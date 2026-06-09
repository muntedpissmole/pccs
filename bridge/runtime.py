from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from actuators.arduino import ArduinoActuator
from actuators.relays import RelayActuator
from actuators.screens import ScreenActuator
from engine.config_compile import compile_config
from engine.policy import desired_outputs
from engine.reconcile import Reconciler
from engine.world import WorldStore
from inputs.reeds import ReedInput
from modules.arduino import ArduinoManager
from modules.gpio import GPIODeviceManager

logger = logging.getLogger("pccs")


class PCCSRuntime:
    """Central runtime: world store, policy reconcile, inputs."""

    def __init__(self, config, socketio=None, dark_mode_config=None):
        self.config = config
        self.socketio = socketio
        self.compiled = compile_config(config)
        self.dark_mode_config = dark_mode_config

        self.arduino = ArduinoManager(config)
        self.gpio = GPIODeviceManager(config)

        self.world = WorldStore(
            self.compiled.reed_names,
            self.compiled.light_names,
            self.compiled.relay_names,
        )
        self.world.set_light_to_reed_map(self.compiled.light_to_reed)

        self.arduino_actuator = ArduinoActuator(self.arduino, self.compiled)
        self.relay_actuator = RelayActuator(self.gpio, self.compiled.relay_names)
        self.screen_actuator = ScreenActuator(self.compiled.screens, self.compiled) if self.compiled.screens else None

        self.reconciler = Reconciler(
            world=self.world,
            cfg=self.compiled,
            arduino_actuator=self.arduino_actuator,
            relay_actuator=self.relay_actuator,
            screen_actuator=self.screen_actuator,
            on_state_emit=self._emit_state,
            ramp_ms_for_source=self._ramp_ms_for_source,
            on_drift=self._on_hardware_drift,
        )

        self.reed_input: Optional[ReedInput] = None
        self.phase_manager = None
        self.gps = None
        self.sensor_manager = None
        self._shutdown = threading.Event()
        self._reconcile_lock = threading.Lock()

    def _ramp_ms_for_source(self, source: str) -> int:
        return {
            "ui": self.compiled.ui_ramp_ms,
            "scene": self.compiled.scene_ramp_ms,
            "phase": self.compiled.phase_ramp_ms,
            "reed": self.compiled.reed_ramp_ms,
        }.get(source, self.compiled.reed_ramp_ms)

    def reconcile(self, ramp_source: str = "auto"):
        with self._reconcile_lock:
            self.reconciler.reconcile(ramp_source=ramp_source)

    def _emit_state(self, state: dict):
        if self.socketio:
            try:
                self.socketio.emit("state_update", state)
            except Exception:
                pass

    def _on_hardware_drift(self, drifts: list):
        from modules.toasts import toast_manager
        if not toast_manager or not drifts:
            return
        if len(drifts) == 1:
            d = drifts[0]
            key = d.get("light") or d.get("relay") or "output"
            toast_manager.warning(
                d.get("detail", "hardware mismatch"),
                title=f"Drift: {key}",
                duration=8000,
            )
        else:
            toast_manager.warning(
                f"{len(drifts)} outputs differ from desired state",
                title="Hardware drift",
                duration=8000,
            )

    def get_explain_json(self) -> dict:
        return self.reconciler.explain_snapshot()

    def effective_reed_states(self) -> dict:
        """Authoritative reed map for the main UI (forces override hardware)."""
        snap = self.world.snapshot()
        effective = dict(snap.reeds)
        for name, closed in snap.reed_forces.items():
            effective[name] = closed
        return effective

    def _emit_reeds(self):
        if not self.socketio:
            return
        self.socketio.emit("reed_update", {"states": self.effective_reed_states()})
        self.socketio.emit("reed_diag_update", self.get_reed_diag_json())

    def on_reeds_updated(self, reeds: dict, closed_transitions: list):
        self.world.update_reeds(reeds, transition_closed=closed_transitions)
        self._emit_reeds()
        self.reconcile(ramp_source="reed")

    def on_phase_change(self, phase: str, forced: Optional[str], invalidate: bool):
        self.world.set_phase(phase, forced, invalidate=invalidate)
        self.reconcile(ramp_source="phase")

    def set_light_intent(self, name: str, brightness: int, mode: Optional[str] = None):
        self.world.set_light_intent(name, brightness, mode, expires="until_reed_close")
        self.reconcile(ramp_source="ui")

    def set_relay_intent(self, name: str, on: bool):
        self.world.set_relay_intent(name, on)
        self.reconcile(ramp_source="ui")

    def set_scene(self, scene_key: str):
        scene = self.compiled.scenes.get(scene_key, {})
        if not scene:
            logger.warning(f"Unknown scene: {scene_key}")
            return

        if scene.get("all_off"):
            self.world.clear_all_light_intents()
            for light in self.compiled.light_names:
                self.world.set_light_intent(light, 0, expires="until_phase_change")
            self.world.clear_active_scene()
        else:
            self.world.set_active_scene(scene_key)
            snap = self.world.snapshot()
            out = desired_outputs(snap, self.compiled)
            self.world.clear_active_scene()
            for light, (brightness, mode) in out.lights.items():
                source = out.light_sources.get(light, "")
                if source.startswith("scene"):
                    self.world.set_light_intent(
                        light, brightness, mode, expires="until_phase_change"
                    )

        self.reconcile(ramp_source="scene")

        from modules.toasts import toast_manager
        if toast_manager and scene.get("name"):
            title = "All Off" if scene.get("all_off") else None
            toast_manager.success(
                f"{scene['name']} activated" if not scene.get("all_off") else "All lights turned off",
                title=title or scene["name"],
                duration=4000 if scene.get("all_off") else 3500,
            )

    def force_reed(self, name: str, closed: Optional[bool]):
        if name == "all" and closed is None:
            self.world.clear_all_reed_forces()
        elif closed is None:
            self.world.set_reed_force(name, None)
        else:
            self.world.set_reed_force(name, closed)
        self._emit_reeds()
        self.reconcile(ramp_source="reed")

    def force_phase(self, phase: Optional[str]):
        if not self.phase_manager:
            return
        if phase is None:
            self.phase_manager.clear_force()
        else:
            self.phase_manager.force_phase(phase)
        pm = self.phase_manager
        self.world.set_phase(pm.get_phase(), pm.forced_phase, invalidate=True)
        self.reconcile(ramp_source="phase")

    def get_ui_state(self) -> dict:
        return self.reconciler.build_ui_state()

    def get_reed_diag_json(self) -> dict:
        """Raw hardware + force overrides — diagnostics only."""
        snap = self.world.snapshot()
        return {"states": dict(snap.reeds), "forced": dict(snap.reed_forces)}

    def start_hardware(self):
        """Init serial/GPIO and load reed state. No reconcile yet — phase comes first."""
        self.arduino.init_serial()
        self.gpio.init_devices()

        initial_reeds = {n: self.gpio.reed_states.get(n, True) for n in self.compiled.reed_names}
        self.world.update_reeds(initial_reeds)
        self.reconciler.read_hardware()

    def bootstrap_phase(self):
        """Calculate real phase and write to world before any light automation runs."""
        pm = self.phase_manager
        if not pm:
            logger.warning("🌗 Phase manager not attached — automation deferred")
            return
        use_fallback = not pm._has_valid_gps()
        phase = pm.bootstrap_initial_phase(use_fallback=use_fallback)
        self.world.set_phase(phase, pm.forced_phase, invalidate=False)
        logger.info(f"🌗 Automation unlocked for phase: {phase}")

    def finish_startup(self):
        """Start reed polling and run the first reconcile (phase must already be set)."""
        self.reed_input = ReedInput(
            gpio_manager=self.gpio,
            reed_names=self.compiled.reed_names,
            debounce_ms=self.compiled.reed_debounce_ms,
            on_update=self.on_reeds_updated,
        )
        self.reed_input.start()
        self.reconcile(ramp_source="startup")

    def start_background_threads(self):
        threading.Thread(target=self._sync_loop, daemon=True, name="HardwareSync").start()
        threading.Thread(target=self._reconcile_loop, daemon=True, name="SafetyReconcile").start()

    def _sync_loop(self):
        while not self._shutdown.is_set():
            time.sleep(self.compiled.sync_interval_s)
            try:
                if self.arduino.is_connected():
                    self.reconciler.read_hardware()
                    self.reconciler.report_hardware_drift()
                    self._emit_state(self.get_ui_state())
            except Exception as e:
                logger.debug(f"Hardware sync: {e}")

    def _reconcile_loop(self):
        while not self._shutdown.is_set():
            time.sleep(self.compiled.reconcile_interval_s)
            try:
                self.reconcile(ramp_source="auto")
            except Exception as e:
                logger.debug(f"Safety reconcile: {e}")

    def stop(self):
        self._shutdown.set()
        if self.reed_input:
            self.reed_input.stop()
        if self.phase_manager:
            self.phase_manager.stop()
        if self.sensor_manager:
            self.sensor_manager.stop()
        self.gpio.cleanup()
        self.arduino.cleanup()

    def get_frontend_config(self):
        return self.arduino.get_frontend_config()