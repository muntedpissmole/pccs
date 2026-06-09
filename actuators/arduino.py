from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

from modules.arduino import ArduinoManager, brightness_to_pwm

logger = logging.getLogger("pccs")


class ArduinoActuator:
    """Thin wrapper around ArduinoManager for the reconciler."""

    def __init__(self, arduino: ArduinoManager, compiled):
        self._arduino = arduino
        self._cfg = compiled

    def set_light(
        self,
        name: str,
        brightness: int,
        mode: Optional[str],
        ramp_ms: int,
        *,
        source: str = "",
        trigger: str = "",
    ):
        from engine.explain import format_light_command

        if name in self._cfg.rgb_lights:
            self._arduino.set_rgb_bug_light(name, brightness, mode or "white", ramp_ms)
        elif name in self._cfg.pwm_lights:
            pin = self._cfg.pwm_lights[name]
            pwm = brightness_to_pwm(brightness)
            self._arduino.send_command(f"RAMP {pin} {pwm} {ramp_ms}")
        else:
            return

        logger.info(
            format_light_command(
                name, brightness, mode, source or "fallback", trigger, ramp_ms
            )
        )

    def read_lights(self) -> Tuple[Dict[str, int], Dict[str, str]]:
        self._arduino.read_all_states()
        lights: Dict[str, int] = {}
        modes: Dict[str, str] = {}
        for name in self._cfg.light_names:
            if name in self._arduino.state:
                lights[name] = self._arduino.state[name]
            elif name in self._cfg.pwm_lights:
                lights[name] = 0
            if name in self._cfg.rgb_lights:
                modes[name] = self._arduino.state.get(f"{name}_mode", "white")
        return lights, modes