# modules/gpio.py
from gpiozero import OutputDevice
import logging

logger = logging.getLogger(__name__)

class GPIOController:
    def __init__(self, on_event=None, relays_config={}):
        self.on_event = on_event
        self.relays = {}
        for name, pin in relays_config.items():
            try:
                relay = OutputDevice(pin, active_high=False)
                self.relays[name] = relay
                logger.info(f"Initialized relay {name} on pin {pin}")
            except Exception as e:
                logger.error(f"Failed to initialize relay {name} on pin {pin}: {e}")
        self.relay_states = {k: relay.is_active for k, relay in self.relays.items()}
        self.sensor_states = {}  # If needed for other generic sensors, add config loading here

    def set_relay(self, name, state):
        if name in self.relays:
            try:
                if state:
                    self.relays[name].on()
                else:
                    self.relays[name].off()
                self.relay_states[name] = state
                if self.on_event:
                    self.on_event('update_relays', self.relay_states)
                logger.debug(f"Set relay {name} to {state}")
            except Exception as e:
                logger.error(f"Error setting relay {name} to {state}: {e}")
        else:
            logger.warning(f"Relay {name} not found")

    def get_relay_states(self):
        return self.relay_states

    def get_sensor_states(self):
        return self.sensor_states  # Empty unless generic sensors added