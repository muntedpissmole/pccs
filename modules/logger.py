# modules/logger.py
import logging
import logging.handlers
import sys
from pathlib import Path


def setup_logging(config) -> logging.Logger:
    """
    Setup logging using values from [logging] section in pccs.conf
    """
    level_name = config.get('logging', 'level', fallback='INFO')
    log_dir = config.get('logging', 'log_directory', fallback='logs')
    retention_days = config.getint('logging', 'log_retention_days', fallback=31)

    level = getattr(logging, level_name.upper(), logging.INFO)

    # Ensure logs directory exists
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Main logger
    logger = logging.getLogger("pccs")
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:
        logger.handlers.clear()

    # Formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # ------------------- Console Handler -------------------
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # ------------------- Daily Rotating File Handler -------------------
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=log_path / "pccs.log",
        when="midnight",
        interval=1,
        backupCount=retention_days,
        encoding="utf-8",
        utc=False
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger