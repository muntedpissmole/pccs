# modules/gpio.py
from gpiozero import OutputDevice, Button
from typing import Dict, Any
import logging

logger = logging.getLogger("pccs")


class GPIODeviceManager:
    """Manages all GPIO devices (outputs + reed switch inputs) using gpiozero."""

    def __init__(self):
        self.devices: Dict[str, OutputDevice | Button] = {}
        self.reeds: Dict[str, Button] = {}           # Reed switches only
        self.reed_states: Dict[str, bool] = {}

    def init_devices(self, config: Dict[str, Dict[str, Any]]) -> None:
        """Initialize all GPIO devices from configuration dictionary."""
        for name, cfg in config.items():
            try:
                if cfg['type'] == 'output':
                    self.devices[name] = OutputDevice(
                        pin=cfg['pin'],
                        active_high=cfg.get('active_high', True),
                        initial_value=cfg.get('initial', False)
                    )
                    logger.debug(f"Initialized output: {name} (GPIO {cfg['pin']})")

                elif cfg['type'] == 'input':
                    button = Button(
                        pin=cfg['pin'],
                        pull_up=cfg.get('pull_up', True),
                        bounce_time=cfg.get('bounce_time', 0.05)
                    )
                    self.devices[name] = button
                    self.reeds[name] = button

                    # Capture initial state
                    self.reed_states[name] = button.is_pressed
                    logger.debug(f"Initialized reed: {name} (GPIO {cfg['pin']})")

                else:
                    logger.warning(f"Unknown device type for {name}")
                    self.devices[name] = None

            except Exception as e:
                logger.error(f"Failed to initialize {name} (GPIO {cfg.get('pin')}): {e}")
                self.devices[name] = None

        logger.info(f"GPIO initialized → {len(self.reeds)} reeds, "
                   f"{len([d for d in self.devices.values() if not isinstance(d, Button)])} outputs")

    def get_device(self, name: str):
        """Return device by name (OutputDevice or Button)."""
        return self.devices.get(name)

    def cleanup(self):
        """Close all GPIO devices."""
        for name, device in list(self.devices.items()):
            if device:
                try:
                    device.close()
                except Exception as e:
                    logger.warning(f"Error closing {name}: {e}")

        self.devices.clear()
        self.reeds.clear()
        self.reed_states.clear()
        logger.debug("GPIO cleanup completed")