# modules/sonos.py
import time
import threading
import logging
from soco import SoCo, discover
from soco.exceptions import SoCoUPnPException, UnknownSoCoException

logger = logging.getLogger(__name__)


class SonosManager:
    def __init__(self, socketio, config=None):
        self.socketio = socketio
        self.config = config or {}
        
        # Config
        sonos_section = self.config.get('sonos', {}) if isinstance(self.config, dict) else {}
        self.target_name = sonos_section.get('player_name', 'Play:1')
        
        self.poll_interval = 3  # seconds
        self._poller_thread = None
        self._running = False
        self.last_state = {}
        self.device = None
        self.last_discovery_attempt = 0

    def discover_device(self):
        """Find the Sonos speaker"""
        now = time.time()
        if now - self.last_discovery_attempt < 30:
            return self.device

        self.last_discovery_attempt = now
        logger.info("🔍 Discovering Sonos devices...")

        try:
            devices = list(discover(timeout=8))
            if not devices:
                logger.info("⚠️ No Sonos devices found on the network")
                self.device = None
                return None

            for d in devices:
                if self.target_name.lower() in d.player_name.lower():
                    self.device = d
                    logger.info(f"✅ Found target Sonos: {d.player_name} @ {d.ip_address}")
                    return d

            self.device = devices[0]
            logger.info(f"✅ Using first available Sonos: {self.device.player_name} @ {self.device.ip_address}")
            return self.device

        except Exception as e:
            logger.warning(f"Sonos discovery failed: {e}")
            self.device = None
            return None

    def get_current_state(self):
        """Get now playing information"""
        if not self.device:
            return {
                'track': 'Sonos unavailable',
                'artist': '',
                'album': '',
                'album_art': '',
                'position': '0:00',
                'duration': '0:00',
                'state': 'STOPPED',
                'volume': 0,
                'is_muted': False,
                'player_name': 'None'
            }

        try:
            track = self.device.get_current_track_info()
            transport = self.device.get_current_transport_info()
            state = transport.get('current_transport_state', 'STOPPED')

            return {
                'track': track.get('title') or "Nothing playing",
                'artist': track.get('artist') or "",
                'album': track.get('album') or "",
                'album_art': track.get('album_art') or "",
                'position': track.get('position', '0:00'),
                'duration': track.get('duration', '0:00'),
                'state': state,
                'volume': self.device.volume,
                'is_muted': self.device.mute,
                'player_name': self.device.player_name
            }

        except (SoCoUPnPException, UnknownSoCoException, Exception) as e:
            logger.debug(f"Sonos state fetch error (normal when idle): {e}")
            return {
                'track': 'Nothing playing',
                'artist': '',
                'album': '',
                'album_art': '',
                'position': '0:00',
                'duration': '0:00',
                'state': 'STOPPED',
                'volume': getattr(self.device, 'volume', 0),
                'is_muted': False,
                'player_name': getattr(self.device, 'player_name', 'None')
            }

    def poll_loop(self):
        """Background poller"""
        while self._running:
            try:
                if not self.device:
                    self.discover_device()

                if self.device:
                    current = self.get_current_state()

                    if current != self.last_state:
                        # FIXED: No 'broadcast=True' when using socketio.emit() from background thread
                        self.socketio.emit(
                            'sonos_update', 
                            current, 
                            namespace='/'
                        )
                        self.last_state = current.copy()
                        logger.debug(f"🎵 Sonos update: {current.get('track')[:50]}...")

            except Exception as e:
                logger.error(f"Sonos poller error: {e}")

            time.sleep(self.poll_interval)

    def start(self):
        if self._running:
            return
        self._running = True
        self._poller_thread = threading.Thread(target=self.poll_loop, daemon=True)
        self._poller_thread.start()
        logger.info("🎵 SonosManager background poller started")

    def stop(self):
        self._running = False
        logger.info("🛑 SonosManager stopped")

    def execute_command(self, data):
        """Handle commands from frontend"""
        cmd = data.get('command')

        if cmd == 'status':
            new_state = self.get_current_state()
            self.socketio.emit('sonos_update', new_state, namespace='/')
            return {"success": True}

        if not self.device:
            self.discover_device()
            if not self.device:
                new_state = self.get_current_state()
                self.socketio.emit('sonos_update', new_state, namespace='/')
                return {"error": "No Sonos device found"}

        try:
            if cmd == 'play':
                self.device.play()
            elif cmd == 'pause':
                self.device.pause()
            elif cmd == 'next':
                self.device.next()
            elif cmd == 'previous':
                self.device.previous()
            elif cmd == 'volume':
                vol = int(data.get('value', 50))
                self.device.volume = max(0, min(100, vol))
            elif cmd == 'mute':
                self.device.mute = not self.device.mute
            elif cmd == 'playpause':
                transport = self.device.get_current_transport_info()
                if transport.get('current_transport_state') == 'PLAYING':
                    self.device.pause()
                else:
                    self.device.play()
            else:
                return {"error": f"Unknown command: {cmd}"}

            time.sleep(0.4)
            new_state = self.get_current_state()
            self.socketio.emit('sonos_update', new_state, namespace='/')
            return {"success": True, "state": new_state}

        except Exception as e:
            logger.error(f"Sonos command '{cmd}' failed: {e}")
            return {"error": str(e)}