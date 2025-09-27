# modules/reeds.py
from gpiozero import Button
import logging

logger = logging.getLogger(__name__)

class ReedsController:
    def __init__(self, config, on_trigger, get_current_phase):
        self.config = config
        self.on_trigger = on_trigger
        self.get_current_phase = get_current_phase
        self.reeds = {}
        for reed_id, reed_data in self.config.items():
            pin = reed_data.get('pin')
            if pin is None:
                logger.warning(f"Skipping reed {reed_id} with no pin")
                continue
            try:
                button = Button(pin, pull_up=True, bounce_time=0.3)  # Added bounce_time for debouncing
                # Trigger on release (door/panel opens: from closed/pressed to open/released)
                button.when_released = lambda r=reed_id: self.handle_open(r)
                # Trigger on press (door/panel closes: from open/released to closed/pressed)
                button.when_pressed = lambda r=reed_id: self.handle_close(r)
                self.reeds[reed_id] = button
                logger.info(f"Initialized reed {reed_id} on pin {pin}")
            except Exception as e:
                logger.error(f"Failed to initialize reed {reed_id}: {e}")
        logger.info("ReedsController initialized")

    def handle_open(self, reed_id):
        phase = self.get_current_phase()
        logger.debug(f"Reed {reed_id} opened in phase {phase}")
        if phase not in self.config[reed_id]:
            logger.debug(f"No action for reed {reed_id} in phase {phase}")
            return  # No action for this phase
        settings = self.config[reed_id][phase]
        if 'channel' not in settings:
            logger.warning(f"Invalid config for reed {reed_id} in phase {phase}: no channel")
            return  # Invalid config; channel required
        self.on_trigger(settings)

    def handle_close(self, reed_id):
        logger.debug(f"Reed {reed_id} closed")
        unique_channels = set()
        for phase in ['day', 'evening', 'night']:
            if phase in self.config[reed_id]:
                phase_data = self.config[reed_id][phase]
                if phase_data and 'channel' in phase_data:
                    unique_channels.add(phase_data['channel'])
        for ch in unique_channels:
            settings = {'channel': ch, 'brightness': 0}
            self.on_trigger(settings)