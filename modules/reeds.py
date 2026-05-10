# modules/reeds.py
import threading
import logging
import time
from typing import Callable, Dict, Optional, Tuple, List, DefaultDict
from collections import defaultdict

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

        self.on_reed_change: Dict[str, Callable] = {}

        # Force states
        self.forced_states: Dict[str, dict] = {}
        self.force_lock = threading.Lock()
        
        self.last_ambient_update = 0
        self.last_broadcast = 0

        self.AMBIENT_THROTTLE_MS = self.config.getint('reed_monitor', 'ambient_throttle_ms', fallback=120)
        self.BROADCAST_THROTTLE_MS = self.config.getint('reed_monitor', 'broadcast_throttle_ms', fallback=80)

        self.REED_DEBOUNCE_MS = self.config.getint('reed_monitor', 'reed_debounce_ms', fallback=50)
        
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
                lights_str = self.config.get('ambient', 'lights', fallback='accent, awning').strip()
                self.ambient_lights = [l.strip() for l in lights_str.split(',') if l.strip()]
                self.all_closed_action = self.config.get('ambient', 'all_closed_action', fallback='off').strip().lower()
                logger.debug(f"🌟 Loaded ambient lights: {self.ambient_lights} | all_closed_action={self.all_closed_action}")
            else:
                logger.warning("⚠️ No [ambient] section found")
        except Exception as e:
            logger.warning(f"Failed to load [ambient]: {e}")

        try:
            loaded_count = 0
            for section in self.config.sections():
                if not section.startswith('reed_phases.'):
                    continue

                light_name = section.split('.', 1)[1].strip()
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
                            logger.debug(f"Loaded {phase}={self.phase_settings[light_name][phase]} for '{light_name}'")
                    except Exception:
                        continue

                if self.phase_settings[light_name]:
                    logger.debug(f"✅ Loaded reed phases for light '{light_name}': {list(self.phase_settings[light_name].keys())}")
                    loaded_count += 1

            if loaded_count == 0:
                logger.warning("⚠️ No reed_phases.* sections were loaded! Check your pccs.conf")
            else:
                ambient_set = set(self.ambient_lights)
                reed_only_count = len([name for name in self.phase_settings.keys() 
                                     if name not in ambient_set])

                logger.info(
                    f"💡 Loaded {len(self.ambient_lights)} ambient lights "
                    f"and {reed_only_count} reed-controlled lights"
                )
        except Exception as e:
            logger.error(f"Failed to load reed_phases: {e}", exc_info=True)
            
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

        self.registered = False
        self.last_change_time: Dict[str, float] = {}

        logger.info("🚪 ReedManager initialized")

    # ====================== (rest of the file unchanged) ======================

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
    def update_ambient_lights(self):
        now = time.time() * 1000
        if now - self.last_ambient_update < self.AMBIENT_THROTTLE_MS:
            return
        self.last_ambient_update = now

        if not hasattr(self, 'phase_manager') or self.phase_manager is None:
            return

        phase = self.phase_manager.get_phase().lower()
        all_closed = all(bool(self.get_effective_state(name)) for name in self.gpio.reed_states)

        if self.current_ambient_phase != phase:
            self.ambient_locked = False
            self.current_ambient_phase = phase

        if phase == "day":
            for light_name in self.ambient_lights:
                settings = self.get_light_settings(phase, light_name)
                if settings is not None:
                    b, m = settings
                    self._set_ambient_light(light_name, b, m, source="ambient")
            return

        if not all_closed:
            for light_name in self.ambient_lights:
                settings = self.get_light_settings(phase, light_name)
                if settings is not None:
                    b, m = settings
                    self._set_ambient_light(light_name, b, m, source="ambient")
        else:
            if self.all_closed_action == "off":
                for light_name in self.ambient_lights:
                    self._set_ambient_light(light_name, 0, "white", source="ambient")
            elif self.all_closed_action == "dim":
                for light_name in self.ambient_lights:
                    night_settings = self.get_light_settings("night", light_name)
                    if night_settings is not None:
                        b, m = night_settings
                        self._set_ambient_light(light_name, b, m, source="ambient")
                    else:
                        self._set_ambient_light(light_name, 0, "white", source="ambient")
            else:
                logger.warning(f"Unknown all_closed_action '{self.all_closed_action}' – treating as off")

    # ====================== CENTRAL LIGHT APPLICATION ======================
    def _apply_light_for_reed(self, reed_name: str, is_phase_change: bool = False):
        effective_closed = self.get_effective_state(reed_name)

        if reed_name in self.interlocks and not self.is_interlock_satisfied(reed_name):
            if not effective_closed:
                logger.debug(f"🔒 Interlock blocked {reed_name}")
            effective_closed = True

        if reed_name in self.on_reed_change:
            try:
                self.on_reed_change[reed_name](effective_closed, is_phase_change=is_phase_change)
            except Exception as e:
                logger.error(f"Failed to apply light for {reed_name}: {e}", exc_info=True)

    # ====================== PHASE CHANGE HANDLER ======================
    def reapply_all_open_lights(self, phase_manager):
        current_phase = phase_manager.get_phase()
        emoji = {"Day": "🌞", "Evening": "🌅", "Night": "🌙"}.get(current_phase, "🌗")

        logger.info(f"{emoji} {current_phase.title()} starts → updating light levels for open reeds")
        
        for name in list(self.gpio.reed_states.keys()):
            if self.get_effective_state(name):
                continue
            self._apply_light_for_reed(name, is_phase_change=True)
        
        self.update_ambient_lights()

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
        now = time.time()
        delta_ms = (now - self.last_change_time.get(name, 0)) * 1000
        if delta_ms < self.REED_DEBOUNCE_MS:
            return

        self.gpio.reed_states[name] = closed
        self.last_change_time[name] = now

        effective_closed = self.get_effective_state(name)
        action = "CLOSED" if effective_closed else "OPEN"
        logger.info(f"🚪 Reed {name} → {action}")

        affected = self.get_affected_lights(name)
        for light_name in affected:
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
        logger.debug(f"🚪 Reed monitor fallback started - watching {len(self.gpio.reed_states)} reeds")
        last_states: Dict[str, bool] = self.gpio.reed_states.copy()

        while not self.stop_event.is_set():
            changed = False
            now = time.time()

            for name in list(self.gpio.reed_states.keys()):
                try:
                    device = self.gpio.reeds.get(name)
                    if not device:
                        continue

                    real_closed = device.is_pressed
                    effective_closed = self.get_effective_state(name)

                    if effective_closed != last_states.get(name):
                        delta_ms = (now - self.last_change_time.get(name, 0)) * 1000
                        if delta_ms > 10:
                            action = "Closed" if effective_closed else "Open"
                            logger.info(f"🚪 Reed {name} → {action}")

                        last_states[name] = effective_closed
                        self.gpio.reed_states[name] = real_closed
                        changed = True

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
        self.on_reed_change[reed_name] = callback

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
        self.update_ambient_lights()

    def get_states(self) -> Dict:
        return self.gpio.reed_states.copy()

    def get_reed_ramp_time(self) -> int:
        return self.reed_ramp_time_ms