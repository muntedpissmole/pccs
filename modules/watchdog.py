# modules/watchdog.py
import threading
import time as time_module
from datetime import datetime, timedelta
import logging
import os

logger = logging.getLogger(__name__)


class WatchdogManager:
    def __init__(self, config_manager, socketio=None):
        self.config_manager = config_manager
        self.socketio = socketio
        self.feed_times = {}
        self.restart_counts = {}
        self.lock = threading.Lock()
        self.running = True
        self.watchdog_thread = None

        self.reload_config()
        logger.info("WatchdogManager initialized with config from config.json")

    def reload_config(self):
        """Load watchdog settings from config.json"""
        wd = self.config_manager.get('watchdog', {})
        self.enabled = wd.get('enabled', True)
        self.check_interval_seconds = wd.get('check_interval_seconds', 15)
        self.thread_timeout_seconds = wd.get('thread_timeout_seconds', 180)
        self.max_restarts = wd.get('max_restarts', 3)
        self.reboot_on_failure = wd.get('reboot_on_failure', False)
        self.reboot_delay_seconds = wd.get('reboot_delay_seconds', 5)
        logger.debug(f"Watchdog config loaded: timeout={self.thread_timeout_seconds}s, reboot={self.reboot_on_failure}")

    def feed(self, thread_name: str):
        """Call this regularly from each background loop"""
        if not self.enabled:
            return
        with self.lock:
            self.feed_times[thread_name] = datetime.now()
            if thread_name in self.restart_counts:
                self.restart_counts[thread_name] = 0

    def start(self):
        if not self.enabled:
            logger.info("Watchdog is disabled in config")
            return
        if self.watchdog_thread is None or not self.watchdog_thread.is_alive():
            self.watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
            self.watchdog_thread.start()
            logger.info("Watchdog monitoring started")

    def stop(self):
        self.running = False
        if self.watchdog_thread and self.watchdog_thread.is_alive():
            self.watchdog_thread.join(timeout=2)
        logger.info("Watchdog stopped")

    def _watchdog_loop(self):
        while self.running:
            time_module.sleep(self.check_interval_seconds)

            if not self.enabled:
                continue

            now = datetime.now()
            with self.lock:
                for thread_name, last_feed in list(self.feed_times.items()):
                    if now - last_feed > timedelta(seconds=self.thread_timeout_seconds):
                        self._handle_dead_thread(thread_name)

    def _handle_dead_thread(self, thread_name: str):
        restarts = self.restart_counts.get(thread_name, 0)
        if restarts >= self.max_restarts:
            logger.error(f"Watchdog: {thread_name} failed {restarts} times.")
            if self.reboot_on_failure:
                self._trigger_reboot()
            else:
                logger.warning(f"Max restarts reached for {thread_name} but reboot is disabled in config")
            return

        logger.warning(f"Watchdog: {thread_name} appears dead. Restarting...")

        self.restart_counts[thread_name] = restarts + 1

        if thread_name in restart_handlers:
            try:
                restart_handlers[thread_name]()
                logger.info(f"Watchdog successfully restarted {thread_name}")
                self.feed(thread_name)
            except Exception as e:
                logger.error(f"Failed to restart {thread_name}: {e}")
        else:
            logger.error(f"No restart handler registered for {thread_name}")

    def _trigger_reboot(self):
        if self.socketio:
            self.socketio.emit('show_toast', {
                'message': 'Watchdog detected critical failure. Rebooting system...',
                'duration': 10000,
                'type': 'error'
            })
        logger.critical(f"Watchdog triggering system reboot in {self.reboot_delay_seconds} seconds...")
        time_module.sleep(self.reboot_delay_seconds)
        os.system("sudo reboot")


# Global registry for restart functions
restart_handlers = {}
