from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("pccs")

VALID_PHASES = ("day", "evening", "night")
Level = Tuple[int, str]  # brightness, mode


def _parse_level(val: str, default_mode: str = "white") -> Optional[Level]:
    if not val or not str(val).strip():
        return None
    val = str(val).strip()
    if "," in val:
        b_str, mode = [x.strip() for x in val.split(",", 1)]
        return int(b_str), mode.lower()
    return int(val), default_mode


@dataclass
class CompiledConfig:
    light_names: List[str] = field(default_factory=list)
    pwm_lights: Dict[str, int] = field(default_factory=dict)
    rgb_lights: Dict[str, dict] = field(default_factory=dict)
    relay_names: List[str] = field(default_factory=list)

    reed_names: List[str] = field(default_factory=list)
    reed_to_lights: Dict[str, List[str]] = field(default_factory=dict)
    light_to_reed: Dict[str, str] = field(default_factory=dict)
    interlocks: Dict[str, List[str]] = field(default_factory=dict)

    ambient_lights: List[str] = field(default_factory=list)
    all_closed_action: str = "off"
    reed_phase_levels: Dict[str, Dict[str, Level]] = field(default_factory=dict)
    ambient_phase_levels: Dict[str, Dict[str, Level]] = field(default_factory=dict)

    scenes: Dict[str, dict] = field(default_factory=dict)
    screens: Dict[str, dict] = field(default_factory=dict)

    ui_ramp_ms: int = 1000
    reed_ramp_ms: int = 2000
    scene_ramp_ms: int = 4000
    phase_ramp_ms: int = 4000
    reed_debounce_ms: int = 50
    reconcile_interval_s: int = 30
    sync_interval_s: int = 45


def compile_config(cfg) -> CompiledConfig:
    """Compile pccs.conf into typed lookup tables for the policy engine."""
    out = CompiledConfig()

    out.ui_ramp_ms = cfg.getint("lighting", "ui_ramp_time_ms", fallback=1000)
    out.reed_ramp_ms = cfg.getint("lighting", "reed_ramp_time_ms", fallback=2000)
    out.scene_ramp_ms = cfg.getint("lighting", "scene_ramp_time_ms", fallback=4000)
    out.phase_ramp_ms = cfg.getint("lighting", "phase_ramp_time_ms", fallback=4000)
    out.reed_debounce_ms = cfg.getint("reed_monitor", "reed_debounce_ms", fallback=50)
    out.sync_interval_s = cfg.getint("background_sync", "sync_interval", fallback=45)
    out.reconcile_interval_s = 30

    if cfg.has_section("ambient"):
        out.all_closed_action = cfg.get("ambient", "all_closed_action", fallback="off").strip().lower()

    # Lights
    if cfg.has_section("lights"):
        for name, line in cfg.items("lights"):
            parts = [p.strip() for p in str(line).split("|")]
            if len(parts) < 4:
                continue
            out.light_names.append(name)
            ltype = parts[1].lower()
            if ltype == "pwm":
                try:
                    out.pwm_lights[name] = int(parts[2])
                except ValueError:
                    logger.warning(f"Bad PWM pin for {name}")
            elif ltype == "rgb_bug" and len(parts) >= 5:
                out.rgb_lights[name] = {
                    "white": int(parts[2]),
                    "red": int(parts[3]),
                    "green": int(parts[4]),
                }

    # Relays
    if cfg.has_section("gpio"):
        for name, line in cfg.items("gpio"):
            if str(line).strip().startswith("#"):
                continue
            parts = [p.strip() for p in str(line).split("|")]
            if len(parts) >= 2:
                out.relay_names.append(name)

    # Reeds
    if cfg.has_section("reeds"):
        for name, line in cfg.items("reeds"):
            parts = [p.strip() for p in str(line).split("|")]
            if len(parts) < 2:
                continue
            out.reed_names.append(name)
            controls = [name]
            if len(parts) > 6:
                last = parts[6].strip()
                if last.startswith("controls:"):
                    cl = last[9:].strip()
                    if cl:
                        controls = [x.strip() for x in cl.split(",") if x.strip()]
                elif last:
                    controls = [last]
            out.reed_to_lights[name] = controls
            for light in controls:
                out.light_to_reed[light] = name

    # Interlocks
    if cfg.has_section("reeds.interlocks"):
        for reed, required in cfg.items("reeds.interlocks"):
            out.interlocks[reed.strip()] = [
                x.strip() for x in str(required).split(",") if x.strip()
            ]

    # Reed phase levels (preferred)
    for section in cfg.sections():
        if not section.startswith("reed_phases."):
            continue
        light = section.split(".", 1)[1].strip()
        levels: Dict[str, Level] = {}
        for phase in VALID_PHASES:
            val = cfg.get(section, phase, fallback=None)
            parsed = _parse_level(val) if val else None
            if parsed:
                levels[phase] = parsed
        if levels:
            out.reed_phase_levels[light] = levels

    # Ambient sections
    for section in cfg.sections():
        if not section.startswith("ambient."):
            continue
        light = section.split(".", 1)[1].strip()
        if light not in out.ambient_lights:
            out.ambient_lights.append(light)
        levels: Dict[str, Level] = {}
        for phase in VALID_PHASES:
            val = cfg.get(section, phase, fallback=None)
            parsed = _parse_level(val) if val else None
            if parsed:
                levels[phase] = parsed
            elif phase == "day":
                levels["day"] = (0, "white")
        if light not in out.reed_phase_levels:
            out.ambient_phase_levels[light] = levels
        else:
            for phase, lvl in levels.items():
                out.reed_phase_levels[light].setdefault(phase, lvl)

    # Scenes
    out.scenes = _compile_scenes(cfg)

    # Screens
    if cfg.has_section("screens"):
        for name, line in cfg.items("screens"):
            parts = [p.strip() for p in str(line).split("|")]
            if len(parts) < 5:
                continue
            out.screens[name] = {
                "friendly": parts[0],
                "linked_reed": parts[1],
                "host": parts[2],
                "username": parts[3],
                "brightness_path": parts[4],
                "icon": parts[5] if len(parts) > 5 else "fa-display",
            }

    from .config_validate import validate_compiled_config

    warnings = validate_compiled_config(cfg, out)
    for w in warnings:
        logger.warning(f"Config: {w}")

    return out


def _compile_scenes(cfg) -> Dict[str, dict]:
    scenes: Dict[str, dict] = {}
    for section in cfg.sections():
        if not section.startswith("scenes."):
            continue
        key = section[7:].strip().lower()
        scene = {
            "name": cfg.get(section, "name", fallback=key.title()),
            "icon": cfg.get(section, "icon", fallback="fa-lightbulb"),
            "order": cfg.getint(section, "order", fallback=999),
            "description": cfg.get(section, "description", fallback=""),
            "all_off": cfg.getboolean(section, "all_off", fallback=False),
            "evening_levels": cfg.getboolean(section, "evening_levels", fallback=False),
            "night_levels": cfg.getboolean(section, "night_levels", fallback=False),
            "day_levels": cfg.getboolean(section, "day_levels", fallback=False),
            "lights": {},
        }
        skip = {"name", "icon", "order", "description", "all_off",
                "evening_levels", "night_levels", "day_levels"}
        for k, value in cfg.items(section):
            k = k.strip().lower()
            if k in skip or not value or not str(value).strip():
                continue
            value = str(value).strip()
            lower = value.lower()
            if "," in value:
                p1, p2 = [x.strip() for x in value.split(",", 1)]
                if p1.lower() in VALID_PHASES:
                    scene["lights"][k] = {"type": "phase", "phase": p1.lower(), "forced_mode": p2.lower()}
                    continue
            if lower in VALID_PHASES:
                scene["lights"][k] = {"type": "phase", "phase": lower}
                continue
            try:
                if "," in value:
                    b, mode = [x.strip() for x in value.split(",", 1)]
                    scene["lights"][k] = {"type": "fixed", "brightness": int(b), "mode": mode.lower()}
                else:
                    scene["lights"][k] = {"type": "fixed", "brightness": int(value), "mode": "white"}
            except ValueError:
                logger.warning(f"Invalid scene value {key}.{k}={value}")
        scenes[key] = scene
    return scenes