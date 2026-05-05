# modules/scenes.py
import logging
from typing import Dict, Any

logger = logging.getLogger("pccs")

# ====================== SCENE CONFIGURATION ======================
SCENE_RAMP_TIME = 4000

SCENES: Dict[str, dict] = {
    "bedtime": {
        "name": "Bedtime",
        "lights": {
            "kitchen_panel": {"brightness": 5, "mode": "white"},
            "kitchen_bench": 5,
            "storage_panel": 5,
            "accent": 5,
            "awning": {"brightness": 5, "mode": "white"},
            "rooftop_tent": 5,
            "ensuite": 10,
        },
    },

    "ensuite": {
        "name": "Ensuite",
        "lights": {
            "accent": 5,
            "rooftop_tent": 2,
            "ensuite": 10,
        },
    },

    "all_off": {
        "name": "All Off",
        "lights": {},
        "all_off": True
    }
}


def get_scene_config(scene_name: str) -> dict | None:
    key = scene_name.lower().strip()
    return SCENES.get(key)


def _clamp_brightness(value: Any) -> int:
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return 0


def _send_scene_toast(message: str, toast_type: str = "info", title: str = None, duration: int = 4500):
    """Safe toast sender that avoids import timing issues"""
    try:
        from modules.toasts import toast_manager
        if toast_manager is None:
            return

        if toast_type == "success":
            toast_manager.success(message, title=title, duration=duration)
        elif toast_type == "error":
            toast_manager.error(message, title=title, duration=duration or 8000)
        elif toast_type == "warning":
            toast_manager.warning(message, title=title, duration=duration or 6000)
        else:
            toast_manager.send_toast(message, toast_type, title=title, duration=duration)
    except Exception as e:
        logger.warning(f"Could not send scene toast: {e}")


def activate_scene(
    scene_name: str,
    ramp_and_broadcast,
    set_rgb_bug_light,
    send_command,
    state: dict,
    LIGHT_MAP: dict,
    RGB_LIGHTS: set,
    reed_manager=None
) -> bool:
    config = get_scene_config(scene_name)
    if not config:
        error_msg = f"Unknown scene: '{scene_name}'"
        logger.error(error_msg)
        _send_scene_toast(error_msg, "error", "Scene Error")
        return False

    scene_display_name = config.get("name", scene_name.title())

    try:
        ramp_ms = config.get("ramp_time_ms", SCENE_RAMP_TIME)

        if config.get("all_off", False):
            logger.info(f"Activating 'All Off' scene")

            for light_name in list(state.keys()):
                if light_name in ["floodlights", "kitchen_panel_mode", "awning_mode"]:
                    continue
                if light_name not in LIGHT_MAP and light_name not in RGB_LIGHTS:
                    continue

                if light_name in RGB_LIGHTS:
                    set_rgb_bug_light(light_name, 0, "white")
                else:
                    send_command(f"RAMP {LIGHT_MAP[light_name]} 0 {ramp_ms}")

                ramp_and_broadcast(light_name, 0, ramp_ms, source="scene")

            if "floodlights" in state:
                state["floodlights"] = False

            _send_scene_toast("All lights turning off", "success", "Scene Activation Successful", duration=4000)
            logger.info("All Off scene applied successfully")
            return True

        logger.info(f"Activating scene '{scene_display_name}'")

        for light_name, value in config["lights"].items():
            if isinstance(value, dict):
                target = _clamp_brightness(value.get("brightness", 0))
                mode = value.get("mode", "white")
            else:
                target = _clamp_brightness(value)
                mode = "white"

            if reed_manager and light_name in reed_manager.on_reed_change:
                trigger = reed_manager.on_reed_change[light_name]
                try:
                    trigger(is_closed=False, desired_brightness=target, desired_mode=mode)
                except TypeError:
                    trigger(False)
            else:
                # Direct control
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

        # Success toast
        _send_scene_toast(
            f"{scene_display_name} scene",
            "success",
            "Scene Activation Successful",
            duration=4500
        )

        logger.info(f"Scene '{scene_display_name}' applied successfully")
        return True

    except Exception as e:
        error_msg = f"Failed to apply scene '{scene_display_name}'"
        logger.exception(error_msg)
        _send_scene_toast(error_msg, "error", "Scene Error", duration=8000)
        return False