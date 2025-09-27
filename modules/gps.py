# modules/gps.py
import serial
import pynmea2
import threading
import time as time_module
import datetime as dt_module
import pytz
from timezonefinder import TimezoneFinder
from geopy.geocoders import Nominatim
from astral.sun import sun
from astral import LocationInfo
import logging

logger = logging.getLogger(__name__)

class GPSController:
    def __init__(self, port='/dev/ttyAMA0', baudrate=9600, on_event=None, on_broadcast=None, weather=None):
        try:
            self.ser = serial.Serial(port, baudrate, timeout=1)
            logger.info(f"GPS serial initialized on {port} at {baudrate}")
        except Exception as e:
            logger.error(f"Failed to initialize GPS serial: {e}")
            raise
        self.lat = None
        self.lon = None
        self.sats = 0
        self.utc_time = None
        self.date = None
        self.fix = False
        self.on_event = on_event or (lambda event, data: None)
        self.on_broadcast = on_broadcast or (lambda data: None)
        self.weather = weather
        self.geolocator = Nominatim(user_agent="pissmole_camping")
        self.tf = TimezoneFinder()
        self.default_lat = -37.8136
        self.default_lon = 144.9631
        self.default_tz = 'Australia/Melbourne'
        self.previous_fix = None
        self.previous_sats = None
        self.previous_lat = None
        self.previous_lon = None
        self.previous_date = None
        self.previous_geo_failed = False
        self.previous_tz_failed = False
        self.previous_sun_failed = False
        self.last_emit = 0

    def start(self):
        logger.info("Starting GPS update thread")
        threading.Thread(target=self._update_thread, daemon=True).start()

    def update(self):
        line = self.ser.readline().decode('ascii', errors='replace').strip()
        if line.startswith('$'):
            try:
                msg = pynmea2.parse(line)
                if isinstance(msg, pynmea2.types.talker.GGA):
                    self.fix = msg.gps_qual and int(msg.gps_qual) > 0
                    if self.fix:
                        self.lat = msg.latitude
                        self.lon = msg.longitude
                        self.sats = int(msg.num_sats)
                    else:
                        self.lat = None
                        self.lon = None
                        self.sats = 0
                elif isinstance(msg, pynmea2.types.talker.RMC):
                    if msg.status == 'A':
                        self.utc_time = msg.timestamp
                        self.date = msg.datestamp
                    else:
                        self.utc_time = None
                        self.date = None
            except pynmea2.ParseError as e:
                logger.debug(f"GPS parse error: {e}")

    def _update_thread(self):
        while True:
            self.update()
            current_time = time_module.time()
            changed = (
                self.fix != self.previous_fix or
                self.sats != self.previous_sats or
                self.lat != self.previous_lat or
                self.lon != self.previous_lon or
                self.date != self.previous_date
            )
            if changed or (current_time - self.last_emit > 60):
                geo_failed = False
                tz_failed = False
                sun_failed = False
                if self.fix:
                    lat = self.lat
                    lon = self.lon
                    sats = self.sats
                    try:
                        location_res = self.geolocator.reverse((lat, lon), language='en')
                        town = (
                            location_res.raw['address'].get('suburb') or
                            location_res.raw['address'].get('town') or
                            location_res.raw['address'].get('city') or
                            location_res.raw['address'].get('village') or
                            location_res.raw['address'].get('village') or
                            location_res.raw['address'].get('hamlet') or
                            'Unknown'
                        )
                        logger.debug(f"Geolocation: {town}")
                    except Exception as e:
                        town = 'Unknown'
                        geo_failed = True
                        logger.error(f"Geolocation failed: {e}")
                    using_gps_time = self.utc_time is not None and self.date is not None
                    now = dt_module.datetime.utcnow()
                    utc_dt = dt_module.datetime.combine(self.date, self.utc_time) if using_gps_time else now
                    try:
                        tz_str = self.tf.timezone_at(lng=lon, lat=lat)
                        if tz_str is None:
                            raise ValueError("No timezone found")
                    except Exception as e:
                        tz_str = self.default_tz
                        tz_failed = True
                        logger.error(f"Timezone lookup failed: {e}")
                    tz = pytz.timezone(tz_str)
                    local_dt = utc_dt.replace(tzinfo=pytz.utc).astimezone(tz)
                    gps_datetime_str = local_dt.strftime('%Y-%m-%d %H:%M:%S')
                    date_str = local_dt.strftime('%a %b %d')
                    hour = local_dt.hour % 12
                    if hour == 0:
                        hour = 12
                    time_str = f"{hour}:{local_dt.minute:02d} {local_dt.strftime('%p')}"
                    try:
                        loc = LocationInfo(name="Custom", region="Custom", timezone=tz_str, latitude=lat, longitude=lon)
                        s = sun(loc.observer, date=local_dt.date(), tzinfo=tz)
                        sunrise_local = s['sunrise']
                        sunset_local = s['sunset']
                        sunrise_hour = sunrise_local.hour % 12
                        if sunrise_hour == 0:
                            sunrise_hour = 12
                        sunrise_str = f"{sunrise_hour}:{sunrise_local.minute:02d} {sunrise_local.strftime('%p')}"
                        sunset_hour = sunset_local.hour % 12
                        if sunset_hour == 0:
                            sunset_hour = 12
                        sunset_str = f"{sunset_hour}:{sunset_local.minute:02d} {sunset_local.strftime('%p')}"
                    except Exception as e:
                        sunrise_str = '---'
                        sunset_str = '---'
                        sun_failed = True
                        logger.error(f"Sunrise/sunset calculation failed: {e}")
                    satellites_str = f"{sats} Satellites"
                    weather_data = self.weather.get_weather_data(lat, lon) if self.weather else None
                else:
                    lat = self.default_lat
                    lon = self.default_lon
                    sats = 0
                    town = '---'
                    date_str = '---'
                    time_str = '---'
                    gps_datetime_str = None
                    sunrise_str = '---'
                    sunset_str = '---'
                    satellites_str = '---'
                    weather_data = None
                if geo_failed != self.previous_geo_failed:
                    if geo_failed:
                        self.on_event('show_toast', {'message': 'Geolocation failed', 'type': 'warning'})
                    self.previous_geo_failed = geo_failed
                if tz_failed != self.previous_tz_failed:
                    if tz_failed:
                        self.on_event('show_toast', {'message': 'Timezone lookup failed', 'type': 'warning'})
                    self.previous_tz_failed = tz_failed
                if sun_failed != self.previous_sun_failed:
                    if sun_failed:
                        self.on_event('show_toast', {'message': 'Sunrise/sunset calculation failed', 'type': 'warning'})
                    self.previous_sun_failed = sun_failed
                data = {
                    'date': date_str,
                    'time': time_str,
                    'sunrise': sunrise_str,
                    'sunset': sunset_str,
                    'satellites': satellites_str,
                    'location': town,
                    'lat': lat,
                    'lon': lon,
                    'weather': weather_data,
                    'has_fix': self.fix,
                }
                if gps_datetime_str:
                    data['gps_datetime_str'] = gps_datetime_str
                self.on_broadcast(data)
                self.last_emit = current_time
                if self.fix != self.previous_fix:
                    if self.fix:
                        self.on_event('show_toast', {'message': 'GPS fix acquired', 'type': 'message'})
                        logger.info("GPS fix acquired")
                    else:
                        self.on_event('show_toast', {'message': 'GPS fix lost', 'type': 'warning'})
                        logger.warning("GPS fix lost")
                self.previous_fix = self.fix
                self.previous_sats = self.sats
                self.previous_lat = self.lat
                self.previous_lon = self.lon
                self.previous_date = self.date