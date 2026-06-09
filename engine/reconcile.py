from __future__ import annotations

import logging
import time
from typing import Callable, Dict, List, Optional, Tuple

from .config_compile import CompiledConfig
from .explain import build_explain_snapshot, source_label
from .policy import DesiredOutputs, desired_outputs
from .precedence import is_scene_source
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
        on_drift: Optional[Callable[[List[dict]], None]] = None,
    ):
        self.world = world
        self.cfg = cfg
        self.arduino = arduino_actuator
        self.relays = relay_actuator
        self.screens = screen_actuator
        self.on_state_emit = on_state_emit
        self.on_drift = on_drift
        self._ramp_ms = ramp_ms_for_source or (lambda _s: cfg.reed_ramp_ms)
        self._last_desired: Optional[DesiredOutputs] = None
        self._last_ramp_source: str = "unknown"
        self._commanded_lights: Dict[str, CommandedLight] = {}
        self._commanded_relays: Dict[str, bool] = {}
        self._commanded_screens: Dict[str, bool] = {}
        self._commanded_at: Dict[str, float] = {}
        self._drift_grace_s = max(3.0, cfg.reed_ramp_ms / 1000.0 + 1.0)
        self._active_drifts: Dict[str, str] = {}

    def _preserve_lights_except(self, desired: DesiredOutputs, world, affected: set) -> None:
        """Keep untouched lights at their prior commanded or observed levels."""
        for light in self.cfg.light_names:
            if light in affected:
                continue
            if self._last_desired and light in self._last_desired.lights:
                desired.lights[light] = self._last_desired.lights[light]
                desired.light_sources[light] = self._last_desired.light_sources.get(
                    light, "fallback"
                )
                if light in self.cfg.rgb_lights and light in self._last_desired.light_modes:
                    desired.light_modes[light] = self._last_desired.light_modes[light]
            elif light in world.observed_lights:
                obs = world.observed_lights[light]
                mode = world.observed_light_modes.get(light, "white")
                desired.lights[light] = (obs, mode)
                desired.light_sources[light] = "unchanged"
                if light in self.cfg.rgb_lights:
                    desired.light_modes[light] = mode

    def reconcile(self, ramp_source: str = "auto"):
        world = self.world.snapshot()
        desired = desired_outputs(world, cfg=self.cfg)
        desired.ramp_source = ramp_source
        self._last_ramp_source = ramp_source
        ramp_ms = self._ramp_ms(ramp_source)
        now = time.time()
        scene_pass = ramp_source == "scene"
        ui_pass = ramp_source == "ui"

        for light, (brightness, mode) in desired.lights.items():
            source = desired.light_sources.get(light, "fallback")
            if scene_pass and not is_scene_source(source):
                continue
            if ui_pass and light not in world.light_intents:
                continue

            target_m = mode or "white"
            cmd_b, cmd_m = self._commanded_lights.get(light, (-1, ""))
            if cmd_b != brightness or (light in self.cfg.rgb_lights and cmd_m != target_m):
                self.arduino.set_light(
                    light,
                    brightness,
                    target_m if light in self.cfg.rgb_lights else None,
                    ramp_ms,
                    source=source,
                    trigger=ramp_source,
                )
                self._commanded_lights[light] = (brightness, target_m)
                self._commanded_at[light] = now

        for relay, on in desired.relays.items():
            if ui_pass and relay not in world.relay_intents:
                continue
            if self._commanded_relays.get(relay) != on:
                rsource = "user_intent" if relay in world.relay_intents else "hardware_default"
                self.relays.set_relay(relay, on, source=rsource, trigger=ramp_source)
                self._commanded_relays[relay] = on
                self._commanded_at[f"relay:{relay}"] = now

        if self.screens:
            for screen, awake in desired.screens.items():
                if self._commanded_screens.get(screen) != awake:
                    self.screens.set_screen(screen, awake)
                    self._commanded_screens[screen] = awake

        if scene_pass:
            scene_lights = {
                light
                for light in self.cfg.light_names
                if is_scene_source(desired.light_sources.get(light, ""))
            }
            self._preserve_lights_except(desired, world, scene_lights)
        elif ui_pass:
            self._preserve_lights_except(desired, world, set(world.light_intents.keys()))

        self._last_desired = desired

        if self.on_state_emit:
            self.on_state_emit(self.build_ui_state(desired))

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
        """Refresh observed state from hardware reads."""
        lights, modes = self.arduino.read_lights()
        relays = self.relays.read_relays()
        self.world.update_observed_lights(lights, modes)
        self.world.update_observed_relays(relays)

    def check_hardware_drift(self) -> List[dict]:
        """Compare desired vs observed hardware; return active drift items."""
        if not self._last_desired:
            return []

        world = self.world.snapshot()
        snap = build_explain_snapshot(
            world,
            self.cfg,
            self._last_desired,
            last_trigger=self._last_ramp_source,
        )
        now = time.time()
        drifts: List[dict] = []

        for item in snap.get("drifts", []):
            key = item.get("light") or item.get("relay")
            if not key:
                continue
            grace_key = f"relay:{key}" if "relay" in item else key
            commanded_at = self._commanded_at.get(grace_key, 0)
            if now - commanded_at < self._drift_grace_s:
                continue
            drifts.append(item)

        return drifts

    def report_hardware_drift(self) -> List[dict]:
        """Log and notify on drift changes. Returns current drift list."""
        drifts = self.check_hardware_drift()
        current = {
            (d.get("light") or d.get("relay")): d.get("detail", "")
            for d in drifts
        }

        cleared = [k for k in self._active_drifts if k not in current]
        for key in cleared:
            logger.info(f"✅ Drift cleared: {key}")
            del self._active_drifts[key]

        new_drifts: List[dict] = []
        for key, detail in current.items():
            if self._active_drifts.get(key) != detail:
                self._active_drifts[key] = detail
                label = source_label("fallback")
                if self._last_desired and key in self._last_desired.light_sources:
                    label = source_label(self._last_desired.light_sources[key])
                logger.warning(
                    f"⚠️ Hardware drift · {key}: {detail} (desired via {label})"
                )
                for item in drifts:
                    item_key = item.get("light") or item.get("relay")
                    if item_key == key:
                        new_drifts.append(item)
                        break

        if new_drifts and self.on_drift:
            try:
                self.on_drift(new_drifts)
            except Exception as e:
                logger.debug(f"Drift callback error: {e}")

        return drifts

    def explain_snapshot(self) -> dict:
        world = self.world.snapshot()
        desired = self._last_desired or desired_outputs(world, self.cfg)
        return build_explain_snapshot(
            world,
            self.cfg,
            desired,
            last_trigger=self._last_ramp_source,
        )