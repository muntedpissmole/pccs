from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .intent import IntentExpiry, LightIntent, RelayIntent


@dataclass
class WorldState:
    reeds: Dict[str, bool] = field(default_factory=dict)
    reed_forces: Dict[str, bool] = field(default_factory=dict)
    phase: str = "Evening"
    phase_forced: Optional[str] = None
    light_intents: Dict[str, LightIntent] = field(default_factory=dict)
    relay_intents: Dict[str, RelayIntent] = field(default_factory=dict)
    active_scene: Optional[str] = None
    observed_lights: Dict[str, int] = field(default_factory=dict)
    observed_light_modes: Dict[str, str] = field(default_factory=dict)
    observed_relays: Dict[str, bool] = field(default_factory=dict)
    observed_screens: Dict[str, bool] = field(default_factory=dict)
    last_reed_raw: Dict[str, bool] = field(default_factory=dict)


class WorldStore:
    """Thread-safe canonical world model. Inputs write; policy reads."""

    def __init__(self, reed_names: List[str], light_names: List[str], relay_names: List[str]):
        self._lock = threading.RLock()
        self._state = WorldState(
            reeds={n: True for n in reed_names},
            last_reed_raw={n: True for n in reed_names},
            observed_lights={n: 0 for n in light_names},
            observed_relays={n: False for n in relay_names},
        )
        self._listeners: List[Callable[[], None]] = []
        self._light_to_reed: Dict[str, str] = {}

    def set_light_to_reed_map(self, mapping: Dict[str, str]):
        self._light_to_reed = dict(mapping)

    def on_change(self, callback: Callable[[], None]):
        self._listeners.append(callback)

    def _notify(self):
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                pass

    def snapshot(self) -> WorldState:
        with self._lock:
            import copy
            return copy.deepcopy(self._state)

    def update_reeds(self, reeds: Dict[str, bool], *, transition_closed: Optional[List[str]] = None):
        """Update reed raw state. Invalidate intents for reeds that transitioned closed."""
        with self._lock:
            transition_closed = transition_closed or []
            self._state.reeds = dict(reeds)
            if transition_closed:
                self._invalidate_intents_for_reed_close(transition_closed)
            self._notify()

    def set_reed_force(self, reed: str, closed: Optional[bool]):
        with self._lock:
            if closed is None:
                self._state.reed_forces.pop(reed, None)
            else:
                self._state.reed_forces[reed] = closed
            self._notify()

    def clear_all_reed_forces(self):
        with self._lock:
            self._state.reed_forces.clear()
            self._notify()

    def set_phase(self, phase: str, forced: Optional[str] = None, *, invalidate: bool = False):
        with self._lock:
            self._state.phase = phase
            self._state.phase_forced = forced
            if invalidate:
                self._invalidate_intents_for_phase_change()
            self._notify()

    def set_light_intent(
        self,
        light: str,
        brightness: int,
        mode: Optional[str] = None,
        expires: IntentExpiry = "until_reed_close",
    ):
        with self._lock:
            self._state.light_intents[light] = LightIntent(
                brightness=brightness, mode=mode, expires=expires, set_at=time.time()
            )
            self._notify()

    def clear_light_intent(self, light: str):
        with self._lock:
            self._state.light_intents.pop(light, None)

    def clear_all_light_intents(self):
        with self._lock:
            self._state.light_intents.clear()

    def clear_active_scene(self):
        with self._lock:
            self._state.active_scene = None

    def set_relay_intent(self, relay: str, on: bool, expires: IntentExpiry = "manual"):
        with self._lock:
            self._state.relay_intents[relay] = RelayIntent(on=on, expires=expires, set_at=time.time())
            self._notify()

    def set_active_scene(self, scene: Optional[str]):
        with self._lock:
            self._state.active_scene = scene
            if scene:
                for light in list(self._state.light_intents.keys()):
                    intent = self._state.light_intents[light]
                    if intent.expires == "until_scene_clear":
                        del self._state.light_intents[light]
            self._notify()

    def update_observed_lights(self, lights: Dict[str, int], modes: Optional[Dict[str, str]] = None):
        with self._lock:
            self._state.observed_lights.update(lights)
            if modes:
                self._state.observed_light_modes.update(modes)

    def update_observed_relays(self, relays: Dict[str, bool]):
        with self._lock:
            self._state.observed_relays.update(relays)

    def update_observed_screens(self, screens: Dict[str, bool]):
        with self._lock:
            self._state.observed_screens.update(screens)

    def _invalidate_intents_for_reed_close(self, closed_reeds: List[str]):
        closed_set = set(closed_reeds)
        for light, intent in list(self._state.light_intents.items()):
            if intent.expires != "until_reed_close":
                continue
            reed = self._light_to_reed.get(light)
            if reed and reed in closed_set:
                del self._state.light_intents[light]
            elif not reed and intent.expires == "until_reed_close":
                pass

    def _invalidate_intents_for_phase_change(self):
        for light, intent in list(self._state.light_intents.items()):
            if intent.expires == "until_phase_change":
                del self._state.light_intents[light]