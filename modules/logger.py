# modules/logger.py
import logging
import logging.handlers
import sys
from pathlib import Path


def setup_logging(level=logging.INFO, log_dir: str = "logs") -> logging.Logger:
    """
    Setup logging with console output + daily rotating files (~31 days retention).
    """
    # Ensure logs directory exists
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Main logger
    logger = logging.getLogger("pccs")
    logger.setLevel(level)
    logger.propagate = False

    # Clear existing handlers (important during reloads)
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
        backupCount=31,
        encoding="utf-8",
        utc=False
    )
    file_handler.setLevel(logging.INFO)   # Always persist INFO+ to disk
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Startup messages (DEBUG only)
    logger.debug("🚀 Logging system initialized")
    logger.debug(f"📁 Log directory: {log_path.absolute()}")
    logger.debug(f"📅 Retention: 31 days (daily rotation) | Level: {logging.getLevelName(level)}")

    return logger