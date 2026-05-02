# modules/phases.py
import threading
import time
import datetime
import logging
import zoneinfo
from suntime import Sun

logger = logging.getLogger("pccs")


class PhaseManager:
    """Manages Day/Evening/Night phases based on GPS sun times or fallback."""

    def __init__(self, gps_module, socketio):
        self.gps = gps_module
        self.socketio = socketio
        self.reed_manager = None

        self.current_phase = None
        self.forced_phase = None
        self.force_timer = None
        self._last_broadcast_phase = None

        self.running = False
        self.thread = None

        # Configuration
        self.phase_ramp_time_ms = 4000

        self.day_offset_minutes = 45
        self.evening_offset_minutes = 45
        self.night_start_hour = 21

        # Timeouts
        self.GPS_STARTUP_TIMEOUT = 900   # 15 minutes
        self.GPS_LOSS_TIMEOUT = 3600     # 1 hour

        self.startup_time = time.time()

        # Fallback
        self.fallback_sun = Sun(-37.191, 145.711)
        self.fallback_tz = zoneinfo.ZoneInfo("Australia/Melbourne")

        self._using_fallback = False
        self._last_good_gps_time = time.time()

        logger.info("🌗 PhaseManager initialized")
        logger.debug(f"🌗 Night phase forced start at {self.night_start_hour}:00")

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._phase_loop, daemon=True, name="PhaseLoop")
        self.thread.start()

    def stop(self):
        self.running = False
        if self.force_timer:
            self.force_timer.cancel()
            self.force_timer = None

    # ====================== MAIN LOOP ======================
    def _phase_loop(self):
        """Background thread that updates phase every 5 seconds."""
        while self.running:
            try:
                has_real_fix = self._has_valid_gps()

                if has_real_fix:
                    self._last_good_gps_time = time.time()
                    if self._using_fallback:
                        logger.info("🌗 GPS fix restored - returning to live sun data")
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
        """Calculate and apply new phase if changed."""
        if self.forced_phase is not None:
            new_phase = self.forced_phase
        else:
            new_phase = self._calculate_phase(use_fallback)

        new_phase = str(new_phase).strip().title()
        if new_phase == "Waiting":
            new_phase = "Day"

        if new_phase != self.current_phase:
            source = "forced" if self.forced_phase else ("fallback" if use_fallback else "GPS")
            logger.info(f"🌗 Phase changed: {self.current_phase} → {new_phase} ({source})")

            self.current_phase = new_phase
            self._broadcast_phase_update()

    def _calculate_phase(self, use_fallback: bool) -> str:
        """Calculate current phase from sun times."""
        try:
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

            # Force sunrise/sunset to today (suntime sometimes returns previous day)
            sunrise = sunrise.replace(year=now.year, month=now.month, day=now.day)
            sunset = sunset.replace(year=now.year, month=now.month, day=now.day)

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

    def _has_valid_gps(self) -> bool:
        """Check if we have usable GPS sun data."""
        state = self.gps.get_state()
        return (
            state.get("fix_quality", 0) >= 1 and
            bool(state.get("sunrise")) and
            bool(state.get("sunset"))
        )

    def _parse_sun_time(self, time_str: str, tz, now):
        """Safely parse sunrise/sunset strings."""
        if not time_str:
            raise ValueError("No sun time available")
        for fmt in ("%I:%M %p", "%-I:%M %p", "%H:%M"):
            try:
                dt = datetime.datetime.strptime(time_str, fmt)
                return dt.replace(year=now.year, month=now.month, day=now.day, tzinfo=tz)
            except ValueError:
                continue
        raise ValueError(f"Could not parse sun time: {time_str}")

    # ====================== PUBLIC API ======================
    def get_phase(self) -> str:
        if self.forced_phase is not None:
            return str(self.forced_phase).strip().title()
        return self.current_phase or "Day"

    def is_forced(self) -> bool:
        return self.forced_phase is not None

    def get_phase_ramp_time(self):
        return self.phase_ramp_time_ms

    def force_phase(self, phase: str):
        if self.force_timer:
            self.force_timer.cancel()
            self.force_timer = None

        self.forced_phase = str(phase).strip().title()
        logger.info(f"🔧 Phase manually forced → {self.forced_phase}")
        self._update_phase()

    def force_phase(self, phase: str):
        if self.force_timer:
            self.force_timer.cancel()
            self.force_timer = None

        self.forced_phase = str(phase).strip().title()
        logger.info(f"🔧 Phase manually forced → {self.forced_phase}")
        self._update_phase()

    def clear_force(self):
        """Clear any forced phase."""
        old = self.forced_phase
        self.forced_phase = None
        if self.force_timer:
            self.force_timer.cancel()
            self.force_timer = None

        if old is not None:
            logger.info(f"🔄 Cleared forced phase (was: {old})")
        else:
            logger.debug("🔄 clear_force called with no active force")

        self._update_phase()

    def get_phase_times(self) -> dict:
        """Return human-readable phase transition times."""
        if self.forced_phase:
            return {}

        try:
            tz = self.fallback_tz
            now = datetime.datetime.now(tz)

            if self._has_valid_gps():
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

            day_start = sunrise + datetime.timedelta(minutes=self.day_offset_minutes)
            evening_start = sunset - datetime.timedelta(minutes=self.evening_offset_minutes)
            night_start_today = now.replace(hour=self.night_start_hour, minute=0, second=0, microsecond=0)
            effective_night_start = max(evening_start, night_start_today)

            return {
                "day_start": day_start.strftime("%I:%M %p"),
                "evening_start": evening_start.strftime("%I:%M %p"),
                "night_start": effective_night_start.strftime("%I:%M %p"),
                "day_offset_min": self.day_offset_minutes,
                "evening_offset_min": self.evening_offset_minutes,
                "night_fixed_hour": self.night_start_hour,
            }
        except Exception as e:
            logger.error(f"Failed to calculate phase times: {e}")
            return {}

    def _broadcast_phase_update(self):
        """Broadcast phase change and trigger reed re-evaluation."""
        try:
            payload = {
                'phase': self.get_phase(),
                'forced': self.is_forced(),
                'using_fallback': self._using_fallback,
                'waiting_for_gps': self.current_phase is None,
                **self.get_phase_times()
            }
            self.socketio.emit('phase_update', payload)

            # Re-apply lights for any open reeds when phase changes
            if (self.reed_manager and 
                self.current_phase is not None and 
                self.current_phase != self._last_broadcast_phase):
                
                self.reed_manager.reapply_all_open_lights(self)
                self._last_broadcast_phase = self.current_phase

        except Exception as e:
            logger.error(f"Phase broadcast failed: {e}")