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
                self.reeds[reed_id] = button
            except Exception as e:
                logger.error(f"Failed to initialize reed {reed_id} on pin {pin}: {str(e)}", exc_info=True)

        # Apply initial states
        for reed_id, button in self.reeds.items():
            if button.is_pressed:
                self.handle_close(reed_id)
            else:
                self.handle_open(reed_id)

        # Now initialise software state tracking so change detection works correctly
        for reed_id, button in self.reeds.items():
            state = "Closed" if button.is_pressed else "Open"
            self.states[reed_id] = state

        self.start_polling()
        logger.info("ReedsController initialized")

    def set_rules_engine(self, rules_engine):
        self.rules_engine = rules_engine

    def evaluate_open_reeds(self):
        phase = self.get_current_phase()
        if phase is None:
            return
        for reed_id, button in self.reeds.items():
            if not button.is_pressed:
                self.handle_open(reed_id)

    def get_phase_settings(self, reed_id):
        phase = self.get_current_phase()
        if phase not in self.config.get(reed_id, {}):
            return None
        return self.config[reed_id][phase].copy()

    def get_all_channels(self, reed_id):
        channels = set()
        for phase in ['day', 'evening', 'night']:
            phase_data = self.config.get(reed_id, {}).get(phase)
            if phase_data and phase_data.get('channel') is not None:
                channels.add(phase_data['channel'])
        return channels

    def handle_open(self, reed_id):
        phase = self.get_current_phase()
        logger.info(f"Reed {reed_id} opened (phase: {phase})")

        if self.on_state_change:
            self.on_state_change(reed_id, 'Open')

        if self.config[reed_id].get('lock_on_close', False):
            for ch in self.get_all_channels(reed_id):
                self.on_lock(int(ch), False)

        if self.rules_engine:
            self.rules_engine.on_reed_state_change(reed_id, 'Open')

        settings = self.get_phase_settings(reed_id)
        if not settings:
            return

        if reed_id == 'kitchen_bench':
            if self.states.get('kitchen_panel', 'Closed') == 'Open':
                self.on_trigger(settings)
        elif reed_id == 'kitchen_panel':
            self.on_trigger(settings)
            bench_settings = self.get_phase_settings('kitchen_bench')
            if bench_settings and self.states.get('kitchen_bench', 'Closed') == 'Open':
                self.on_trigger(bench_settings)
        else:
            self.on_trigger(settings)

    def handle_close(self, reed_id):
        logger.info(f"Reed {reed_id} closed")

        if self.on_state_change:
            self.on_state_change(reed_id, 'Closed')

        channels = self.get_all_channels(reed_id)
        for ch in channels:
            self.on_trigger({'channel': ch, 'brightness': 0})

        if self.config[reed_id].get('lock_on_close', False):
            for ch in channels:
                self.on_lock(int(ch), True)

        if reed_id == 'kitchen_panel':
            bench_channels = self.get_all_channels('kitchen_bench')
            for ch in bench_channels:
                self.on_trigger({'channel': ch, 'brightness': 0})

        if self.rules_engine:
            self.rules_engine.on_reed_state_change(reed_id, 'Closed')

    def start_polling(self):
        threading.Thread(target=self._poll_thread, daemon=True).start()

    def _poll_thread(self):
        while self.running:
            for reed_id, button in self.reeds.items():
                current = "Closed" if button.is_pressed else "Open"
                if current != self.states.get(reed_id):
                    if current == 'Open':
                        self.handle_open(reed_id)
                    else:
                        self.handle_close(reed_id)
                    self.states[reed_id] = current
            time.sleep(0.5)

    def stop_polling(self):
        self.running = False
        for button in self.reeds.values():
            try:
                button.close()
            except Exception as e:
                logger.warning(f"Error closing reed: {e}")