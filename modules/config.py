# modules/config.py
import configparser
import os
import logging

logger = logging.getLogger("pccs.config")


class PccsConfig:
    def __init__(self):
        self._config = configparser.ConfigParser()
        self._config.optionxform = str

        # Path to pccs.conf
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.path = os.path.join(base_dir, 'config', 'pccs.conf')

        if os.path.exists(self.path):
            self._config.read(self.path, encoding='utf-8')
            logger.info(f"📋 Loaded config file: {self.path}")
        else:
            logger.warning(f"⚠️ Config file not found: {self.path}")

    def get(self, section, key, fallback=None):
        try:
            return self._config.get(section, key, fallback=fallback)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback

    def getint(self, section, key, fallback=None):
        try:
            return self._config.getint(section, key, fallback=fallback)
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
            return fallback

    def getfloat(self, section, key, fallback=None):
        try:
            return self._config.getfloat(section, key, fallback=fallback)
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
            if fallback is not None:
                return float(fallback)
            return None

    def getboolean(self, section, key, fallback=None):
        try:
            return self._config.getboolean(section, key, fallback=fallback)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback

    def getlist(self, section, key, fallback=None):
        value = self.get(section, key, fallback)
        if not value:
            return []
        return [x.strip() for x in value.split(',')]

    def has_section(self, section):
        return self._config.has_section(section)

    def items(self, section):
        """Return section as dict"""
        if self.has_section(section):
            return self._config.items(section)
        return []

    def sections(self):
        return self._config.sections()

    def get_section(self, section: str) -> dict:
        """Convenience: return whole section as dict"""
        if self.has_section(section):
            return dict(self._config.items(section))
        return {}

    @property
    def config(self):
        return self._config


# Global instance
config = PccsConfig()