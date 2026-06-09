from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .config_compile import CompiledConfig, Level
from .world import WorldState

LightLevel = Tuple[int, str]  # brightness, mode


@dataclass(frozen=True)
class ResolvedLight:
    brightness: int
    mode: str = "white"
    source: str = "fallback"

    def clamped(self) -> "ResolvedLight":
        b = max(0, min(100, int(self.brightness)))
        m = (self.mode or "white").lower()
        return ResolvedLight(b, m, self.source)


def _phase_key(world: WorldState) -> Optional[str]:
    p = str(world.phase_forced or world.phase or "").strip().lower()
    if not p:
        return None
    return p if p in ("day", "evening", "night") else "evening"


def effective_reed_closed(world: WorldState, reed: str, cfg: CompiledConfig) -> bool:
    if reed in world.reed_forces:
        return world.reed_forces[reed]
    if world.reeds.get(reed, True):
        return True
    for required in cfg.interlocks.get(reed, []):
        if effective_reed_closed(world, required, cfg):
            return True
    return False


def any_reed_open(world: WorldState, cfg: CompiledConfig) -> bool:
    return any(not effective_reed_closed(world, r, cfg) for r in cfg.reed_names)


def _get_phase_level(light: str, phase: str, cfg: CompiledConfig) -> Optional[Level]:
    key = phase.strip().lower()
    if light in cfg.reed_phase_levels and key in cfg.reed_phase_levels[light]:
        return cfg.reed_phase_levels[light][key]
    if light in cfg.ambient_phase_levels and key in cfg.ambient_phase_levels[light]:
        return cfg.ambient_phase_levels[light][key]
    return None


def _scene_level(light: str, setting: dict, cfg: CompiledConfig) -> Optional[LightLevel]:
    if setting.get("type") == "phase":
        lvl = _get_phase_level(light, setting["phase"], cfg)
        if lvl is None:
            return None
        return lvl[0], setting.get("forced_mode") or lvl[1]
    return setting["brightness"], setting.get("mode", "white")


def _scene_applies(light: str, world: WorldState, cfg: CompiledConfig) -> bool:
    if light in cfg.ambient_lights:
        return any_reed_open(world, cfg)
    reed = cfg.light_to_reed.get(light)
    if reed:
        return not effective_reed_closed(world, reed, cfg)
    return True


def _automation_default(light: str, world: WorldState, cfg: CompiledConfig) -> ResolvedLight:
    phase = _phase_key(world)
    if phase is None:
        return ResolvedLight(0, "white", "phase_pending")

    if light in cfg.ambient_lights:
        if not any_reed_open(world, cfg):
            if cfg.all_closed_action == "dim":
                lvl = _get_phase_level(light, "night", cfg)
                if lvl:
                    return ResolvedLight(lvl[0], lvl[1], "automation_all_closed_dim")
            return ResolvedLight(0, "white", "automation_all_closed")
        lvl = _get_phase_level(light, phase, cfg)
        if lvl:
            return ResolvedLight(lvl[0], lvl[1], "automation_ambient")
        return ResolvedLight(0, "white", "automation_ambient")

    reed = cfg.light_to_reed.get(light)
    if reed:
        lvl = _get_phase_level(light, phase, cfg)
        if lvl:
            return ResolvedLight(lvl[0], lvl[1], "automation_reed")
        return ResolvedLight(0, "white", "automation_reed")

    return ResolvedLight(0, "white", "fallback")


def _scene_resolve(light: str, world: WorldState, cfg: CompiledConfig) -> Optional[ResolvedLight]:
    if not world.active_scene:
        return None
    scene = cfg.scenes.get(world.active_scene, {})
    if not scene:
        return None

    if scene.get("all_off"):
        return ResolvedLight(0, "white", "scene_all_off")

    phase_target = None
    if scene.get("evening_levels"):
        phase_target = "evening"
    elif scene.get("night_levels"):
        phase_target = "night"
    elif scene.get("day_levels"):
        phase_target = "day"

    if not _scene_applies(light, world, cfg):
        return None

    setting = scene.get("lights", {}).get(light)
    if setting:
        sl = _scene_level(light, setting, cfg)
        if sl:
            return ResolvedLight(sl[0], sl[1], "scene")

    if phase_target:
        lvl = _get_phase_level(light, phase_target, cfg)
        if lvl:
            return ResolvedLight(lvl[0], lvl[1], f"scene_{phase_target}")

    return None


def _safety_clamp(light: str, resolved: ResolvedLight, world: WorldState, cfg: CompiledConfig) -> ResolvedLight:
    if light == "rooftop_tent" and resolved.brightness > 0:
        reed = cfg.light_to_reed.get("rooftop_tent", "rooftop_tent")
        if effective_reed_closed(world, reed, cfg):
            return ResolvedLight(0, "white", "safety_rooftop")
    return resolved


def resolve_light(light: str, world: WorldState, cfg: CompiledConfig) -> ResolvedLight:
    """Explicit precedence stack (highest wins first).

    1. Reed closed — reed-linked lights off (includes operator force via effective_reed_closed)
    2. User intent — manual UI levels while context is valid
    3. Active scene — one-shot scene activation levels
    4. Automation — ambient / reed phase tables
    5. Fallback — off
    6. Safety clamp — rooftop tent cannot be on when reed closed (hard guard)
    """
    reed = cfg.light_to_reed.get(light)

    # 1. Reed closed
    if reed and effective_reed_closed(world, reed, cfg):
        return ResolvedLight(0, "white", "reed_closed")

    # 2. User intent
    intent = world.light_intents.get(light)
    if intent is not None:
        return ResolvedLight(intent.brightness, intent.mode or "white", "user_intent").clamped()

    # 3. Scene
    scene_result = _scene_resolve(light, world, cfg)
    if scene_result is not None:
        return _safety_clamp(light, scene_result.clamped(), world, cfg)

    # 4. Automation
    auto = _automation_default(light, world, cfg)

    # 5–6. Fallback + safety
    return _safety_clamp(light, auto.clamped(), world, cfg)


def resolve_screen(linked_reed: str, world: WorldState, cfg: CompiledConfig) -> bool:
    return not effective_reed_closed(world, linked_reed, cfg)