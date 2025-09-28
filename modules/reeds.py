# modules/reeds.py
from gpiozero import Button
import logging
import time
import threading

logger = logging.getLogger(__name__)

class ReedsController:
    def __init__(self, config, on_trigger, get_current_phase, on_state_change=None, on_lock=None):
        self.config = config
        self.on_trigger = on_trigger
        self.get_current_phase = get_current_phase
        self.on_state_change = on_state_change
        self.on_lock = on_lock or (lambda light_id, locked: None)
        self.rules_engine = None
        self.reeds = {}
        self.states = {}
        self.running = True
        for reed_id, reed_data in self.config.items():
            pin = reed_data.get('pin')
            if pin is None:
                logger.warning(f"Skipping reed {reed_id} with no pin")
                continue
            try:
                button = Button(pin, pull_up=True, bounce_time=0.3)
                # Comment out event handlers since they appear not to be firing
                # button.when_released = lambda r=reed_id: self.handle_open(r)
                # button.when_pressed = lambda r=reed_id: self.handle_close(r)
                self.reeds[reed_id] = button
                initial_state = 'Closed' if button.is_pressed else 'Open'
                self.states[reed_id] = initial_state
                logger.info(f"Initialized reed {reed_id} on pin {pin}, initial state: {initial_state}")
                if initial_state == 'Closed' and reed_data.get('lock_on_close', False):
                    unique_channels = set()
                    for phase in ['day', 'evening', 'night']:
                        if phase in reed_data:
                            phase_data = reed_data[phase]
                            if phase_data and 'channel' in phase_data:
                                unique_channels.add(phase_data['channel'])
                    for ch in unique_channels:
                        self.on_lock(ch, True)
            except Exception as e:
                logger.error(f"Failed to initialize reed {reed_id} on pin {pin}: {str(e)}", exc_info=True)
        
        # Apply and broadcast initial states
        for reed_id, button in self.reeds.items():
            if self.on_state_change:
                state = "Closed" if button.is_pressed else "Open"
                self.on_state_change(reed_id, state)
            if not button.is_pressed:  # Initial open: apply settings
                logger.debug(f"Applying initial open state for reed {reed_id}")
                self.handle_open(reed_id)
        
        self.start_polling()
        logger.info("ReedsController initialized")

    def set_rules_engine(self, rules_engine):
        self.rules_engine = rules_engine

    def evaluate_open_reeds(self):
        phase = self.get_current_phase()
        if phase is None:
            logger.warning("Cannot evaluate open reeds without current phase")
            return
        logger.info(f"Evaluating open reeds for phase {phase}")
        for reed_id, button in self.reeds.items():
            if not button.is_pressed:  # is_pressed False means open/released
                logger.debug(f"Reed {reed_id} is open, applying settings")
                self.handle_open(reed_id)
            else:
                logger.debug(f"Reed {reed_id} is closed, no action")
                if self.on_state_change:
                    self.on_state_change(reed_id, 'Closed')

    def handle_open(self, reed_id):
        logger.debug(f"handle_open called for reed {reed_id}")
        phase = self.get_current_phase()
        logger.info(f"Reed {reed_id} opened, current phase: {phase}")
        if self.on_state_change:
            self.on_state_change(reed_id, 'Open')
        if self.config[reed_id].get('lock_on_close', False):
            unique_channels = set()
            for p in ['day', 'evening', 'night']:
                if p in self.config[reed_id]:
                    pd = self.config[reed_id][p]
                    if pd and 'channel' in pd:
                        unique_channels.add(pd['channel'])
            for ch in unique_channels:
                self.on_lock(ch, False)
        if phase not in self.config[reed_id]:
            logger.warning(f"No action for reed {reed_id} in phase {phase} - phase not in config")
            return  # No action for this phase
        settings = self.config[reed_id][phase]
        if 'channel' not in settings:
            logger.warning(f"Invalid config for reed {reed_id} in phase {phase}: no channel")
            return  # Invalid config; channel required
        logger.info(f"Triggering on_trigger for reed {reed_id} in phase {phase} with settings: {settings}")
        self.on_trigger(settings)
        if self.rules_engine:
            self.rules_engine.on_reed_state_change(reed_id, 'Open')

    def handle_close(self, reed_id):
        logger.debug(f"handle_close called for reed {reed_id}")
        logger.info(f"Reed {reed_id} closed")
        if self.on_state_change:
            self.on_state_change(reed_id, 'Closed')
        unique_channels = set()
        for phase in ['day', 'evening', 'night']:
            if phase in self.config[reed_id]:
                phase_data = self.config[reed_id][phase]
                if phase_data and 'channel' in phase_data:
                    unique_channels.add(phase_data['channel'])
        logger.debug(f"Unique channels to turn off for reed {reed_id}: {unique_channels}")
        for ch in unique_channels:
            settings = {'channel': ch, 'brightness': 0}
            logger.info(f"Turning off channel {ch} for reed {reed_id} with settings: {settings}")
            self.on_trigger(settings)
        if self.config[reed_id].get('lock_on_close', False):
            for ch in unique_channels:
                self.on_lock(ch, True)
        if self.rules_engine:
            self.rules_engine.on_reed_state_change(reed_id, 'Closed')

    def start_polling(self):
        logger.info("Starting reed polling thread")
        threading.Thread(target=self._poll_thread, daemon=True).start()

    def _poll_thread(self):
        while self.running:
            for reed_id, button in self.reeds.items():
                current = 'Closed' if button.is_pressed else 'Open'
                if current != self.states[reed_id]:
                    if current == 'Open':
                        self.handle_open(reed_id)
                    else:
                        self.handle_close(reed_id)
                    self.states[reed_id] = current
            time.sleep(0.5)  # Poll every 0.5 seconds; adjust if needed for responsiveness vs. CPU usage

    def stop_polling(self):
        self.running = False
        for reed_id, button in self.reeds.items():
            try:
                button.close()
            except Exception as e:
                logger.warning(f"Error closing reed {reed_id}: {e}")