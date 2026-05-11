# modules/scenes.py
import logging
from typing import Dict, Any

logger = logging.getLogger("pccs")

VALID_PHASES = {"day", "evening", "night"}


def get_all_scenes(config) -> Dict[str, dict]:
    """Dynamically load all scenes from pccs.conf"""
    scenes: Dict[str, dict] = {}

    for section in config.sections():
        if not section.startswith("scenes."):
            continue

        scene_key = section[7:].strip().lower()

        scene = {
            "name": config.get(section, "name", fallback=scene_key.title()),
            "icon": config.get(section, "icon", fallback="fa-lightbulb"),
            "order": config.getint(section, "order", fallback=999),
            "description": config.get(section, "description", fallback=""),
            "all_off": config.getboolean(section, "all_off", fallback=False),
            "evening_levels": config.getboolean(section, "evening_levels", fallback=False),
            "night_levels": config.getboolean(section, "night_levels", fallback=False),
            "day_levels": config.getboolean(section, "day_levels", fallback=False),
            "lights": {}
        }

        for key, value in config.items(section):
            key = key.strip().lower()

            if key in {"name", "icon", "order", "description", "all_off",
                       "evening_levels", "night_levels", "day_levels"}:
                continue

            if not value or value.strip() == "":
                continue

            value = value.strip()

            # === NEW: Phase reference with optional colour override ===
            # Supports: night, red   /   evening,white   /   night
            lower_val = value.lower()
            if "," in value:
                part1, part2 = [x.strip() for x in value.split(",", 1)]
                if part1.lower() in VALID_PHASES:
                    scene["lights"][key] = {
                        "type": "phase",
                        "phase": part1.lower(),
                        "forced_mode": part2.lower()
                    }
                    continue

            if lower_val in VALID_PHASES:
                scene["lights"][key] = {
                    "type": "phase",
                    "phase": lower_val
                }
                continue

            # Normal fixed brightness (with optional colour)
            try:
                if "," in value:
                    brightness_str, mode = [x.strip() for x in value.split(",", 1)]
                    brightness = int(brightness_str)
                    mode = mode.lower()
                else:
                    brightness = int(value)
                    mode = "white"

                scene["lights"][key] = {
                    "type": "fixed",
                    "brightness": max(0, min(100, brightness)),
                    "mode": mode
                }
            except ValueError:
                logger.warning(f"⚠️ Invalid value in scene '{scene_key}' for light '{key}': {value}")

        scenes[scene_key] = scene

    return dict(sorted(scenes.items(), key=lambda item: item[1]["order"]))


def get_scene_config(config, scene_name: str) -> dict | None:
    scenes = get_all_scenes(config)
    return scenes.get(scene_name.lower().strip())


def activate_scene(
    main_config,
    scene_name: str,
    ramp_and_broadcast,
    set_rgb_bug_light,
    send_command,
    state: dict,
    LIGHT_MAP: dict,
    RGB_LIGHTS: set | list,
    reed_manager=None
) -> bool:
    """Activate a scene loaded from config"""
    
    scene_config = get_scene_config(main_config, scene_name)
    if not scene_config:
        logger.error(f"Unknown scene: '{scene_name}'")
        return False

    scene_display_name = scene_config["name"]
    ramp_ms = main_config.getint('lighting', 'scene_ramp_time_ms', fallback=4000)

    logger.info(f"🎬 Activating scene: {scene_display_name}")

    # ====================== ALL OFF ======================
    if scene_config.get("all_off"):
        # ... unchanged ...
        for light_name in list(state.keys()):
            if light_name.endswith("_mode"):
                continue
            if light_name not in LIGHT_MAP and light_name not in RGB_LIGHTS:
                continue

            if light_name in RGB_LIGHTS:
                set_rgb_bug_light(light_name, 0, "white")
            else:
                send_command(f"RAMP {LIGHT_MAP.get(light_name)} 0 {ramp_ms}")

            ramp_and_broadcast(light_name, 0, ramp_ms, source="scene")

        if "floodlights" in state:
            state["floodlights"] = False

        from modules.toasts import toast_manager
        if toast_manager:
            toast_manager.success("All lights turned off", title="All Off", duration=4000)
        return True

    # ====================== PHASE LEVEL SCENES (evening_levels etc.) ======================
    phase_target = None
    if scene_config.get("evening_levels"):
        phase_target = "evening"
    elif scene_config.get("night_levels"):
        phase_target = "night"
    elif scene_config.get("day_levels"):
        phase_target = "day"

    if phase_target and reed_manager:
        reed_manager.ramp_ambient_lights(phase=phase_target, source="scene")
        
        for light_name, setting in scene_config.get("lights", {}).items():
            if setting.get("type") == "phase":
                level = reed_manager.get_phase_level(light_name, setting["phase"]) if reed_manager else None
                if level is None:
                    logger.warning(f"Scene '{scene_display_name}': No {setting['phase']} level defined for '{light_name}' - skipping")
                    continue
                target = level["brightness"]
                mode = setting.get("forced_mode") or level.get("mode", "white")
            else:
                target = setting["brightness"]
                mode = setting["mode"]

            if light_name in RGB_LIGHTS:
                set_rgb_bug_light(light_name, target, mode)
                state[f"{light_name}_mode"] = mode
            elif light_name in LIGHT_MAP:
                pwm = int(target * 2.55)
                send_command(f"RAMP {LIGHT_MAP[light_name]} {pwm} {ramp_ms}")

            ramp_and_broadcast(
                light_name, target, ramp_ms,
                mode if light_name in RGB_LIGHTS else None,
                source="scene"
            )

        from modules.toasts import toast_manager
        if toast_manager:
            toast_manager.success(f"{scene_display_name} activated")
        return True

    # ====================== NORMAL / MIXED SCENE ======================
    for light_name, setting in scene_config.get("lights", {}).items():
        if setting.get("type") == "phase":
            level = reed_manager.get_phase_level(light_name, setting["phase"]) if reed_manager else None
            if level is None:
                logger.warning(f"Scene '{scene_display_name}': No {setting['phase']} level defined for light '{light_name}' - skipping")
                continue

            target = level["brightness"]
            mode = setting.get("forced_mode") or level.get("mode", "white")
        else:
            target = setting["brightness"]
            mode = setting["mode"]

        if light_name in RGB_LIGHTS:
            set_rgb_bug_light(light_name, target, mode)
            state[f"{light_name}_mode"] = mode
        elif light_name in LIGHT_MAP:
            pwm = int(target * 2.55)
            send_command(f"RAMP {LIGHT_MAP[light_name]} {pwm} {ramp_ms}")

        ramp_and_broadcast(
            light_name, target, ramp_ms,
            mode if light_name in RGB_LIGHTS else None,
            source="scene"
        )

    from modules.toasts import toast_manager
    if toast_manager:
        toast_manager.success(f"{scene_display_name} activated", duration=3500)

    return True