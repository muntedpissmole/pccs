# modules/phases.py
import threading
import time as time_module
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class PhaseManager:
    def __init__(self, config_manager, handle_apply_scene, get_last_gps_data, get_computed_dt, get_has_gps_fix, socketio, screens_config, set_screen_brightness, current_screen_levels, screen_sids):
        self.config_manager = config_manager
        self.handle_apply_scene = handle_apply_scene
        self.get_last_gps_data = get_last_gps_data
        self.get_computed_dt = get_computed_dt
        self.get_has_gps_fix = get_has_gps_fix
        self.socketio = socketio
        self.screens_config = screens_config
        self.set_screen_brightness = set_screen_brightness
        self.current_screen_levels = current_screen_levels
        self.screen_sids = screen_sids
        self.current_phase = None
        self.phase_to_scene = {}  # Empty to disable auto scene application; will be handled by rules engine
        self.reeds_controller = None  # Will be set after initialization
        self.rules_engine = None
        self.prev_dt = None
        logger.info("PhaseManager initialized")

    def set_reeds_controller(self, reeds_controller):
        self.reeds_controller = reeds_controller

    def set_rules_engine(self, rules_engine):
        self.rules_engine = rules_engine

    def parse_time(self, time_str):
        try:
            return datetime.strptime(time_str, '%I:%M %p').time()
        except ValueError as e:
            logger.warning(f"Invalid time format: {time_str}, {e}")
            return None

    def parse_offset(self, offset_str):
        try:
            # Extracts the number part, handling + or -
            num_str = offset_str.split(' ')[0]
            return int(num_str)
        except (ValueError, IndexError) as e:
            logger.warning(f"Invalid offset format: {offset_str}, {e}")
            return 0

    def get_current_phase(self):
        if not self.get_has_gps_fix() or self.get_computed_dt() is None:
            logger.debug("No GPS fix or computed DT, phase unknown")
            return None

        gps_data = self.get_last_gps_data()
        current_dt = self.get_computed_dt()

        sunrise_str = gps_data.get('sunrise', '---')
        sunset_str = gps_data.get('sunset', '---')

        if sunrise_str == '---' or sunset_str == '---':
            logger.debug("Sunrise/sunset unknown, phase unknown")
            return None

        sunrise_time = self.parse_time(sunrise_str)
        sunset_time = self.parse_time(sunset_str)

        if sunrise_time is None or sunset_time is None:
            return None

        evening_offset_str = self.config_manager.get('evening_offset', '-30 mins')
        morning_offset_str = self.config_manager.get('sunrise_offset', '+30 mins')
        night_time_str = self.config_manager.get('night_time', '8:00 PM')

        evening_offset_mins = self.parse_offset(evening_offset_str)
        morning_offset_mins = self.parse_offset(morning_offset_str)
        night_time = self.parse_time(night_time_str)

        if night_time is None:
            return None

        today = current_dt.date()
        sunrise_dt = datetime.combine(today, sunrise_time)
        sunset_dt = datetime.combine(today, sunset_time)

        day_start_dt = sunrise_dt + timedelta(minutes=morning_offset_mins)
        evening_start_dt = sunset_dt + timedelta(minutes=evening_offset_mins)
        night_start_dt = datetime.combine(today, night_time)

        # If night start is before evening start, assume next day (unlikely, but handle)
        if night_start_dt < evening_start_dt:
            night_start_dt += timedelta(days=1)

        if current_dt < day_start_dt:
            return 'night'
        elif current_dt < evening_start_dt:
            return 'day'
        elif current_dt < night_start_dt:
            return 'evening'
        else:
            return 'night'

    def phase_check(self):
        new_phase = self.get_current_phase()
        if new_phase is not None and new_phase != self.current_phase:
            old_phase = self.current_phase
            self.current_phase = new_phase
            # Apply scene if mapped
            scene_id = self.phase_to_scene.get(new_phase)
            if scene_id:
                self.handle_apply_scene({'scene_id': scene_id})
            # Update reed settings for open reeds
            if self.reeds_controller is not None:
                self.reeds_controller.evaluate_open_reeds()
            self.socketio.emit('update_phase', {'phase': new_phase})
            logger.info(f"Phase changed to {new_phase} from {old_phase}")
            if self.rules_engine:
                self.rules_engine.on_phase_change(new_phase)

            # Handle auto theme switch
            auto_theme = self.config_manager.get('auto_theme', False)
            if auto_theme and self.current_phase is not None:
                should_be_dark = self.current_phase in ['evening', 'night']
                current_dark = self.config_manager.get('dark_mode', False)
                if should_be_dark != current_dark:
                    self.config_manager.set('dark_mode', should_be_dark)
                    self.socketio.emit('update_settings', self.config_manager.config)
                    logger.info(f"Auto theme switch: set dark_mode to {should_be_dark} due to phase {self.current_phase}")

            # Handle auto brightness
            auto_brightness = self.config_manager.get('auto_brightness', False)
            if auto_brightness:
                brightness_level = {'day': 'high', 'evening': 'medium', 'night': 'low'}.get(new_phase)
                if brightness_level:
                    for screen_name in self.screens_config:
                        self.set_screen_brightness(screen_name, brightness_level)
                        self.current_screen_levels[screen_name] = brightness_level
                        if screen_name in self.screen_sids:
                            self.socketio.emit('update_brightness_level', {'level': brightness_level}, to=self.screen_sids[screen_name])

    def check_all_off_time(self):
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
            logger.info("Triggered all off after sunrise event")
        self.prev_dt = current_dt

    def start(self):
        logger.info("Starting phase loop thread")
        self.phase_check()  # Evaluate and apply on startup
        auto_brightness = self.config_manager.get('auto_brightness', False)
        if auto_brightness and self.current_phase:
            brightness_level = {'day': 'high', 'evening': 'medium', 'night': 'low'}.get(self.current_phase)
            if brightness_level:
                for screen_name in self.screens_config:
                    self.set_screen_brightness(screen_name, brightness_level)
                    self.current_screen_levels[screen_name] = brightness_level
                    if screen_name in self.screen_sids:
                        self.socketio.emit('update_brightness_level', {'level': brightness_level}, to=self.screen_sids[screen_name])
        self.prev_dt = self.get_computed_dt()
        threading.Thread(target=self._phase_loop, daemon=True).start()

    def _phase_loop(self):
        while True:
            self.phase_check()
            self.check_all_off_time()
            time_module.sleep(10)  # Reduced from 60 to 10 for faster response