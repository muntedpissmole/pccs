# Test GPIO's
from gpiozero import Button
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
try:
    button = Button(12, pull_up=True, bounce_time=0.3)
    logger.info(f"Kitchen bench pin 12 state: {'Closed' if button.is_pressed else 'Open'}")
    def on_press():
        logger.info("Kitchen bench pressed (closed)")
    def on_release():
        logger.info("Kitchen bench released (open)")
    button.when_pressed = on_press
    button.when_released = on_release
    input("Press Enter to exit...")
except Exception as e:
    logger.error(f"Error: {e}", exc_info=True)