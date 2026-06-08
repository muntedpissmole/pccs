from __future__ import annotations

import logging
import subprocess
import threading
from typing import Dict, Optional

logger = logging.getLogger("pccs")


class ScreenActuator:
    def __init__(self, screens: dict, compiled):
        self._screens = screens
        self._observed: Dict[str, bool] = {n: False for n in screens}

    def set_screen(self, name: str, awake: bool):
        threading.Thread(target=self._apply, args=(name, awake), daemon=True).start()

    def _apply(self, name: str, awake: bool):
        conf = self._screens.get(name)
        if not conf:
            return
        bpath = conf.get("brightness_path", "")
        is_blank = "blank" in bpath or "/graphics/fb" in bpath
        if awake:
            value = "0" if is_blank else "255"
        else:
            value = "1" if is_blank else "0"
        cmd = (
            f"ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no "
            f"-o PreferredAuthentications=publickey -o IdentitiesOnly=no "
            f"{conf['username']}@{conf['host']} \"echo {value} > {bpath}\""
        )
        try:
            result = subprocess.run(cmd, shell=True, timeout=8, capture_output=True, text=True)
            if result.returncode == 0:
                self._observed[name] = awake
                logger.info(f"🖥️ {'Woke' if awake else 'Slept'} screen: {conf.get('friendly', name)}")
        except Exception as e:
            logger.debug(f"Screen {name} SSH: {e}")

    def read_screens(self) -> Dict[str, bool]:
        return dict(self._observed)

    def test_connectivity(self, name: str, timeout: float = 3.0) -> dict:
        """Ported for diag REST endpoints."""
        conf = self._screens.get(name)
        if not conf:
            return {"online": False, "error": "No config"}
        import socket
        from datetime import datetime

        result = {
            "online": False,
            "latency": None,
            "ssh_passwordless": False,
            "last_checked": datetime.now().isoformat(),
            "brightness": None,
            "on": None,
        }
        host = conf["host"]
        try:
            with socket.create_connection((host, 22), timeout=timeout):
                result["online"] = True
        except Exception:
            return result

        bpath = conf.get("brightness_path")
        if bpath:
            cmd = (
                f"ssh -o BatchMode=yes -o ConnectTimeout={int(timeout)} "
                f"-o StrictHostKeyChecking=no -o PreferredAuthentications=publickey "
                f"-o IdentitiesOnly=no {conf['username']}@{host} 'cat {bpath} 2>/dev/null'"
            )
            try:
                proc = subprocess.run(cmd, shell=True, timeout=timeout + 2, capture_output=True, text=True)
                if proc.returncode == 0:
                    val = int((proc.stdout or "").strip())
                    is_blank = "blank" in bpath or "/graphics/fb" in bpath
                    result["brightness"] = val
                    result["on"] = (val == 0) if is_blank else (val > 0)
                    result["ssh_passwordless"] = True
                    self._observed[name] = result["on"]
            except Exception as e:
                result["ssh_error"] = str(e)[:200]
        return result

    def manual_toggle(self, name: str, force_on: Optional[bool] = None):
        if force_on is None:
            force_on = not self._observed.get(name, False)
        self.set_screen(name, force_on)