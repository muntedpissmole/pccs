# modules/scenes.py

from typing import Dict

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
        return False

    ramp_ms = config.get("ramp_time_ms", SCENE_RAMP_TIME)

    # ====================== ALL OFF ======================
    if config.get("all_off", False):
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
        return True

    # ====================== NORMAL SCENE ======================
    for light_name, value in config["lights"].items():
        if isinstance(value, dict):
            target = max(0, min(100, int(value.get("brightness", 0))))
            mode = value.get("mode", "white")
        else:
            target = max(0, min(100, int(value)))
            mode = "white"

        if reed_manager and light_name in reed_manager.on_reed_change:
            trigger = reed_manager.on_reed_change[light_name]
            try:
                trigger(is_closed=False, desired_brightness=target, desired_mode=mode)
            except TypeError:
                trigger(False)
        else:
            # Direct apply for lights without reed triggers (accent, etc.)
            if light_name in RGB_LIGHTS:
                set_rgb_bug_light(light_name, target, mode)
                state[f"{light_name}_mode"] = mode
            elif light_name in LIGHT_MAP:
                pwm = int(target * 2.55)
                send_command(f"RAMP {LIGHT_MAP[light_name]} {pwm} {ramp_ms}")

            ramp_and_broadcast(light_name, target, ramp_ms, mode if light_name in RGB_LIGHTS else None, source="scene")

    return True