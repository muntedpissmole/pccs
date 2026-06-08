from __future__ import annotations

import logging
from typing import Callable, Dict, Optional, Tuple

from .config_compile import CompiledConfig
from .policy import DesiredOutputs, desired_outputs
from .world import WorldStore

logger = logging.getLogger("pccs")

CommandedLight = Tuple[int, str]


class Reconciler:
    """Apply desired state diffs to hardware actuators."""

    def __init__(
        self,
        world: WorldStore,
        cfg: CompiledConfig,
        arduino_actuator,
        relay_actuator,
        screen_actuator=None,
        on_state_emit: Optional[Callable[[dict], None]] = None,
        ramp_ms_for_source: Optional[Callable[[str], int]] = None,
    ):
        self.world = world
        self.cfg = cfg
        self.arduino = arduino_actuator
        self.relays = relay_actuator
        self.screens = screen_actuator
        self.on_state_emit = on_state_emit
        self._ramp_ms = ramp_ms_for_source or (lambda _s: cfg.reed_ramp_ms)
        self._last_desired: Optional[DesiredOutputs] = None
        self._commanded_lights: Dict[str, CommandedLight] = {}
        self._commanded_relays: Dict[str, bool] = {}
        self._commanded_screens: Dict[str, bool] = {}

    def reconcile(self, ramp_source: str = "auto"):
        world = self.world.snapshot()
        desired = desired_outputs(world, cfg=self.cfg)
        desired.ramp_source = ramp_source
        ramp_ms = self._ramp_ms(ramp_source)

        light_changes = []
        for light, (brightness, mode) in desired.lights.items():
            target_m = mode or "white"
            cmd_b, cmd_m = self._commanded_lights.get(light, (-1, ""))
            if cmd_b != brightness or (light in self.cfg.rgb_lights and cmd_m != target_m):
                self.arduino.set_light(
                    light, brightness, target_m if light in self.cfg.rgb_lights else None, ramp_ms
                )
                self._commanded_lights[light] = (brightness, target_m)
                light_changes.append(light)

        for relay, on in desired.relays.items():
            if self._commanded_relays.get(relay) != on:
                self.relays.set_relay(relay, on)
                self._commanded_relays[relay] = on

        if self.screens:
            for screen, awake in desired.screens.items():
                if self._commanded_screens.get(screen) != awake:
                    self.screens.set_screen(screen, awake)
                    self._commanded_screens[screen] = awake

        self._last_desired = desired

        if self.on_state_emit:
            self.on_state_emit(self.build_ui_state(desired))

        if light_changes:
            logger.debug(f"Reconciled lights: {light_changes} [{ramp_source}]")

    def build_ui_state(self, desired: Optional[DesiredOutputs] = None) -> dict:
        desired = desired or self._last_desired
        if not desired:
            world = self.world.snapshot()
            desired = desired_outputs(world, self.cfg)
        state = {}
        for name, (b, _) in desired.lights.items():
            state[name] = b
        for name, mode in desired.light_modes.items():
            state[f"{name}_mode"] = mode
        for name, on in desired.relays.items():
            state[name] = on
        return state

    def read_hardware(self):
        """Refresh observed state from hardware reads (not used for reconcile diffs)."""
        lights, modes = self.arduino.read_lights()
        relays = self.relays.read_relays()
        self.world.update_observed_lights(lights, modes)
        self.world.update_observed_relays(relays)