# modules/sonos.py
import time
import threading
import logging
from soco import SoCo, discover

logger = logging.getLogger("pccs")


class SonosManager:
    def __init__(self, socketio, config=None):
        self.socketio = socketio
        self.config = config or {}

        sonos = self.config.get('sonos', {}) if isinstance(self.config, dict) else {}

        self.enabled = sonos.get('enabled', True)
        self.target_name = sonos.get('player_name', 'Master Bedroom')
        self.auto_select_first = sonos.get('auto_select_first', True)

        self.poll_interval = int(sonos.get('poll_interval', 3))
        self.discovery_interval = int(sonos.get('discovery_interval', 30))
        self.discovery_timeout = int(sonos.get('discovery_timeout', 8))
        self.default_volume = int(sonos.get('default_volume', -1))

        self._poller_thread = None
        self._running = False
        self.last_state = {}
        self.device = None
        self.all_devices = {}
        self.last_discovery_attempt = 0

    def discover_all(self, log: bool = False):
        """Discover all Sonos devices on the network."""
        if not self.enabled:
            return {}

        now = time.time()
        if now - self.last_discovery_attempt < self.discovery_interval:
            return self.all_devices

        self.last_discovery_attempt = now
        if log:
            logger.info("🔍 Discovering Sonos devices...")

        try:
            devices = list(discover(timeout=self.discovery_timeout))
            new_devices = {d.player_name: d for d in devices}

            # Only log when devices actually change
            if new_devices != self.all_devices:
                self.all_devices = new_devices
                if log or self.all_devices:
                    count = len(self.all_devices)
                    logger.info(f"🎵 Found {count} Sonos speaker(s)")

            return self.all_devices

        except Exception as e:
            logger.warning(f"Sonos discovery failed: {e}")
            self.all_devices = {}
            return {}

    def _apply_default_volume(self):
        """Apply default volume on first connection if configured."""
        if self.device and self.default_volume >= 0:
            try:
                self.device.volume = self.default_volume
                logger.info(f"🔊 Applied default volume: {self.default_volume}%")
            except Exception as e:
                logger.debug(f"Failed to set default volume: {e}")

    def _select_initial_device(self):
        """Select preferred speaker, with optional fallback."""
        if not self.all_devices:
            return

        # Try preferred speaker first (partial, case-insensitive match)
        for dev_name, dev in self.all_devices.items():
            if self.target_name.lower() in dev_name.lower():
                self.device = dev
                self.target_name = dev_name
                logger.info(f"✅ Using preferred speaker: {dev_name}")
                self._apply_default_volume()
                return

        # Fallback to first available speaker
        if self.auto_select_first:
            self.device = next(iter(self.all_devices.values()))
            logger.info(f"✅ Using first available speaker: {self.device.player_name}")
            self._apply_default_volume()
        else:
            logger.info(f"⚠️ Preferred speaker '{self.target_name}' not found "
                       f"(auto_select_first=False)")

    def start(self):
        if self._running or not self.enabled:
            return
        self._running = True

        # Initial discovery
        self.discover_all(log=True)

        count = len(self.all_devices)
        if count > 0:
            self._select_initial_device()
        else:
            logger.info("🎵 Sonos integration loaded (no speakers found)")

        self._poller_thread = threading.Thread(target=self.poll_loop, daemon=True)
        self._poller_thread.start()
        logger.debug("🎵 SonosManager polling started")

    def switch_speaker(self, name: str):
        if name in self.all_devices:
            self.device = self.all_devices[name]
            self.target_name = name

            if isinstance(self.config, dict):
                self.config.setdefault('sonos', {})['player_name'] = name

            logger.info(f"🔄 Switched to Sonos speaker: {name}")
            self._apply_default_volume()
            return True

        logger.warning(f"Speaker '{name}' not found")
        return False

    def get_current_state(self):
        if not self.device:
            return {
                'track': 'Sonos unavailable',
                'artist': '',
                'album_art': '',
                'position': '0:00',
                'duration': '0:00',
                'state': 'STOPPED',
                'volume': 0,
                'is_muted': False,
                'player_name': 'None',
                'available_speakers': list(self.all_devices.keys())
            }

        try:
            track = self.device.get_current_track_info()
            transport = self.device.get_current_transport_info()
            state = transport.get('current_transport_state', 'STOPPED')

            return {
                'track': track.get('title') or "Nothing playing",
                'artist': track.get('artist') or "",
                'album_art': track.get('album_art') or "",
                'position': track.get('position', '0:00'),
                'duration': track.get('duration', '0:00'),
                'state': state,
                'volume': self.device.volume,
                'is_muted': self.device.mute,
                'player_name': self.device.player_name,
                'available_speakers': list(self.all_devices.keys())
            }
        except Exception as e:
            logger.debug(f"Sonos state fetch error: {e}")
            return {
                'track': 'Nothing playing',
                'artist': '',
                'album_art': '',
                'position': '0:00',
                'duration': '0:00',
                'state': 'STOPPED',
                'volume': getattr(self.device, 'volume', 0),
                'is_muted': False,
                'player_name': getattr(self.device, 'player_name', 'None'),
                'available_speakers': list(self.all_devices.keys())
            }

    def poll_loop(self):
        while self._running:
            try:
                self.discover_all(log=False)   # silent during normal polling

                if not self.device and self.all_devices:
                    self._select_initial_device()

                if self.device:
                    current = self.get_current_state()
                    if current != self.last_state:
                        self.socketio.emit('sonos_update', current, namespace='/')
                        self.last_state = current.copy()

            except Exception as e:
                logger.error(f"Sonos poller error: {e}")

            time.sleep(self.poll_interval)

    def stop(self):
        self._running = False
        logger.debug("🛑 SonosManager stopped")

    def execute_command(self, data):
        if not self.enabled:
            return {"error": "Sonos integration is disabled"}

        cmd = data.get('command')

        if cmd == 'status':
            self.socketio.emit('sonos_update', self.get_current_state(), namespace='/')
            return {"success": True}

        # Auto-connect if we don't have a device yet
        if not self.device:
            self.discover_all(log=False)
            if not self.device and self.all_devices:
                self._select_initial_device()

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
                vol = int(data.get('volume') or data.get('value', 50))
                vol = max(0, min(100, vol))
                self.device.volume = vol
                logger.debug(f"Sonos volume set to {vol}%")
            elif cmd == 'mute':
                current_mute = self.device.mute
                self.device.mute = not current_mute
                logger.info(f"🔇 Mute toggled: {'ON' if not current_mute else 'OFF'}")
            elif cmd == 'playpause':
                transport = self.device.get_current_transport_info()
                if transport.get('current_transport_state') == 'PLAYING':
                    self.device.pause()
                else:
                    self.device.play()
            elif cmd == 'seek':
                if not self.device:
                    return {"error": "No Sonos device"}

                position_sec = int(data.get('position', 0))
                
                try:
                    transport = self.device.get_current_transport_info()
                    current_state = transport.get('current_transport_state', 'STOPPED')
                except:
                    current_state = 'STOPPED'

                if current_state not in ('PLAYING', 'PAUSED_PLAYBACK'):
                    logger.info(f"Seek ignored - player is {current_state}")
                    return {"success": False, "reason": "not_playing"}

                hours = position_sec // 3600
                minutes = (position_sec % 3600) // 60
                seconds = position_sec % 60
                time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

                # More aggressive recovery for flaky Sonos seek
                for attempt in range(4):
                    try:
                        # Ensure we're in a good state
                        if attempt > 0:
                            self.device.play()          # force playing state
                            time.sleep(0.4)
                        
                        self.device.seek(time_str)
                        logger.info(f"⏩ Seeked to {time_str} (attempt {attempt+1})")
                        break
                    except Exception as e:
                        if attempt == 3:  # final failure
                            logger.error(f"Sonos seek failed after retries: {e}")
                            return {"error": str(e)}
                        else:
                            logger.warning(f"Seek attempt {attempt+1} failed, retrying... {e}")
                            time.sleep(0.5)

            else:
                return {"error": f"Unknown command: {cmd}"}

            # Refresh state after successful command
            time.sleep(0.4)
            new_state = self.get_current_state()
            self.socketio.emit('sonos_update', new_state, namespace='/')
            return {"success": True, "state": new_state}

        except Exception as e:
            logger.error(f"Sonos command '{cmd}' failed: {e}")
            return {"error": str(e)}