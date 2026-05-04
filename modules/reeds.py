# modules/reeds.py
import threading
import logging
import time
from typing import Callable, Dict, Optional, Tuple

from flask_socketio import SocketIO
from gpiozero import Button

from .gpio import GPIODeviceManager

# ====================== SCENE RAMP TIME ======================
try:
    from .scenes import SCENE_RAMP_TIME
except ImportError:
    SCENE_RAMP_TIME = 4000

logger = logging.getLogger("pccs")


class ReedManager:
    def __init__(
        self,
        gpio_manager: GPIODeviceManager,
        socketio: SocketIO,
        rgb_lights: set,
        light_map: dict,
        set_rgb_bug_light: Callable,
        send_command: Callable,
        ramp_and_broadcast: Callable,
    ):
        self.gpio = gpio_manager
        self.socketio = socketio

        # Injected dependencies (clean architecture)
        self.RGB_LIGHTS = rgb_lights
        self.LIGHT_MAP = light_map
        self.set_rgb_bug_light = set_rgb_bug_light
        self.send_command = send_command
        self.ramp_and_broadcast = ramp_and_broadcast

        self.stop_event = threading.Event()
        self.monitor_thread: threading.Thread | None = None
        self.interval: float = 0.25

        self.reed_ramp_time_ms = 2000

        self.ambient_locked = False
        self.current_ambient_phase = None

        self.on_reed_change: Dict[str, Callable] = {}

        # Force states
        self.forced_states: Dict[str, dict] = {}
        self.force_lock = threading.Lock()

        # Per-reed phase light settings
        self.phase_settings: Dict[str, Dict[str, Tuple[int, str] | int]] = {
            # RGB lights
            "kitchen_panel": {
                "day":     (100, "white"),
                "evening": (30, "white"),
                "night":   (10, "red"),
            },
            # Ambient lighting
            "awning": {
                "evening": (20, "white"),
                "night":   (10, "red"),
            },

            # White-only lights
            "kitchen_bench": {
                "day":     100,
                "evening": 80,
                "night":   10,
            },
            "storage_panel": {
                "day":     100,
                "evening": 30,
                "night":   5,
            },
            "rear_drawer": {
                "day":     0,
                "evening": 50,
                "night":   10,
            },
            "rooftop_tent": {
                "day":     0,
                "evening": 20,
                "night":   5,
            },
            # Ambient lighting
            "accent": {
                "evening": 20,
                "night":   5,
            },
        }

        self.registered = False
        self.last_change_time: Dict[str, float] = {}

        logger.info("🚪 ReedManager initialized")

    def get_light_settings(self, phase: str, reed_name: str) -> Tuple[int, str] | None:
        phase = str(phase).strip().lower()
        config = self.phase_settings.get(reed_name, {})

        if reed_name in self.RGB_LIGHTS:
            settings = config.get(phase, config.get("day", (0, "white")))
            if isinstance(settings, tuple):
                return settings
            else:
                mode = "red" if reed_name == "kitchen_panel" and phase == "night" else "white"
                return (settings, mode)
        else:
            if phase == "day" and "day" not in config:
                return None

            setting = config.get(phase, config.get("day", 0))

            if isinstance(setting, tuple):
                return setting
            else:
                return (setting, "white")
            
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

    # ====================== AMBIENT LIGHTS (accent + awning) ======================
    def update_ambient_lights(self):
        if not hasattr(self, 'phase_manager') or self.phase_manager is None:
            return

        phase = self.phase_manager.get_phase().lower()
        any_open = any(not self.get_effective_state(name) for name in self.gpio.reed_states)

        if self.current_ambient_phase != phase:
            self.ambient_locked = False
            self.current_ambient_phase = phase

        if phase in ("evening", "night"):
            if not any_open:
                self.ambient_locked = False
                brightness = 0
                mode = "white"
                apply_to = ["accent", "awning"]
            elif self.ambient_locked:
                logger.debug("🌟 Ambient locked – skipping")
                return
            else:
                self.ambient_locked = True
                apply_to = ["accent", "awning"]
        else:
            # day logic...
            if any_open:
                apply_to = ["accent", "awning"]
            else:
                brightness = 0
                mode = "white"
                apply_to = ["accent", "awning"]

        for light_name in ("accent", "awning"):
            if light_name not in apply_to:
                continue

            settings = self.get_light_settings(phase, light_name)
            if settings is None:
                continue

            brightness, mode = settings
            self._set_ambient_light(light_name, brightness, mode, source="ambient")

    # ====================== PHASE CHANGE HANDLER ======================
    def reapply_all_open_lights(self, phase_manager):
        current_phase = phase_manager.get_phase()
        logger.info(f"🌗 Phase changed to {current_phase.title()} → reapplying lights to open reeds")

        for name in list(self.gpio.reed_states.keys()):
            if not self.get_effective_state(name):  # Door is OPEN
                if name in self.on_reed_change:
                    try:
                        self.on_reed_change[name](False, is_phase_change=True)
                    except Exception as e:
                        logger.error(f"Failed to reapply {name}: {e}", exc_info=True)

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
            logger.info(f"🔧 Reed forced {reed_name} → {'Closed' if forced_closed else 'Open'}")

        self.broadcast_update()
        self.update_ambient_lights()
        return True

    def clear_force(self, reed_name: str) -> bool:
        """Clear a forced reed state. Safe version - no deadlock."""
        was_forced = False
        with self.force_lock:
            if reed_name in self.forced_states:
                timer = self.forced_states[reed_name].get('timer')
                if timer:
                    timer.cancel()
                del self.forced_states[reed_name]
                logger.info(f"🔄 Cleared force state on {reed_name}")
                was_forced = True

        if was_forced:
            self.broadcast_update()          # ← was missing!
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
        logger.info("🧹 Cleared all forced reed states")
        self.broadcast_update()
        self.update_ambient_lights()

    def get_forced_states(self) -> Dict[str, bool]:
        with self.force_lock:
            return {name: data['state'] for name, data in self.forced_states.items()}

    def is_forced(self, reed_name: str) -> bool:
        with self.force_lock:
            return reed_name in self.forced_states

    def get_effective_state(self, reed_name: str) -> Optional[bool]:
        with self.force_lock:
            if reed_name in self.forced_states:
                return self.forced_states[reed_name]['state']
        return self.gpio.reed_states.get(reed_name)

    # ====================== REED EVENT HANDLING ======================
    def register_event_handlers(self):
        if self.registered:
            return

        for name, button in self.gpio.reeds.items():
            button.when_pressed = lambda btn, n=name: self._on_reed_event(n, closed=True)
            button.when_released = lambda btn, n=name: self._on_reed_event(n, closed=False)

        self.registered = True
        logger.info(f"🚪 Registered event handlers for {len(self.gpio.reeds)} reeds")

    def _on_reed_event(self, name: str, closed: bool):
        now = time.time()
        effective_closed = self.get_effective_state(name)
        delta_ms = (now - self.last_change_time.get(name, 0)) * 1000

        if delta_ms > 10:
            action = "CLOSED" if effective_closed else "OPEN"
            logger.info(f"🚪 Reed {name} → {action} "
                       f"(gpio: {'closed' if closed else 'open'})")
            self.last_change_time[name] = now

        self.gpio.reed_states[name] = closed

        if name in self.on_reed_change:
            try:
                self.on_reed_change[name](effective_closed)
            except Exception as e:
                logger.error(f"Error in on_reed_change for {name}: {e}", exc_info=True)

        self.broadcast_update()
        self.update_ambient_lights()

    # ====================== MONITOR FALLBACK ======================
    def start_monitor(self, interval: float = 0.25):
        self.interval = interval
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="ReedMonitor"
        )
        self.monitor_thread.start()

    def _monitor_loop(self):
        logger.info(f"🚪 Reed monitor fallback started - watching {len(self.gpio.reed_states)} reeds")
        last_states: Dict[str, bool] = self.gpio.reed_states.copy()

        while not self.stop_event.is_set():
            changed = False
            now = time.time()

            for name, device in list(self.gpio.devices.items()):
                if not isinstance(device, Button):
                    continue
                try:
                    real_closed = device.is_pressed
                    effective_closed = self.get_effective_state(name)

                    if effective_closed != last_states.get(name):
                        delta_ms = (now - self.last_change_time.get(name, 0)) * 1000
                        if delta_ms > 10:
                            action = "Closed" if effective_closed else "Open"
                            logger.info(f"🚪 Reed {name} → {action}")

                            self.last_change_time[name] = now

                        last_states[name] = effective_closed
                        self.gpio.reed_states[name] = real_closed
                        changed = True

                        if name in self.on_reed_change:
                            self.on_reed_change[name](effective_closed)
                except Exception:
                    continue

            if changed:
                self.broadcast_update()
                self.update_ambient_lights()

            self.stop_event.wait(self.interval)

        logger.info("🚪 Reed monitor stopped")

    def stop(self):
        self.stop_event.set()
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=1.5)

    def register_trigger(self, reed_name: str, callback: Callable):
        self.on_reed_change[reed_name] = callback

    def broadcast_update(self):
        payload = {
            'states': self.get_states(),
            'forced': self.get_forced_states()
        }
        try:
            self.socketio.emit('reed_update', payload)
        except Exception as e:
            logger.warning(f"Failed to emit reed_update: {e}")

    def get_states(self) -> Dict:
        return self.gpio.reed_states.copy()

    def get_reed_ramp_time(self) -> int:
        return self.reed_ramp_time_ms