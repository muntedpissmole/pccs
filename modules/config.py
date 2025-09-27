# modules/config.py
import json
import re
import logging

logger = logging.getLogger(__name__)

class ConfigManager:
    def __init__(self, file_path='settings.json'):
        self.file_path = file_path
        try:
            with open(self.file_path, 'r') as f:
                self.config = json.load(f)
            self.validate()
            logger.info(f"Config loaded from {file_path}")
        except FileNotFoundError:
            logger.error(f"Config file not found: {file_path}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file {file_path}: {e}")
            raise

    def validate(self):
        required_keys = ['dark_mode', 'auto_theme', 'auto_brightness', 'evening_offset', 'morning_offset', 'night_time']
        for key in required_keys:
            if key not in self.config:
                logger.error(f"Missing required key '{key}' in {self.file_path}")
                raise ValueError(f"Missing required key '{key}' in {self.file_path}")
        
        # Type checks
        bool_keys = ['dark_mode', 'auto_theme', 'auto_brightness']
        for key in bool_keys:
            if not isinstance(self.config[key], bool):
                logger.error(f"'{key}' must be a boolean in {self.file_path}")
                raise ValueError(f"'{key}' must be a boolean in {self.file_path}")
        
        str_keys = ['evening_offset', 'morning_offset', 'night_time']
        for key in str_keys:
            if not isinstance(self.config[key], str):
                logger.error(f"'{key}' must be a string in {self.file_path}")
                raise ValueError(f"'{key}' must be a string in {self.file_path}")
        
        # Additional format checks for offsets and time
        offset_pattern = re.compile(r'^[+-]\d+\s*mins?$')
        for offset_key in ['evening_offset', 'morning_offset']:
            if not offset_pattern.match(self.config[offset_key]):
                logger.error(f"Invalid format for '{offset_key}' in {self.file_path}. Expected: '+/-NN mins'")
                raise ValueError(f"Invalid format for '{offset_key}' in {self.file_path}. Expected: '+/-NN mins'")
        
        time_pattern = re.compile(r'^\d{1,2}:\d{2}\s*(AM|PM)?$', re.IGNORECASE)
        if not time_pattern.match(self.config['night_time']):
            logger.error(f"Invalid format for 'night_time' in {self.file_path}. Expected: 'HH:MM AM/PM' or 'HH:MM'")
            raise ValueError(f"Invalid format for 'night_time' in {self.file_path}. Expected: 'HH:MM AM/PM' or 'HH:MM'")

    def save(self):
        try:
            with open(self.file_path, 'w') as f:
                json.dump(self.config, f, indent=4)
            logger.debug(f"Config saved to {self.file_path}")
        except Exception as e:
            logger.error(f"Failed to save config to {self.file_path}: {e}")

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value
        self.save()