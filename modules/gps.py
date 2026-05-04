# modules/gps.py
"""
GPS Module for PCCS (Pissmole Camper Control System).

Handles NMEA parsing from serial GPS hardware, reverse geocoding via Nominatim,
sunrise/sunset calculations, and provides a unified state dictionary for the frontend.
Supports a no-fix simulation mode for diagnostics and testing.
"""

import serial
import time
import threading
import math
import logging
from datetime import datetime, date
import zoneinfo
from typing import Tuple, Optional

import pynmea2
from geopy.geocoders import Nominatim
from astral import LocationInfo
from astral.sun import sun
from flask_socketio import SocketIO

logger = logging.getLogger("pccs")


class GPSModule:
    """Manages GPS hardware interface, position tracking, time, location naming, and solar data."""

    # Common Raspberry Pi / USB serial ports
    GPS_PORTS = [
        '/dev/serial0',
        '/dev/ttyS0',
        '/dev/ttyAMA0',
        '/dev/ttyUSB0',
        '/dev/ttyUSB1'
    ]
    GPS_BAUD = 9600

    # Victoria, Australia specific defaults
    FALLBACK_LAT = -37.191
    FALLBACK_LON = 145.711
    FALLBACK_NAME = "Alexandra"

    MOVEMENT_THRESHOLD_KM = 2.0
    SUBURB_UPDATE_INTERVAL = 3600      # seconds
    SUN_UPDATE_INTERVAL = 3600         # seconds
    BROADCAST_INTERVAL = 10            # seconds

    def __init__(self, socketio: SocketIO):
        self.socketio = socketio

        self.serial: Optional[serial.Serial] = None
        self.geolocator: Optional[Nominatim] = None
        self._serial_lock = threading.Lock()

        self.state = {
            "latitude": None,
            "longitude": None,
            "local_time": None,
            "date": None,
            "utc_time": None,
            "satellites": 0,
            "fix_quality": 0,
            "speed_kmh": None,
            "suburb": None,
            "timezone": "Australia/Melbourne",
            "sunrise": None,
            "sunset": None,
            "raw_sentences": [],
            "using_fallback": False,
            "force_no_fix": False,
        }

        self.last_known_lat: Optional[float] = None
        self.last_known_lon: Optional[float] = None
        self.last_suburb_update = 0.0
        self.last_broadcast = 0.0

    def _parse_lat_lon(self, msg) -> Tuple[Optional[float], Optional[float]]:
        """Extract latitude and longitude from an NMEA message and normalise for southern hemisphere."""
        try:
            lat = getattr(msg, 'latitude', None)
            lon = getattr(msg, 'longitude', None)
            if lat is None or lon is None:
                return None, None

            lat = lat if getattr(msg, 'lat_dir', 'N') == 'N' else -lat
            lon = lon if getattr(msg, 'lon_dir', 'E') == 'E' else -lon

            # Melbourne / Victoria safety net - ensure southern hemisphere
            if lat > 0:
                lat = -lat

            return round(lat, 6), round(lon, 6)
        except Exception:
            return None, None

    def init_gps(self) -> bool:
        """Attempt to initialise GPS on common serial ports."""
        for port in self.GPS_PORTS:
            if not __import__('os').path.exists(port):
                continue
            try:
                with self._serial_lock:
                    self.serial = serial.Serial(port, self.GPS_BAUD, timeout=0.8)
                logger.info(f"GPS initialised on {port}")
                return True
            except Exception as e:
                logger.debug(f"Failed to open GPS on {port}: {e}")

        logger.error("No GPS hardware found on any configured port")
        return False

    def init_geolocator(self) -> bool:
        """Initialise Nominatim geolocator (idempotent)."""
        if self.geolocator is not None:
            return True
        try:
            self.geolocator = Nominatim(
                user_agent="pccs-rv-control-system",
                timeout=12
            )
            logger.info("Nominatim geolocator initialised")
            return True
        except Exception as e:
            logger.warning(f"Geolocator initialisation failed: {e}")
            return False

    def set_no_fix_simulation(self, enabled: bool) -> None:
        """Enable or disable 'No GPS Fix' simulation mode for diagnostics."""
        self.state["force_no_fix"] = bool(enabled)
        logger.info(f"GPS No-Fix simulation {'ENABLED' if enabled else 'DISABLED'}")
        self.socketio.emit('gps_update', self.get_state())

    def get_state(self) -> dict:
        """Return current GPS state, applying no-fix simulation when active."""
        state = self.state.copy()
        if state.get("force_no_fix"):
            state.update({
                "fix_quality": 0,
                "satellites": 0,
                "latitude": None,
                "longitude": None,
                "speed_kmh": None,
            })
        return state

    def start_reader(self) -> None:
        """Start background GPS reader and sun refresh threads."""
        self.init_geolocator()
        threading.Thread(target=self._reader_loop, daemon=True, name="GPS_Reader").start()
        threading.Thread(target=self._sun_refresh_loop, daemon=True, name="SunRefresh").start()

    def _reader_loop(self) -> None:
        """Main GPS NMEA parsing loop."""
        while True:
            if not self.serial or not getattr(self.serial, 'is_open', False):
                time.sleep(0.5)
                continue

            try:
                with self._serial_lock:
                    line_bytes = self.serial.readline()

                if not line_bytes:
                    time.sleep(0.05)
                    continue

                line = line_bytes.decode('ascii', errors='ignore').strip()
                if not line or not line.startswith('$'):
                    continue

                # Keep recent sentences for diagnostics
                self.state["raw_sentences"] = (self.state["raw_sentences"] + [line])[-15:]

                msg = pynmea2.parse(line)
                position_updated = False

                # No-fix simulation takes precedence
                if self.state.get("force_no_fix"):
                    now = time.time()
                    if now - self.last_broadcast > self.BROADCAST_INTERVAL:
                        self.socketio.emit('gps_update', self.get_state())
                        self.last_broadcast = now
                    time.sleep(0.03)
                    continue

                # GGA - Fix quality and position
                if isinstance(msg, pynmea2.GGA):
                    quality = getattr(msg, 'quality', None) or getattr(msg, 'gps_qual', None) or 0
                    self.state["fix_quality"] = int(quality) if quality is not None else 0
                    self.state["satellites"] = int(getattr(msg, 'num_sats', 0) or 0)

                    lat, lon = self._parse_lat_lon(msg)
                    if lat is not None:
                        self.state["latitude"] = lat
                        self.state["longitude"] = lon
                        position_updated = True

                # RMC - Position, time, speed
                if isinstance(msg, pynmea2.RMC):
                    lat, lon = self._parse_lat_lon(msg)
                    if lat is not None:
                        self.state["latitude"] = lat
                        self.state["longitude"] = lon
                        position_updated = True

                    if getattr(msg, 'datetime', None):
                        utc_dt = msg.datetime.replace(tzinfo=zoneinfo.ZoneInfo("UTC"))
                        self.state["utc_time"] = utc_dt.isoformat()

                        try:
                            local_tz = zoneinfo.ZoneInfo(self.state["timezone"])
                            local_dt = utc_dt.astimezone(local_tz)
                            self.state["local_time"] = local_dt.strftime("%I:%M:%S %p")
                            self.state["date"] = local_dt.strftime("%A, %d %B %Y")
                        except Exception:
                            self.state["local_time"] = utc_dt.strftime("%H:%M:%S UTC")
                            self.state["date"] = utc_dt.strftime("%Y-%m-%d")

                    if getattr(msg, 'spd_over_grnd', None) is not None:
                        self.state["speed_kmh"] = round(float(msg.spd_over_grnd) * 1.852, 1)

                # Broadcast state when position changes
                now = time.time()
                if position_updated and (now - self.last_broadcast > self.BROADCAST_INTERVAL):
                    self.state["using_fallback"] = False
                    self.socketio.emit('gps_update', self.get_state())
                    self.last_broadcast = now

                    if self.state["fix_quality"] >= 1:
                        if not self.state.get("sunrise"):
                            self._update_sun_times()
                        if now - self.last_suburb_update > self.SUBURB_UPDATE_INTERVAL:
                            self._update_suburb()

            except pynmea2.ParseError:
                pass
            except Exception as e:
                logger.error(f"GPS reader error: {e}")
                time.sleep(0.2)

            time.sleep(0.03)

    def _sun_refresh_loop(self) -> None:
        """Periodic sun times refresh."""
        while True:
            time.sleep(self.SUN_UPDATE_INTERVAL)
            if self.state.get("latitude") and self.state.get("fix_quality", 0) >= 1:
                self._update_sun_times()

    def _update_sun_times(self) -> bool:
        """Calculate sunrise and sunset for current location."""
        lat = self.state.get("latitude")
        lon = self.state.get("longitude")
        if not lat or not lon:
            return False

        try:
            location = LocationInfo(latitude=lat, longitude=lon)
            s = sun(location.observer, date=date.today())
            local_tz = zoneinfo.ZoneInfo(self.state["timezone"])

            sunrise = s["sunrise"].astimezone(local_tz)
            sunset = s["sunset"].astimezone(local_tz)

            self.state["sunrise"] = sunrise.strftime("%I:%M %p")
            self.state["sunset"] = sunset.strftime("%-I:%M %p")

            self.socketio.emit('gps_update', self.get_state())
            return True
        except Exception as e:
            logger.error(f"Sun times calculation failed: {e}")
            return False

    def _haversine_km(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate great-circle distance in kilometres."""
        R = 6371.0
        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        lon2_rad = math.radians(lon2)

        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad

        a = (math.sin(dlat / 2)**2 +
             math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def _update_suburb(self) -> None:
        """Update suburb name using online Nominatim or offline fallback towns."""
        lat = self.state.get("latitude")
        lon = self.state.get("longitude")
        if not lat or not lon or self.state.get("force_no_fix"):
            return

        # Skip if movement is insignificant
        if self.last_known_lat is not None and self.last_known_lon is not None:
            distance = self._haversine_km(self.last_known_lat, self.last_known_lon, lat, lon)
            if distance < self.MOVEMENT_THRESHOLD_KM:
                self.last_suburb_update = time.time()
                return

        self.last_known_lat = lat
        self.last_known_lon = lon

        try:
            # Prefer online reverse geocoding
            if self.geolocator:
                try:
                    location = self.geolocator.reverse(
                        (lat, lon),
                        exactly_one=True,
                        timeout=12,
                        language='en',
                        addressdetails=True
                    )
                    if location and location.raw and location.raw.get('address'):
                        addr = location.raw['address']
                        name_keys = ['suburb', 'town', 'village', 'hamlet', 'locality', 'city', 'place']
                        new_suburb = next((addr[key] for key in name_keys if addr.get(key)), None)

                        if new_suburb:
                            logger.info(f"Location: {new_suburb} (lat: {lat:.6f}, lon: {lon:.6f})")
                            self.state["suburb"] = new_suburb
                            self.state["using_fallback"] = False
                            self.socketio.emit('gps_update', self.get_state())
                            self.last_suburb_update = time.time()
                            return
                except Exception as e:
                    logger.debug(f"Nominatim lookup failed: {e}")

            # Offline fallback using major Victorian towns
            major_towns = [
                {"name": "Alexandra", "lat": -37.191, "lon": 145.711},
                {"name": "Mansfield", "lat": -37.052, "lon": 146.083},
                {"name": "Eildon", "lat": -37.233, "lon": 145.917},
                {"name": "Yea", "lat": -37.213, "lon": 145.424},
                {"name": "Marysville", "lat": -37.510, "lon": 145.733},
                {"name": "Healesville", "lat": -37.654, "lon": 145.514},
                {"name": "Lilydale", "lat": -37.758, "lon": 145.350},
                {"name": "Melbourne", "lat": -37.8136, "lon": 144.9631},
            ]

            closest = None
            min_dist = float('inf')
            for town in major_towns:
                dist = self._haversine_km(lat, lon, town["lat"], town["lon"])
                if dist < min_dist:
                    min_dist = dist
                    closest = town

            if closest and min_dist < 120:
                new_suburb = (
                    closest["name"] if min_dist < 10
                    else f"{closest['name']} ({min_dist:.0f} km away)"
                )
            else:
                new_suburb = f"{lat:.4f}, {lon:.4f}"

            logger.info(f"Location (offline): {new_suburb}")
            self.state["suburb"] = new_suburb
            self.state["using_fallback"] = False
            self.socketio.emit('gps_update', self.get_state())

        except Exception as e:
            logger.warning(f"Suburb update failed: {e}")
        finally:
            self.last_suburb_update = time.time()