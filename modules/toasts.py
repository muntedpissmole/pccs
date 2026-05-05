# modules/toasts.py
import time
import logging
from typing import Optional
from flask_socketio import SocketIO

logger = logging.getLogger("pccs")


class ToastManager:

    def __init__(self, socketio: SocketIO):
        self.socketio = socketio

    def send_toast(
        self,
        message: str,
        toast_type: str = "info",           # success | info | warning | error
        duration: int = 5000,               # ms before auto-dismiss
        title: Optional[str] = None,
        persistent: bool = False,           # if True, doesn't auto-dismiss
        broadcast: bool = True
    ):

        if toast_type not in ("success", "info", "warning", "error"):
            toast_type = "info"

        toast_data = {
            "id": f"toast_{int(time.time() * 1000)}",
            "message": message,
            "type": toast_type,
            "duration": 0 if persistent else duration,
            "title": title,
            "timestamp": time.time(),
            "persistent": persistent
        }

        if broadcast:
            self.socketio.emit("toast", toast_data)
            logger.debug(f"📢 Toast [{toast_type}] → {message[:120]}")
        else:
            self.socketio.emit("toast", toast_data)

    def success(self, message: str, **kwargs):
        self.send_toast(message, "success", **kwargs)

    def info(self, message: str, **kwargs):
        self.send_toast(message, "info", **kwargs)

    def warning(self, message: str, **kwargs):
        self.send_toast(message, "warning", **kwargs)

    def error(self, message: str, **kwargs):
        self.send_toast(message, "error", duration=8000, **kwargs)


toast_manager: Optional[ToastManager] = None