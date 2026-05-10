# modules/gpio.py
from gpiozero import OutputDevice, Button, Device
from gpiozero.pins.lgpio import LGPIOFactory
import logging

logger = logging.getLogger("pccs")


class GPIODeviceManager:
    def __init__(self, config):
        self.config = config
        self.devices = {}
        self.reeds = {}
        self.relays = {}
        self.reed_states = {}
        self.reed_to_light_map = {}
        self.relay_initial_states = {}

        self._setup_pin_factory()

    def _setup_pin_factory(self):
        try:
            if Device.pin_factory is None:
                Device.pin_factory = LGPIOFactory()
                logger.debug("🏭 LGPIOFactory initialized")
        except Exception as e:
            logger.error(f"Failed to set LGPIOFactory: {e}")

    def init_devices(self) -> None:
        logger.debug("🔧 Initializing GPIO relays and reeds...")

        # ====================== RELAYS (from [gpio]) ======================
        if self.config.has_section('gpio'):
            gpio_section = self.config.get_section('gpio')
            for name, line in gpio_section.items():
                if name.endswith(('_pin', '_pull_up', '_bounce_time')):
                    continue  # skip old reed config lines

                parts = [p.strip() for p in str(line).split('|')]
                if len(parts) < 2:
                    continue

                friendly = parts[0]
                try:
                    pin = int(parts[1])
                except ValueError:
                    continue

                active_high = len(parts) > 2 and parts[2].lower() == 'true'
                initial = len(parts) > 3 and parts[3].lower() == 'true'
                icon = parts[4] if len(parts) > 4 and parts[4].startswith('fa-') else "fa-lightbulb"

                try:
                    dev = OutputDevice(pin, active_high=active_high, initial_value=initial)
                    self.devices[name] = dev
                    self.relays[name] = dev
                    self.relay_initial_states[name] = initial

                    logger.debug(f"📟 Relay: {name} → {friendly} (GPIO {pin}, initial={'ON' if initial else 'OFF'})")
                except Exception as e:
                    logger.error(f"Failed to create relay {name}: {e}")

        # ====================== REEDS (from new [reeds] section) ======================
        if self.config.has_section('reeds'):
            reed_section = self.config.get_section('reeds')
            for name, line in reed_section.items():
                parts = [p.strip() for p in str(line).split('|')]
                if len(parts) < 2:
                    continue

                friendly = parts[0]
                try:
                    pin = int(parts[1])
                except ValueError:
                    continue

                pull_up = len(parts) > 2 and parts[2].lower() != 'false'
                bounce = float(parts[3]) if len(parts) > 3 else 0.5

                # ==================== CONTROLS FIELD PARSING ====================
                controls = [name]
                if len(parts) > 6:
                    last_field = parts[6].strip()
                    if last_field.startswith("controls:"):
                        light_list = last_field[9:].strip()
                        if light_list:
                            controls = [x.strip() for x in light_list.split(',') if x.strip()]
                    elif last_field:
                        controls = [last_field]

                try:
                    button = Button(pin, pull_up=pull_up, bounce_time=bounce)
                    self.devices[name] = button
                    self.reeds[name] = button
                    self.reed_states[name] = button.is_pressed
                    self.reed_to_light_map[name] = controls

                    logger.debug(f"🚪 Reed: {name} → {friendly} controls {controls} (GPIO {pin})")
                except Exception as e:
                    logger.error(f"Failed to create reed {name}: {e}")

        logger.info(f"🏭 GPIO initialized → {len(self.relays)} relay(s), {len(self.reeds)} reed(s)")

    def get_device(self, name: str):
        return self.devices.get(name)

    def get_relay(self, name: str):
        return self.relays.get(name)

    def cleanup(self):
        for dev in self.devices.values():
            try:
                dev.close()
            except:
                pass
        self.devices.clear()
        self.relays.clear()
        self.reeds.clear()
        self.reed_to_light_map.clear()