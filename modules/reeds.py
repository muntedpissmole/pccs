# modules/reeds.py
import threading
import logging
import time
from typing import Callable, Dict, Optional, Tuple, List, DefaultDict
from collections import defaultdict
import subprocess
import socket
from datetime import datetime

from flask_socketio import SocketIO
from gpiozero import Button

from .gpio import GPIODeviceManager

logger = logging.getLogger("pccs")


class ReedManager:
    def __init__(
        self,
        config,
        gpio_manager: GPIODeviceManager,
        socketio: SocketIO,
        rgb_lights: set,
        light_map: dict,
        set_rgb_bug_light: Callable,
        send_command: Callable,
        ramp_and_broadcast: Callable,
        toast_manager=None,
    ):
        self.config = config
        self.gpio = gpio_manager
        self.socketio = socketio

        # Injected dependencies
        self.RGB_LIGHTS = rgb_lights
        self.LIGHT_MAP = light_map
        self.set_rgb_bug_light = set_rgb_bug_light
        self.send_command = send_command
        self.ramp_and_broadcast = ramp_and_broadcast

        self.stop_event = threading.Event()
        self.monitor_thread: threading.Thread | None = None

        # Configuration from pccs.conf
        self.reed_ramp_time_ms = config.getint('lighting', 'reed_ramp_time_ms')
        self.interval: float = config.getfloat('reed_monitor', 'monitor_interval')

        self.ambient_locked = False
        self.current_ambient_phase = None
        self.ambient_active = False
        self.last_all_closed_state = True
        self.startup_ambient_done = False

        # CHANGED: Now supports multiple callbacks per reed (lights + screens)
        self.on_reed_change: DefaultDict[str, List[Callable]] = defaultdict(list)

        # Force states
        self.forced_states: Dict[str, dict] = {}
        self.force_lock = threading.Lock()
        
        self.last_ambient_update = 0
        self.last_broadcast = 0

        self.AMBIENT_THROTTLE_MS = self.config.getint('reed_monitor', 'ambient_throttle_ms', fallback=120)
        self.BROADCAST_THROTTLE_MS = self.config.getint('reed_monitor', 'broadcast_throttle_ms', fallback=80)

        self.REED_DEBOUNCE_MS = self.config.getint('reed_monitor', 'reed_debounce_ms', fallback=50)
        
        # ====================== AMBIENT & PHASE SETTINGS ======================
        self.ambient_lights: list[str] = []
        self.all_closed_action: str = "off"
        self.phase_settings: Dict[str, Dict[str, Tuple[int, str]]] = {}

        # ====================== FRIENDLY NAME MAP ======================
        self.friendly_names: Dict[str, str] = {}
        try:
            if self.config.has_section('reeds'):
                for key, value in self.config.items('reeds'):
                    parts = [p.strip() for p in value.split('|')]
                    if parts and len(parts) > 0:
                        friendly = parts[0]
                        self.friendly_names[key.strip()] = friendly
        except Exception as e:
            logger.debug(f"Could not build friendly name map: {e}")

        try:
            if self.config.has_section('ambient'):
                self.all_closed_action = self.config.get('ambient', 'all_closed_action', 
                                                       fallback='off').strip().lower()
                
                try:
                    lights_value = self.config.get('ambient', 'lights')
                    if lights_value and lights_value.strip():
                        logger.warning("⚠️ [ambient] 'lights =' is deprecated and ignored. "
                                      "Ambient lights are now auto-detected from [ambient.*] sections.")
                except Exception:
                    pass
            else:
                logger.warning("⚠️ No [ambient] section found")

            ambient_count = 0
            for section in self.config.sections():
                if not section.startswith('ambient.'):
                    continue

                light_name = section.split('.', 1)[1].strip()
                self.ambient_lights.append(light_name)
                self.phase_settings[light_name] = {}

                for phase in ['day', 'evening', 'night']:
                    try:
                        val = self.config.get(section, phase, fallback=None)
                        if val is not None:
                            val = str(val).strip()
                            if ',' in val:
                                b_str, mode = [x.strip() for x in val.split(',', 1)]
                                self.phase_settings[light_name][phase] = (int(b_str), mode.lower())
                            else:
                                self.phase_settings[light_name][phase] = (int(val), 'white')
                        elif phase == 'day':
                            self.phase_settings[light_name]['day'] = (0, 'white')
                    except Exception:
                        if phase == 'day':
                            self.phase_settings[light_name]['day'] = (0, 'white')
                        continue

                ambient_count += 1
                logger.debug(f"✅ Loaded ambient light '{light_name}' with phases: "
                            f"{list(self.phase_settings[light_name].keys())}")

            reed_only_count = 0
            for section in self.config.sections():
                if not section.startswith('reed_phases.'):
                    continue

                light_name = section.split('.', 1)[1].strip()

                if light_name in self.phase_settings:
                    continue

                self.phase_settings[light_name] = {}
                for phase in ['day', 'evening', 'night']:
                    try:
                        val = self.config.get(section, phase, fallback=None)
                        if val is not None:
                            val = str(val).strip()
                            if ',' in val:
                                b_str, mode = [x.strip() for x in val.split(',', 1)]
                                self.phase_settings[light_name][phase] = (int(b_str), mode.lower())
                            else:
                                self.phase_settings[light_name][phase] = (int(val), 'white')
                    except Exception:
                        continue

                if self.phase_settings[light_name]:
                    reed_only_count += 1

            logger.info(
                f"💡 Loaded {ambient_count} ambient lights "
                f"and {reed_only_count} reed-controlled lights"
            )

        except Exception as e:
            logger.error(f"Failed to load ambient/reed phases: {e}", exc_info=True)
            
        # ====================== REED INTERLOCKS ======================
        self.interlocks: Dict[str, list[str]] = {}
        self.dependents: DefaultDict[str, list[str]] = defaultdict(list)
        
        try:
            if self.config.has_section('reeds.interlocks'):
                for key, value in self.config.items('reeds.interlocks'):
                    reed_name = key.strip()
                    required_str = str(value).strip()
                    
                    if required_str:
                        required = [x.strip() for x in required_str.split(',') if x.strip()]
                        self.interlocks[reed_name] = required
                        for req in required:
                            self.dependents[req].append(reed_name)
                        
                        # Friendly name logging
                        friendly_reed = self.friendly_names.get(reed_name, reed_name)
                        friendly_reqs = [self.friendly_names.get(r, r) for r in required]
                        logger.info(f"🔒 Loaded interlock: {friendly_reed} requires {', '.join(friendly_reqs)}")
                    else:
                        logger.warning(f"⚠️ Empty interlock for {reed_name}")
                        
            if self.interlocks:
                logger.debug(f"🔒 Loaded {len(self.interlocks)} reed interlocks")
            else:
                logger.debug("No reed interlocks configured")
                
        except Exception as e:
            logger.error(f"Failed to load [reeds.interlocks]: {e}", exc_info=True)

        # ====================== TOUCHSCREENS (on/off only) ======================
        self.screens: Dict[str, dict] = {}
        self.screen_states: Dict[str, bool] = {}   # True = on, False = off

        try:
            if self.config.has_section('screens'):
                for key, value in self.config.items('screens'):
                    parts = [p.strip() for p in value.split('|')]
                    if len(parts) < 5:
                        logger.warning(f"⚠️ Invalid screen line: {key}")
                        continue

                    name = key.strip()
                    friendly = parts[0]
                    linked_reed = parts[1]
                    host = parts[2]
                    username = parts[3]
                    brightness_path = parts[4]
                    icon = parts[5] if len(parts) > 5 else 'fa-display'

                    self.screens[name] = {
                        'friendly': friendly,
                        'linked_reed': linked_reed,
                        'host': host,
                        'username': username,
                        'brightness_path': brightness_path,
                        'icon': icon
                    }
                    self.screen_states[name] = False

                    self.register_trigger(linked_reed, self._make_screen_trigger(linked_reed))

                    logger.info(f"🖥️ Screen '{friendly}' linked to reed '{linked_reed}' @ {host}")
        except Exception as e:
            logger.error(f"Failed to load [screens] section: {e}", exc_info=True)

        self.registered = False
        self.last_change_time: Dict[str, float] = {}

        logger.info("🚪 ReedManager initialized")

    def get_light_settings(self, phase: str, light_name: str) -> Optional[Tuple[int, str]]:
        phase = str(phase).strip().lower()
        if light_name not in self.phase_settings:
            return None
        config = self.phase_settings[light_name]
        if phase not in config:
            return None
        return config[phase]

    def _set_ambient_light(self, light_name: str, brightness: int, mode: str = "white", source: str = "ambient"):
        ramp_ms = self.reed_ramp_time_ms

        if light_name in self.RGB_LIGHTS and self.set_rgb_bug_light:
            self.set_rgb_bug_light(light_name, brightness, mode)
        elif light_name in self.LIGHT_MAP and self.send_command:
            pwm = int(brightness * 2.55)
            self.send_command(f"RAMP {self.LIGHT_MAP[light_name]} {pwm} {ramp_ms}")

        if self.ramp_and_broadcast:
            self.ramp_and_broadcast(
                light_name, brightness, ramp_ms,
                mode if light_name in self.RGB_LIGHTS else None,
                source=source
            )

    # ====================== AMBIENT LIGHTS ======================
    def update_ambient_lights(self, force=False):
        now = time.time() * 1000
        if not force and now - self.last_ambient_update < self.AMBIENT_THROTTLE_MS:
            return
        self.last_ambient_update = now

        all_closed = all(bool(self.get_effective_state(name)) for name in self.gpio.reed_states)

        just_opened = not all_closed and self.last_all_closed_state
        just_closed = all_closed and not self.last_all_closed_state

        self.last_all_closed_state = all_closed

        if all_closed:
            self.ambient_active = False
            logger.info("🌙 All reeds closed → Applying all_closed_action")

            for light_name in self.ambient_lights:
                if self.all_closed_action == "off":
                    self._set_ambient_light(light_name, 0, "white", source="ambient")
                elif self.all_closed_action == "dim":
                    settings = self.get_light_settings("night", light_name)
                    b, m = settings if settings else (0, "white")
                    self._set_ambient_light(light_name, b, m, source="ambient")

        elif just_opened:
            self.ramp_ambient_lights(source="reed")


    def ramp_ambient_lights(self, phase: str = None, source: str = "auto"):
        """Single source of truth for ramping ambient lights when reeds open."""
        if phase is None:
            if not hasattr(self, 'phase_manager') or self.phase_manager is None:
                phase = "evening"
            else:
                phase = self.phase_manager.get_phase().lower()

        now = time.time() * 1000
        is_forced = source in ("startup", "phase_change")

        if not is_forced and now - self.last_ambient_update < self.AMBIENT_THROTTLE_MS * 1.5:
            logger.debug(f"⏭️ Ambient ramp throttled ({source})")
            return

        self.last_ambient_update = now
        self.ambient_active = True

        logger.info(f"🌟 Ramping ambient lights to {phase} [{source}]")

        for light_name in self.ambient_lights:
            settings = self.get_light_settings(phase, light_name)
            b, m = settings if settings else (0, "white")
            self._set_ambient_light(light_name, b, m, source=source)

        # Handle open reed-controlled lights
        for reed_name in list(self.gpio.reed_states.keys()):
            if not self.get_effective_state(reed_name):
                self._apply_light_for_reed(reed_name, is_phase_change=True)

    # ====================== CENTRAL LIGHT APPLICATION ======================
    def _apply_light_for_reed(self, reed_name: str, is_phase_change: bool = False):
        effective_closed = self.get_effective_state(reed_name)

        if reed_name in self.interlocks and not self.is_interlock_satisfied(reed_name):
            if not effective_closed:
                logger.debug(f"🔒 Interlock blocked {reed_name}")
            effective_closed = True

        # UPDATED: Call ALL callbacks (light + screen)
        if reed_name in self.on_reed_change:
            for callback in self.on_reed_change[reed_name]:
                try:
                    callback(effective_closed, is_phase_change=is_phase_change)
                except Exception as e:
                    logger.error(f"Failed to apply callback for {reed_name}: {e}", exc_info=True)

    # ====================== PHASE CHANGE HANDLER ======================
    def apply_initial_ambient_state(self, timeout=6.0):
        """Run once at startup."""
        if getattr(self, 'startup_ambient_done', False):
            return

        if not hasattr(self, 'phase_manager') or self.phase_manager is None:
            logger.warning("⚠️ PhaseManager not attached")
            return

        logger.debug("🚪 Waiting for valid phase from PhaseManager...")

        start_time = time.time()
        phase = None

        while time.time() - start_time < timeout:
            phase = self.phase_manager.get_phase()
            if phase and phase.lower() in ("day", "evening", "night"):
                break
            time.sleep(0.25)

        if not phase or phase.lower() not in ("day", "evening", "night"):
            phase = "evening"
            logger.warning(f"⚠️ No valid phase after {timeout}s → using fallback '{phase}'")

        all_closed = all(bool(self.get_effective_state(name)) for name in self.gpio.reed_states)

        self.last_all_closed_state = all_closed
        self.startup_ambient_done = True

        if not all_closed:
            self.ramp_ambient_lights(phase=phase, source="startup")
        else:
            self.ambient_active = False
            logger.info("🌙 All closed at startup")
            self.update_ambient_lights(force=True)
            
    def reapply_all_open_lights(self, phase_manager):
        """Called by PhaseManager on every phase change."""
        if not self.startup_ambient_done:
            return

        logger.info(f"🌗 Phase changed → reapplying levels for open reeds")
        self.ramp_ambient_lights(source="phase change")
        
        for name in list(self.gpio.reed_states.keys()):
            if not self.get_effective_state(name):   # if open
                self._apply_light_for_reed(name, is_phase_change=True)
                
    def apply_initial_screen_states(self):
        """Evaluate current reed states and set all linked touchscreens accordingly at startup."""
        if not self.screens:
            logger.debug("🖥️ No touchscreens configured")
            return

        logger.debug("🖥️ Applying initial touchscreen states based on reeds...")

        success = 0
        unreachable = 0
        failed = 0

        for screen_name, conf in self.screens.items():
            reed_name = conf['linked_reed']
            effective_closed = self.get_effective_state(reed_name)
            friendly = conf.get('friendly', screen_name)

            action = "sleep" if effective_closed else "wake"

            ok = self._set_screen_state(screen_name, sleep=effective_closed)

            if ok:
                success += 1
                logger.debug(f"🖥️ Initial {action} → {friendly}")
            elif effective_closed and self._was_unreachable(screen_name):
                unreachable += 1
                logger.debug(f"🖥️ {friendly} unreachable (expected if off)")
            else:
                failed += 1
                logger.warning(f"🖥️ Failed to {action} {friendly} during initial setup")

            time.sleep(0.15)

        total = len(self.screens)
        if failed == 0:
            if unreachable > 0:
                logger.info(f"🖥️ {success} touchscreen(s) initialized ({unreachable} unreachable)")
            else:
                logger.info(f"✅ All {success} touchscreen(s) initialized")
        else:
            logger.warning(f"🖥️ Initial screen setup: {success} OK, {unreachable} unreachable, {failed} failed")

    # ====================== FORCE CONTROL ======================
    def force_state(self, reed_name: str, forced_closed: bool) -> bool:
        if reed_name not in self.gpio.reed_states:
            logger.warning(f"❌ Unknown reed switch: {reed_name}")
            return False

        with self.force_lock:
            if reed_name in self.forced_states:
                old_timer = self.forced_states[reed_name].get('timer')
                if old_timer:
                    old_timer.cancel()
            self.forced_states[reed_name] = {'state': forced_closed}
            logger.debug(f"🔧 [FORCE] {reed_name} → {'Closed' if forced_closed else 'Open'}")

        affected = self.get_affected_lights(reed_name)
        for light_name in affected:
            self._apply_light_for_reed(light_name)

        self.broadcast_update()
        self.update_ambient_lights()
        return True

    def clear_force(self, reed_name: str) -> bool:
        was_forced = False
        with self.force_lock:
            if reed_name in self.forced_states:
                timer = self.forced_states[reed_name].get('timer')
                if timer:
                    timer.cancel()
                del self.forced_states[reed_name]
                logger.debug(f"🔄 [FORCE] Cleared force on {reed_name}")
                was_forced = True

        if was_forced:
            affected = self.get_affected_lights(reed_name)
            for light_name in affected:
                self._apply_light_for_reed(light_name)

            self.broadcast_update()
            self.update_ambient_lights()
            return True
        return False

    def clear_all_forces(self):
        with self.force_lock:
            for data in list(self.forced_states.values()):
                timer = data.get('timer')
                if timer:
                    timer.cancel()
            self.forced_states.clear()
        logger.debug("🧹 Cleared all forced reed states")
        self.broadcast_update()
        self.update_ambient_lights()

    def get_forced_states(self) -> Dict[str, bool]:
        with self.force_lock:
            return {name: data['state'] for name, data in self.forced_states.items()}

    def get_effective_state(self, reed_name: str) -> Optional[bool]:
        with self.force_lock:
            if reed_name in self.forced_states:
                return self.forced_states[reed_name]['state']
        return self.gpio.reed_states.get(reed_name)
        
    # ====================== INTERLOCK HELPERS ======================
    def is_interlock_satisfied(self, reed_name: str) -> bool:
        if reed_name not in self.interlocks:
            return True
        
        for required in self.interlocks[reed_name]:
            if self.get_effective_state(required) is True:
                return False
        return True

    def get_affected_lights(self, reed_name: str) -> list[str]:
        affected = {reed_name}
        affected.update(self.dependents[reed_name])
        return list(affected)
        
    # ====================== REED EVENT HANDLING ======================
    def register_event_handlers(self):
        if self.registered:
            return

        for name, button in self.gpio.reeds.items():
            button.when_pressed = lambda btn, n=name: self._on_reed_event(n, closed=True)
            button.when_released = lambda btn, n=name: self._on_reed_event(n, closed=False)

        self.registered = True
        logger.debug(f"🚪 Registered event handlers for {len(self.gpio.reeds)} reeds")

    def _on_reed_event(self, name: str, closed: bool):
        logger.debug(f"Reed event received: {name} → {'Closed' if closed else 'Open'}")
        now = time.time()
        delta_ms = (now - self.last_change_time.get(name, 0)) * 1000
        
        if delta_ms < self.REED_DEBOUNCE_MS:
            logger.debug(f"Reed {name} debounced")
            return

        self.gpio.reed_states[name] = closed
        self.last_change_time[name] = now

        effective_closed = self.get_effective_state(name)
        action = "CLOSED" if effective_closed else "OPEN"
        
        logger.info(f"🚪 Reed {name} → {action} [EVENT]  (raw: {closed})")
        
        # Trigger lights
        for light_name in self.get_affected_lights(name):
            self._apply_light_for_reed(light_name)

        self._throttled_broadcast_and_ambient()

    # ====================== MONITOR FALLBACK ======================
    def start_monitor(self, interval: float = None):
        if interval is not None:
            self.interval = interval
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="ReedMonitor"
        )
        self.monitor_thread.start()

    def _monitor_loop(self):
        logger.debug("🚪 Reed monitor started in POLLING mode")

        last_physical = {
            name: self.gpio.reeds[name].is_pressed 
            for name in self.gpio.reed_states
        }

        while not self.stop_event.is_set():
            changed = False
            now = time.time()

            for name in list(self.gpio.reed_states.keys()):
                try:
                    device = self.gpio.reeds.get(name)
                    if not device:
                        continue

                    real_closed = device.is_pressed

                    if real_closed != last_physical.get(name):
                        self.gpio.reed_states[name] = real_closed
                        last_physical[name] = real_closed
                        changed = True

                        effective_closed = self.get_effective_state(name)
                        action = "Closed" if effective_closed else "Open"

                        logger.info(f"🚪 Reed {name} → {action}")

                        for light_name in self.get_affected_lights(name):
                            self._apply_light_for_reed(light_name)

                except Exception as e:
                    logger.debug(f"Monitor error on {name}: {e}")
                    continue

            if changed:
                self._throttled_broadcast_and_ambient()

            self.stop_event.wait(self.interval)

    def stop(self):
        self.stop_event.set()
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=1.5)

    def register_trigger(self, reed_name: str, callback: Callable):
        self.on_reed_change[reed_name].append(callback)

    def broadcast_update(self):
        try:
            self.socketio.emit('reed_update', {
                'states': self.get_states(),
                'forced': self.get_forced_states()
            })
        except Exception as e:
            logger.warning(f"Failed to emit reed_update: {e}")
            
    def _throttled_broadcast_and_ambient(self):
        now = time.time() * 1000
        if now - self.last_broadcast < self.BROADCAST_THROTTLE_MS:
            return
        self.last_broadcast = now

        self.broadcast_update()

        all_closed = all(bool(self.get_effective_state(name)) for name in self.gpio.reed_states)

        if not all_closed and not self.ambient_active:
            self.ramp_ambient_lights(source="throttled")
        elif all_closed:
            self.update_ambient_lights(force=True)

    def get_states(self) -> Dict:
        return self.gpio.reed_states.copy()

    def get_reed_ramp_time(self) -> int:
        return self.reed_ramp_time_ms

    # ====================== TOUCHSCREEN CONTROL ======================
    def _make_screen_trigger(self, reed_name: str):
        """Create callback for screen control when linked reed changes."""
        def screen_trigger(is_closed: bool, is_phase_change: bool = False):
            for screen_name, conf in self.screens.items():
                if conf['linked_reed'] == reed_name:
                    if is_closed:
                        self._sleep_screen(screen_name)
                    else:
                        self._wake_screen(screen_name)
        return screen_trigger

    def _sleep_screen(self, screen_name: str):
        """Turn screen completely off."""
        conf = self.screens.get(screen_name, {})
        friendly = conf.get('friendly', screen_name)

        cmd = f"ssh {conf['username']}@{conf['host']} \"echo 0 > {conf['brightness_path']}\""

        try:
            result = subprocess.run(cmd, shell=True, timeout=5, capture_output=True, text=True)
            success = result.returncode == 0
        except Exception:
            success = False

        self.screen_states[screen_name] = False

        # ←←← THIS IS THE IMPORTANT PART
        self.socketio.emit('screen_update', {
            'name': screen_name,
            'on': False,
            'online': True,           # assume reachable unless we know otherwise
            'config': conf            # send full config (friendly + icon)
        })

        if success:
            logger.info(f"🖥️ Slept screen: {friendly}")
        else:
            logger.debug(f"🖥️ Sleep command sent for {friendly} (may be unreachable)")

    def _wake_screen(self, screen_name: str):
        """Wake + realistic connectivity check"""
        success = self._set_screen_state(screen_name, sleep=False)
        if success:
            logger.info(f"🖥️ Woke screen: {self.screens[screen_name].get('friendly', screen_name)}")
        else:
            logger.debug(f"🖥️ Wake command sent but screen unreachable (expected if powered off)")


    def _sleep_screen(self, screen_name: str):
        """Sleep + realistic connectivity check"""
        success = self._set_screen_state(screen_name, sleep=True)
        if success:
            logger.info(f"🖥️ Slept screen: {self.screens[screen_name].get('friendly', screen_name)}")
        else:
            logger.debug(f"🖥️ Sleep command sent but screen unreachable")
        
    def _set_screen_state(self, screen_name: str, sleep: bool) -> bool:
        """Internal helper that returns True if SSH command succeeded."""
        conf = self.screens.get(screen_name, {})
        friendly = conf.get('friendly', screen_name)
        value = "0" if sleep else "255"
        action_word = "sleep" if sleep else "wake"

        cmd = f"ssh {conf['username']}@{conf['host']} \"echo {value} > {conf['brightness_path']}\""

        try:
            result = subprocess.run(cmd, shell=True, timeout=5, capture_output=True, text=True)

            if result.returncode == 0:
                logger.debug(f"🖥️ {action_word.capitalize()} command succeeded for {friendly}")
                self.screen_states[screen_name] = not sleep
                
                self.socketio.emit('screen_update', {
                    'name': screen_name,
                    'on': not sleep,
                    'online': True,
                    'config': conf
                })
                return True

            else:
                stderr = (result.stderr or "").strip()
                if any(x in stderr for x in ["No route to host", "Connection refused", "Host is down"]):
                    self.screen_states[screen_name] = not sleep
                    
                    self.socketio.emit('screen_update', {
                        'name': screen_name,
                        'on': not sleep,
                        'online': False,
                        'config': conf
                    })
                    return False  # unreachable, but not a hard failure
                else:
                    logger.warning(f"🖥️ Failed to {action_word} {friendly} (code {result.returncode}) - {stderr}")
                    return False

        except subprocess.TimeoutExpired:
            logger.warning(f"🖥️ Timeout {action_word}ing screen {friendly}")
            self.socketio.emit('screen_update', {
                'name': screen_name,
                'on': not sleep,
                'online': False,
                'config': conf
            })
            return False

        except Exception as e:
            logger.warning(f"🖥️ SSH error {action_word}ing screen {friendly}: {e}")
            self.socketio.emit('screen_update', {
                'name': screen_name,
                'on': not sleep,
                'online': False,
                'config': conf
            })
            return False
            
    def test_screen_connectivity(self, screen_name: str, timeout: float = 3.0) -> dict:
        """Test connectivity + actual passwordless SSH."""
        conf = self.screens.get(screen_name)
        if not conf or not conf.get('host'):
            return {'online': False, 'ssh_passwordless': False, 'error': 'No config'}

        host = conf['host']
        username = conf['username']
        port = 22

        result = {
            'online': False,
            'latency': None,
            'ssh_passwordless': False,
            'last_checked': datetime.now().isoformat()
        }

        start = time.time()

        # 1. Quick port check
        try:
            with socket.create_connection((host, port), timeout=timeout):
                result['latency'] = round((time.time() - start) * 1000, 1)
                result['online'] = True
        except:
            pass

        # 2. Test passwordless SSH (BatchMode prevents password prompt)
        if result['online']:
            try:
                cmd = f"ssh -o BatchMode=yes -o ConnectTimeout={int(timeout)} -o StrictHostKeyChecking=no {username}@{host} 'echo SSH_OK 2>/dev/null'"
                proc = subprocess.run(cmd, shell=True, timeout=timeout + 2, capture_output=True, text=True)
                
                result['ssh_passwordless'] = proc.returncode == 0 and 'SSH_OK' in proc.stdout
            except subprocess.TimeoutExpired:
                result['ssh_passwordless'] = False
            except Exception:
                result['ssh_passwordless'] = False

        return result

    def _was_unreachable(self, screen_name: str) -> bool:
        """Optional helper if you want extra checks later."""
        return True