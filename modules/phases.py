# modules/phases.py
import threading
import time as time_module
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class PhaseManager:
    def __init__(self, config_manager, handle_apply_scene, get_last_gps_data, get_computed_dt, get_has_gps_fix, socketio, screens_config, current_screen_levels, screen_sids, watchdog=None):
        self.config_manager = config_manager
        self.handle_apply_scene = handle_apply_scene
        self.get_last_gps_data = get_last_gps_data
        self.get_computed_dt = get_computed_dt
        self.get_has_gps_fix = get_has_gps_fix
        self.socketio = socketio
        self.screens_config = screens_config
        self.current_screen_levels = current_screen_levels
        self.screen_sids = screen_sids
        self.watchdog = watchdog                    # Watchdog instance passed from main app
        self.current_phase = None
        self.phase_to_scene = {}
        self.reeds_controller = None
        self.rules_engine = None
        self.prev_dt = None
        logger.info("PhaseManager initialized")

    def set_reeds_controller(self, reeds_controller):
        self.reeds_controller = reeds_controller

    def set_rules_engine(self, rules_engine):
        self.rules_engine = rules_engine

    def parse_time(self, time_str):
        """Parse a time string like '6:30 AM' or '5:45 PM' into datetime.time"""
        try:
            return datetime.strptime(time_str, '%I:%M %p').time()
        except ValueError as e:
            logger.warning(f"Invalid time format: {time_str} — {e}")
            return None

    def parse_offset(self, offset_str):
        """Parse offset like '+30 mins' or '-45 mins' into integer minutes"""
        try:
            num_str = offset_str.strip().split()[0]
            return int(num_str)
        except (ValueError, IndexError) as e:
            logger.warning(f"Invalid offset format: {offset_str} — {e}")
            return 0

    def get_current_phase(self):
        """Determine current phase: 'night', 'day', 'evening', or None"""
        if not self.get_has_gps_fix() or self.get_computed_dt() is None:
            logger.debug("No GPS fix or computed datetime → phase unknown")
            return None

        gps_data = self.get_last_gps_data()
        current_dt = self.get_computed_dt()

        sunrise_str = gps_data.get('sunrise', '---')
        sunset_str = gps_data.get('sunset', '---')

        if sunrise_str == '---' or sunset_str == '---':
            logger.debug("Sunrise/sunset data missing → phase unknown")
            return None

        sunrise_time = self.parse_time(sunrise_str)
        sunset_time = self.parse_time(sunset_str)

        if sunrise_time is None or sunset_time is None:
            logger.warning("Failed to parse sunrise or sunset time")
            return None

        morning_offset_str = self.config_manager.get('sunrise_offset', '+30 mins')
        evening_offset_str = self.config_manager.get('evening_offset', '-30 mins')
        night_time_str = self.config_manager.get('night_time', '8:00 PM')

        morning_offset_mins = self.parse_offset(morning_offset_str)
        evening_offset_mins = self.parse_offset(evening_offset_str)
        night_time = self.parse_time(night_time_str)

        if night_time is None:
            logger.warning("Failed to parse night_time")
            return None

        today = current_dt.date()

        sunrise_dt = datetime.combine(today, sunrise_time)
        sunset_dt = datetime.combine(today, sunset_time)

        # Phase start times
        day_start = sunrise_dt + timedelta(minutes=morning_offset_mins)
        evening_start = sunset_dt + timedelta(minutes=evening_offset_mins)
        night_start = datetime.combine(today, night_time)

        # If night_time is before evening_start, push to next day
        if night_start <= evening_start:
            night_start += timedelta(days=1)

        # Chronological checks
        if current_dt < day_start:
            return 'night'
        elif current_dt < evening_start:
            return 'day'
        elif current_dt < night_start:
            return 'evening'
        else:
            return 'night'

    def phase_check(self):
        new_phase = self.get_current_phase()
        if new_phase != self.current_phase:
            old_phase = self.current_phase
            self.current_phase = new_phase

            # Update reed overrides based on current phase
            if self.reeds_controller is not None:
                self.reeds_controller.evaluate_open_reeds()

            self.socketio.emit('update_phase', {'phase': new_phase})
            logger.info(f"Phase changed: {old_phase or 'None'} → {new_phase}")

            if self.rules_engine:
                self.rules_engine.on_phase_change(new_phase)

            # Auto theme switch (dark mode)
            auto_theme = self.config_manager.get('auto_theme', False)
            if auto_theme and new_phase is not None:
                should_be_dark = new_phase in ['evening', 'night']
                current_dark = self.config_manager.get('dark_mode', False)
                if should_be_dark != current_dark:
                    self.config_manager.set('dark_mode', should_be_dark)
                    self.socketio.emit('update_settings', self.config_manager.config)
                    logger.info(f"Auto theme: dark_mode → {should_be_dark}")

    def check_all_off_time(self):
        """Trigger a custom event 1 hour after sunrise (used by rules)"""
        if not self.get_has_gps_fix():
            return
        current_dt = self.get_computed_dt()
        if current_dt is None:
            return

        gps_data = self.get_last_gps_data()
        sunrise_str = gps_data.get('sunrise', '---')
        if sunrise_str == '---':
            return

        sunrise_time = self.parse_time(sunrise_str)
        if sunrise_time is None:
            return

        today = current_dt.date()
        sunrise_dt = datetime.combine(today, sunrise_time)
        all_off_dt = sunrise_dt + timedelta(hours=1)

        if self.prev_dt is not None and self.prev_dt < all_off_dt <= current_dt:
            if self.rules_engine:
                self.rules_engine.on_time_event("all_off_after_sunrise")
            logger.info("Triggered 'all_off_after_sunrise' time event")

        self.prev_dt = current_dt

    def start(self):
        logger.info("Starting PhaseManager loop")
        self.phase_check()  # Initial evaluation on startup

        self.prev_dt = self.get_computed_dt()
        threading.Thread(target=self._phase_loop, daemon=True).start()

    def _phase_loop(self):
        while True:
            try:
                if self.watchdog:
                    self.watchdog.feed("phase_loop")
                self.phase_check()
                self.check_all_off_time()
                time_module.sleep(15)   # Increased for stability
            except Exception as e:
                logger.error(f"Error in phase_loop: {e}", exc_info=True)
                time_module.sleep(10)
