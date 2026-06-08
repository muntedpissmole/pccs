from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("pccs")


class ReedInput:
    """Poll GPIO reeds, debounce at input boundary, publish stable state to WorldStore."""

    def __init__(
        self,
        gpio_manager,
        reed_names: List[str],
        debounce_ms: int,
        on_update: Callable[[Dict[str, bool], List[str]], None],
        poll_interval_s: float = 0.2,
    ):
        self._gpio = gpio_manager
        self._reed_names = reed_names
        self._debounce_ms = debounce_ms
        self._on_update = on_update
        self._poll_interval = poll_interval_s
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_change: Dict[str, float] = {}
        self._stable: Dict[str, bool] = {
            n: gpio_manager.reed_states.get(n, True) for n in reed_names
        }

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ReedInput")
        self._thread.start()
        logger.debug(f"ReedInput started ({len(self._reed_names)} reeds)")

    def stop(self):
        self._running = False

    def resync(self) -> List[str]:
        """Force hardware resample; return reeds whose stable state changed."""
        changed = []
        for name in self._reed_names:
            button = self._gpio.reeds.get(name)
            if button is None:
                continue
            current = bool(button.is_pressed)
            self._gpio.reed_states[name] = current
            if self._stable.get(name) != current:
                self._stable[name] = current
                changed.append(name)
        if changed:
            self._on_update(dict(self._stable), changed)
        return changed

    def _loop(self):
        while self._running:
            try:
                pending: Dict[str, bool] = {}
                for name in self._reed_names:
                    button = self._gpio.reeds.get(name)
                    if button is None:
                        continue
                    current = bool(button.is_pressed)
                    self._gpio.reed_states[name] = current
                    if self._stable.get(name) != current:
                        now = time.time()
                        last = self._last_change.get(name, 0)
                        if (now - last) * 1000 >= self._debounce_ms:
                            pending[name] = current
                            self._last_change[name] = now
                if pending:
                    closed_transitions = [n for n, v in pending.items() if v]
                    for name, val in pending.items():
                        self._stable[name] = val
                        action = "CLOSED" if val else "OPEN"
                        logger.info(f"🚪 Reed {name} → {action}")
                    self._on_update(dict(self._stable), closed_transitions)
            except Exception as e:
                logger.debug(f"ReedInput loop error: {e}")
            time.sleep(self._poll_interval)