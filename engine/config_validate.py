"""Validate compiled config before the runtime starts."""

from __future__ import annotations

from typing import List, Set

from .config_compile import CompiledConfig, VALID_PHASES


class ConfigValidationError(Exception):
    """Raised when pccs.conf fails validation."""

    def __init__(self, errors: List[str], warnings: List[str] | None = None):
        self.errors = errors
        self.warnings = warnings or []
        msg = "Config validation failed:\n" + "\n".join(f"  • {e}" for e in errors)
        super().__init__(msg)


def _reed_pins(raw_cfg) -> dict:
    pins = {}
    if not raw_cfg.has_section("reeds"):
        return pins
    for name, line in raw_cfg.items("reeds"):
        parts = [p.strip() for p in str(line).split("|")]
        if len(parts) < 2:
            continue
        try:
            pin = int(parts[1])
        except ValueError:
            continue
        pins.setdefault(pin, []).append(name)
    return pins


def validate_compiled_config(raw_cfg, compiled: CompiledConfig) -> List[str]:
    """
    Validate compiled config. Returns warnings; raises ConfigValidationError on errors.
    """
    errors: List[str] = []
    warnings: List[str] = []
    lights: Set[str] = set(compiled.light_names)
    reeds: Set[str] = set(compiled.reed_names)

    # Reed controls reference real lights
    for reed, controlled in compiled.reed_to_lights.items():
        for light in controlled:
            if light not in lights:
                errors.append(
                    f"Reed '{reed}' controls unknown light '{light}'"
                )

    # Reed-linked lights need evening + night phase levels
    for reed, controlled in compiled.reed_to_lights.items():
        for light in controlled:
            levels = compiled.reed_phase_levels.get(light, {})
            for phase in ("evening", "night"):
                if phase not in levels:
                    errors.append(
                        f"Reed-linked light '{light}' missing [reed_phases.{light}] "
                        f"{phase} level"
                    )

    # Ambient lights need evening + night levels
    for light in compiled.ambient_lights:
        if light not in lights:
            errors.append(f"Ambient light '{light}' not defined in [lights]")
            continue
        levels = (
            compiled.reed_phase_levels.get(light)
            or compiled.ambient_phase_levels.get(light)
            or {}
        )
        for phase in ("evening", "night"):
            if phase not in levels:
                warnings.append(
                    f"Ambient light '{light}' has no {phase} level "
                    f"(will fall back to off)"
                )

    # Interlocks
    for controlled, required_list in compiled.interlocks.items():
        if controlled not in reeds:
            errors.append(f"Interlock controlled reed '{controlled}' is not configured")
        for req in required_list:
            if req not in reeds:
                errors.append(
                    f"Interlock for '{controlled}' references unknown reed '{req}'"
                )

    # Screens
    for screen, meta in compiled.screens.items():
        linked = meta.get("linked_reed")
        if linked and linked not in reeds:
            errors.append(
                f"Screen '{screen}' linked_reed '{linked}' is not in [reeds]"
            )

    # Scenes
    for scene_key, scene in compiled.scenes.items():
        for light in scene.get("lights", {}):
            if light not in lights:
                errors.append(
                    f"Scene '{scene_key}' references unknown light '{light}'"
                )

    # Duplicate reed GPIO pins
    for pin, names in _reed_pins(raw_cfg).items():
        if len(names) > 1:
            errors.append(
                f"Duplicate reed GPIO pin {pin}: {', '.join(names)}"
            )

    # Orphan reed_phases / ambient sections
    for light in compiled.reed_phase_levels:
        if light not in lights:
            warnings.append(f"[reed_phases.{light}] has no matching [lights] entry")
    for light in compiled.ambient_phase_levels:
        if light not in lights:
            warnings.append(f"[ambient.{light}] has no matching [lights] entry")

    if errors:
        raise ConfigValidationError(errors, warnings)

    return warnings