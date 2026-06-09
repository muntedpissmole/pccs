# modules/phases.py
import threading
import time
import datetime
import logging
import zoneinfo
from typing import Callable
from suntime import Sun

logger = logging.getLogger("pccs")


def _send_phase_toast(message: str, toast_type: str = "info"):
    """Safe toast sender for phase changes - no title, no custom duration"""
    try:
        from modules.toasts import toast_manager
        if toast_manager is None:
            return

        if toast_type == "warning":
            toast_manager.warning(message, title=None)
        else:
            toast_manager.info(message, title=None)
    except Exception as e:
        logger.debug(f"Could not send phase toast: {e}")


class PhaseManager:
    """Manages Day/Evening/Night phases based on GPS sun times or fallback."""

    def __init__(self, config, gps_module, socketio, dark_mode_config=None):
        self.config = config
        self.gps = gps_module
        self.socketio = socketio
        self.on_phase_change = None  # optional callback(phase, forced_phase, invalidate)
        self.dark_mode_config = dark_mode_config
        
        self.fallback_latitude, self.fallback_longitude = self.gps.get_fallback_coords()
        self.fallback_sun = Sun(self.fallback_latitude, self.fallback_longitude)
        self.fallback_tz = zoneinfo.ZoneInfo(self.gps.get_fallback_timezone())

        self.current_phase = None
        self.forced_phase = None
        self.force_timer = None
        self._last_broadcast_phase = None
        self._cached_phase_times = {}

        self.running = False
        self.thread = None

        # Configuration from pccs.conf
        self.phase_ramp_time_ms = config.getint('lighting', 'phase_ramp_time_ms')
        self.day_offset_minutes = config.getint('phases', 'day_offset_minutes')
        self.evening_offset_minutes = config.getint('phases', 'evening_offset_minutes')
        self.night_start_hour = config.getint('phases', 'night_start_hour')

        # Timeouts
        self.GPS_STARTUP_TIMEOUT = config.getint('phases', 'gps_startup_timeout')
        self.GPS_LOSS_TIMEOUT = config.getint('phases', 'gps_loss_timeout')

        # Dark/Light Mode
        self.current_dark_mode = 'dark'
        self.manual_dark_mode = None        # User manually set override

        self.startup_time = time.time()

        # Night phase listeners (used by VictronManager for daily solar reset, etc.)
        self._night_listeners: list[Callable[[], None]] = []

        self.fallback_latitude = config.getfloat('gps', 'fallback_latitude')
        self.fallback_longitude = config.getfloat('gps', 'fallback_longitude')

        self.fallback_sun = Sun(self.fallback_latitude, self.fallback_longitude)

        self.fallback_tz = zoneinfo.ZoneInfo(
            config.get('gps', 'fallback_timezone', fallback='Australia/Melbourne')
        )

        self._using_fallback = False
        self._last_good_gps_time = time.time()

        self.load_manual_dark_mode()

        logger.info("🌗 PhaseManager initialized")
        logger.info(f"🌙 Night phase starts at {self.night_start_hour}:00")

    def bootstrap_initial_phase(self, use_fallback: bool = False) -> str:
        """Calculate phase at startup without reconcile callbacks (world sync is separate)."""
        self._calculate_and_cache_times()
        if self.forced_phase is not None:
            new_phase = self.forced_phase
        else:
            new_phase = self._calculate_phase(use_fallback)

        new_phase = str(new_phase).strip().title()
        if new_phase == "Waiting":
            new_phase = "Day"

        if self.current_phase != new_phase:
            logger.info(
                f"🌗 Initial phase: {self.current_phase or 'unset'} → {new_phase}"
            )
        self.current_phase = new_phase
        self._last_broadcast_phase = new_phase
        return new_phase

    def start(self):
        if self.running:
            return
        self.running = True

        self._calculate_and_cache_times()
        self._update_phase(use_fallback=False)
        self._auto_update_dark_mode()

        self.thread = threading.Thread(target=self._phase_loop, daemon=True, name="PhaseLoop")
        self.thread.start()

    def stop(self):
        self.running = False
        if self.force_timer:
            self.force_timer.cancel()
            self.force_timer = None

    # ====================== MAIN LOOP ======================
    def _phase_loop(self):
        while self.running:
            try:
                has_real_fix = self._has_valid_gps()

                if has_real_fix:
                    self._last_good_gps_time = time.time()
                    if self._using_fallback:
                        logger.info("🌍 GPS fix restored - returning to live sun data")
                        self._using_fallback = False
                    self._update_phase(use_fallback=False)
                else:
                    now = time.time()
                    if now - self.startup_time > self.GPS_STARTUP_TIMEOUT:
                        if not self._using_fallback:
                            logger.warning(f"🌗 No GPS fix for {int(now - self.startup_time)}s → using fallback")
                            self._using_fallback = True
                        self._update_phase(use_fallback=True)

                time.sleep(5)
            except Exception as e:
                logger.error(f"🌗 Phase loop error: {e}", exc_info=True)
                time.sleep(10)

    # ====================== CORE LOGIC ======================
    def _update_phase(self, use_fallback: bool = False):
        if self.forced_phase is not None:
            new_phase = self.forced_phase
        else:
            new_phase = self._calculate_phase(use_fallback)

        new_phase = str(new_phase).strip().title()
        if new_phase == "Waiting":
            new_phase = "Day"

        if new_phase != self.current_phase:
            emoji_map = {
                "Day":     "🌞",
                "Evening": "🌅",
                "Night":   "🌙",
            }
            emoji = emoji_map.get(new_phase, "🌗")

            logger.info(f"{emoji} Phase changed: {self.current_phase or 'null'} → {new_phase}")

            toast_message = f"{emoji} It is now {new_phase}"
            _send_phase_toast(toast_message)

            old_phase = self.current_phase
            self.current_phase = new_phase
            self._maybe_clear_manual_dark_mode()
            self._broadcast_phase_update()
            self._auto_update_dark_mode()

            # Notify listeners when we enter Night phase (e.g. Victron daily reset)
            if new_phase == "Night" and old_phase != "Night":
                for cb in list(self._night_listeners):
                    try:
                        cb()
                    except Exception as e:
                        logger.error(f"Night phase listener failed: {e}")

    def _maybe_clear_manual_dark_mode(self):
        """Clear manual dark/light mode when the phase naturally changes to a point
        where the manual setting no longer matches what the phase would want."""
        if not self.manual_dark_mode:
            return

        desired_mode = 'light' if self.current_phase.lower() == 'day' else 'dark'

        if self.manual_dark_mode != desired_mode:
            self.clear_manual_dark_mode()
        else:
            logger.debug(f"🌗 Manual dark mode {self.manual_dark_mode} still matches desired phase mode")

    def _get_sun_times(self, use_fallback: bool):
        tz = self.fallback_tz
        now = datetime.datetime.now(tz)

        if not use_fallback and self._has_valid_gps():
            state = self.gps.get_state()
            tz = zoneinfo.ZoneInfo(state.get("timezone", "Australia/Melbourne"))
            now = datetime.datetime.now(tz)

            sunrise = self._parse_sun_time(state.get("sunrise"), tz, now)
            sunset = self._parse_sun_time(state.get("sunset"), tz, now)
        else:
            sunrise = self.fallback_sun.get_local_sunrise_time(now, tz)
            sunset = self.fallback_sun.get_local_sunset_time(now, tz)

        sunrise = sunrise.replace(year=now.year, month=now.month, day=now.day)
        sunset = sunset.replace(year=now.year, month=now.month, day=now.day)

        return sunrise, sunset, tz, now

    def _calculate_phase(self, use_fallback: bool) -> str:
        try:
            sunrise, sunset, _, now = self._get_sun_times(use_fallback)

            day_start = sunrise + datetime.timedelta(minutes=self.day_offset_minutes)
            evening_start = sunset - datetime.timedelta(minutes=self.evening_offset_minutes)
            night_start_today = now.replace(hour=self.night_start_hour, minute=0, second=0, microsecond=0)
            effective_night_start = max(evening_start, night_start_today)

            if now < day_start or now >= effective_night_start:
                return "Night"
            elif now >= evening_start:
                return "Evening"
            else:
                return "Day"

        except Exception as e:
            logger.error(f"🌗 Phase calculation failed: {e}", exc_info=True)
            return "Day"

    def _log_dark_mode_change(self, mode: str, source: str):
        """Unified dark mode logging"""
        logger.info(f"🌑 Dark mode → {mode} [{source}]")

    def _auto_update_dark_mode(self):
        if self.manual_dark_mode is not None:
            return

        if not self.socketio:
            return
        try:
            phase = self.get_phase().lower()
            if phase not in ("day", "evening", "night"):
                return

            desired_mode = 'light' if phase == 'day' else 'dark'

            if desired_mode != self.current_dark_mode:
                self.current_dark_mode = desired_mode
                self._log_dark_mode_change(desired_mode, "phase change")
                self._broadcast_dark_mode()
        except Exception as e:
            logger.debug(f"Auto dark mode check failed: {e}")

    # ====================== MANUAL DARK MODE SUPPORT ======================
    def load_manual_dark_mode(self):
        """Load saved dark mode from config"""
        if not self.dark_mode_config:
            logger.warning("No dark_mode_config attached")
            self.manual_dark_mode = None
            return

        try:
            data = self.dark_mode_config.load()
            if data.get('manual', False):
                mode = data.get('mode')
                self.manual_dark_mode = mode
                self.current_dark_mode = mode
                self._log_dark_mode_change(mode, "startup")
            else:
                self.manual_dark_mode = None
                logger.debug("🌑 No saved dark mode override - will follow phase")
        except Exception as e:
            logger.warning(f"Failed to load dark mode config: {e}")
            self.manual_dark_mode = None

    def set_manual_dark_mode(self, mode: str):
        """Set dark mode from user action"""
        if mode not in ('light', 'dark'):
            return

        self.manual_dark_mode = mode
        self.current_dark_mode = mode

        if self.dark_mode_config:
            try:
                self.dark_mode_config.save({'mode': mode, 'manual': True})
            except Exception as e:
                logger.error(f"Failed to save dark mode: {e}")

        self._log_dark_mode_change(mode, "user interface")
        self._broadcast_dark_mode()

    def clear_manual_dark_mode(self):
        """Clear manual override and return to phase-based mode"""
        self.manual_dark_mode = None

        if self.dark_mode_config:
            try:
                self.dark_mode_config.save({'mode': 'dark', 'manual': False})
            except Exception:
                pass

    def _broadcast_dark_mode(self):
        """Send update with manual override flag"""
        if not self.socketio:
            return
        self.socketio.emit('global_dark_mode_update', {
            'mode': self.get_current_dark_mode(),
            'manual': self.manual_dark_mode is not None
        })

    # ====================== HELPERS ======================
    def _has_valid_gps(self) -> bool:
        state = self.gps.get_state()
        return (
            state.get("fix_quality", 0) >= 1 and
            bool(state.get("sunrise")) and
            bool(state.get("sunset"))
        )

    def _parse_sun_time(self, time_str: str, tz, now):
        if not time_str:
            raise ValueError("No sun time available")
        for fmt in ("%I:%M %p", "%-I:%M %p", "%H:%M"):
            try:
                dt = datetime.datetime.strptime(time_str, fmt)
                return dt.replace(year=now.year, month=now.month, day=now.day, tzinfo=tz)
            except ValueError:
                continue
        raise ValueError(f"Could not parse sun time: {time_str}")

    def _calculate_and_cache_times(self):
        start_time = time.time()
        logger.debug("🌗 [CACHE] Starting phase times calculation")

        try:
            sunrise, sunset, _, now = self._get_sun_times(use_fallback=False)

            day_start = sunrise + datetime.timedelta(minutes=self.day_offset_minutes)
            evening_start = sunset - datetime.timedelta(minutes=self.evening_offset_minutes)
            night_start_today = now.replace(hour=self.night_start_hour, minute=0, second=0, microsecond=0)
            effective_night_start = max(evening_start, night_start_today)

            self._cached_phase_times = {
                "day_start": day_start.strftime("%I:%M %p"),
                "evening_start": evening_start.strftime("%I:%M %p"),
                "night_start": effective_night_start.strftime("%I:%M %p"),
                "sunrise": sunrise.strftime("%I:%M %p"),
                "sunset": sunset.strftime("%-I:%M %p"),
                "day_offset_min": self.day_offset_minutes,
                "evening_offset_min": self.evening_offset_minutes,
                "night_fixed_hour": self.night_start_hour,
            }

            duration = (time.time() - start_time) * 1000
            logger.debug(f"🌗 [CACHE] SUCCESS in {duration:.1f}ms")

        except Exception as e:
            logger.error(f"🌗 [CACHE] FAILED: {e}", exc_info=True)
            self._cached_phase_times = {"day_start": "—", "evening_start": "—", "night_start": "—", "sunrise": "—", "sunset": "—"}

    # ====================== PUBLIC API ======================
    def get_phase(self) -> str:
        if self.forced_phase is not None:
            return str(self.forced_phase).strip().title()
        return self.current_phase or "Day"

    def is_forced(self) -> bool:
        return self.forced_phase is not None

    def get_phase_ramp_time(self):
        return self.phase_ramp_time_ms

    def get_current_dark_mode(self) -> str:
        """Public API - respects manual override if present"""
        if self.manual_dark_mode is not None:
            return self.manual_dark_mode
        return self.current_dark_mode

    def _emit_phase_diag(self):
        if self.socketio:
            try:
                self.socketio.emit('phase_diag_update', {'forced': self.is_forced()})
            except Exception:
                pass

    def force_phase(self, phase: str):
        if self.force_timer:
            self.force_timer.cancel()
            self.force_timer = None

        self.forced_phase = str(phase).strip().title()
        logger.debug(f"🔧 Phase forced → {self.forced_phase}")
        self._update_phase()
        self._emit_phase_diag()

    def clear_force(self):
        old = self.forced_phase
        self.forced_phase = None
        if self.force_timer:
            self.force_timer.cancel()
            self.force_timer = None

        if old is not None:
            logger.debug(f"🔄 Cleared forced phase (was: {old})")
        else:
            logger.debug("🔄 clear_force called with no active force")

        self._update_phase()
        self._emit_phase_diag()

    # --------------------------- Night phase listeners (for Victron daily reset etc.) ---------------------------

    def register_night_listener(self, callback: Callable[[], None]):
        """Register a callback that will be invoked when the system enters Night phase."""
        if callback and callback not in self._night_listeners:
            self._night_listeners.append(callback)
            logger.debug("🌙 Registered night phase listener")

    def unregister_night_listener(self, callback: Callable[[], None]):
        if callback in self._night_listeners:
            self._night_listeners.remove(callback)

    def get_phase_times(self) -> dict:
        if not self._cached_phase_times or len(self._cached_phase_times) < 3:
            self._calculate_and_cache_times()
        return self._cached_phase_times.copy()

    def _broadcast_phase_update(self):
        try:
            times = self.get_phase_times()
            payload = {
                'phase': self.get_phase(),
                'using_fallback': self._using_fallback,
                'waiting_for_gps': self.current_phase is None,
                **times
            }
            self.socketio.emit('phase_update', payload)
            self.socketio.emit('phase_diag_update', {'forced': self.is_forced()})

            if (self.current_phase is not None and
                self.current_phase != self._last_broadcast_phase):
                if self.on_phase_change:
                    self.on_phase_change(
                        self.get_phase(),
                        self.forced_phase,
                        True,
                    )
                self._last_broadcast_phase = self.current_phase

        except Exception as e:
            logger.error(f"Phase broadcast failed: {e}")