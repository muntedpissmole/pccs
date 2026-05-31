# modules/arduino.py
import serial
import threading
import time
import os
import logging

logger = logging.getLogger("pccs")


class ArduinoManager:
    def __init__(self, config):
        self.config = config
        self.ser = None
        self.serial_lock = threading.Lock()
        self.state = {}

        self.OPTIMISTIC_LOCK: dict[str, float] = {}
        self.OPTIMISTIC_LOCK_DURATION = config.getfloat('arduino', 'optimistic_lock_duration', 2.5)

        self.LIGHT_MAP = {}
        self.RGB_BUG_LIGHTS = {}
        self.LIGHT_ICONS = {}

        self._frontend_controls = []   # Unified ordered list for frontend

        self._load_all_controls()

        self.COMMAND_DELAY = config.getfloat('arduino', 'command_delay', 0.08)
        self.RESPONSE_DELAY = config.getfloat('arduino', 'response_delay', 0.04)
        self.RGB_RED_SWITCH_RAMP = config.getint('arduino', 'rgb_red_switch_ramp_ms', 180)
        self.RGB_MODE_SWITCH_RAMP = config.getint('arduino', 'rgb_mode_switch_ramp_ms', 250)

    def _load_all_controls(self):
        """Load PWM, RGB, and Relay controls with custom ordering"""
        # Safely clear all collections
        self.LIGHT_MAP.clear()
        self.RGB_BUG_LIGHTS.clear()
        
        if not hasattr(self, 'RGB_LIGHTS'):
            self.RGB_LIGHTS = set()
        else:
            self.RGB_LIGHTS.clear()
        
        self.LIGHT_ICONS.clear()
        self._frontend_controls.clear()

        logger.debug("=== LOADING ALL CONTROLS WITH ORDER ===")

        # ====================== LIGHTS (PWM + RGB) ======================
        if self.config.has_section('lights'):
            for name, line in self.config.items('lights'):
                parts = [p.strip() for p in str(line).split('|')]
                if len(parts) < 4:
                    logger.warning(f"Invalid light: {name}")
                    continue

                friendly = parts[0]
                light_type = parts[1].lower()
                icon = parts[-2] if len(parts) > 2 and parts[-2].startswith('fa-') else "fa-lightbulb"
                try:
                    order = int(parts[-1])
                except:
                    order = 999

                self.LIGHT_ICONS[name] = icon

                if light_type == "pwm":
                    try:
                        pin = int(parts[2])
                        self.LIGHT_MAP[name] = pin
                        self._frontend_controls.append({
                            "name": name,
                            "label": friendly,
                            "type": "dimmer",
                            "icon": icon,
                            "has_mode": False,
                            "order": order
                        })
                        logger.debug(f"✓ PWM: {name} | order {order}")
                    except:
                        logger.error(f"Bad PWM pin for {name}")

                elif light_type == "rgb_bug":
                    try:
                        if len(parts) < 5:
                            continue
                        self.RGB_BUG_LIGHTS[name] = {
                            "white": int(parts[2]),
                            "red":   int(parts[3]),
                            "green": int(parts[4])
                        }
                        self.RGB_LIGHTS.add(name)
                        self._frontend_controls.append({
                            "name": name,
                            "label": friendly,
                            "type": "dimmer",
                            "icon": icon,
                            "has_mode": True,
                            "order": order
                        })
                        logger.debug(f"✓ RGB: {name} | order {order}")
                    except Exception as e:
                        logger.error(f"RGB parse error {name}: {e}")

        # ====================== RELAYS ======================
        if self.config.has_section('gpio'):
            for name, line in self.config.items('gpio'):
                parts = [p.strip() for p in str(line).split('|')]
                if len(parts) < 5 or line.strip().startswith('#'):
                    continue

                friendly = parts[0]
                icon = parts[4] if len(parts) > 4 and parts[4].startswith('fa-') else "fa-lightbulb"
                try:
                    order = int(parts[5])
                except:
                    order = 999

                self._frontend_controls.append({
                    "name": name,
                    "label": friendly,
                    "type": "relay",
                    "icon": icon,
                    "has_mode": False,
                    "order": order
                })
                logger.debug(f"✓ Relay: {name} | order {order}")

        self._frontend_controls.sort(key=lambda x: x['order'])

    # ====================== FRONTEND ======================
    def get_frontend_config(self):
        """Return single unified list in user-defined order"""
        return self._frontend_controls

    # ====================== REST OF THE CLASS (unchanged) ======================
    def init_serial(self) -> bool:
        ports = [p.strip() for p in self.config.get('arduino', 'serial_ports').split(',')]
        baud_rate = self.config.getint('arduino', 'baud_rate')
        init_delay = self.config.getfloat('arduino', 'init_delay')

        for port in ports:
            if os.path.exists(port):
                try:
                    self.ser = serial.Serial(port, baud_rate, timeout=self.config.getfloat('arduino', 'timeout'))
                    time.sleep(init_delay)
                    self.ser.reset_input_buffer()
                    logger.info(f"📟 Arduino initialized on {port}")
                    return True
                except Exception as e:
                    logger.error(f"❌ Failed to open {port}: {e}")
        
        logger.warning("⚠️ No Arduino hardware found")
        return False

    def send_command(self, cmd: str) -> str | None:
        if not self.ser or not self.ser.is_open:
            return None

        with self.serial_lock:
            try:
                self.ser.reset_input_buffer()
                self.ser.write((cmd + '\n').encode('utf-8'))
                self.ser.flush()
                time.sleep(self.COMMAND_DELAY)

                if self.ser.in_waiting:
                    response = self.ser.readline().decode('utf-8').strip()
                    if response:
                        return response

                time.sleep(self.RESPONSE_DELAY)
                if self.ser.in_waiting:
                    response = self.ser.readline().decode('utf-8').strip()
                    if response:
                        return response

            except Exception as e:
                logger.error(f"Serial error sending '{cmd}': {e}")
                try:
                    self.ser.reset_input_buffer()
                except:
                    pass
        return None

    def should_ignore_for_optimistic(self, name: str) -> bool:
        if name in self.OPTIMISTIC_LOCK:
            if time.time() < self.OPTIMISTIC_LOCK[name]:
                return True
            else:
                self.OPTIMISTIC_LOCK.pop(name, None)
        return False

    def read_all_states(self):
        if not self.ser or not self.ser.is_open:
            return

        for name, pin in self.LIGHT_MAP.items():
            if self.should_ignore_for_optimistic(name):
                continue
            resp = self.send_command(f"GET {pin}")
            if resp and resp.startswith("VALUE"):
                try:
                    pwm = int(resp.split()[2])
                    self.state[name] = round(pwm / 2.55)
                except:
                    pass

        for name, pins in self.RGB_BUG_LIGHTS.items():
            if self.should_ignore_for_optimistic(name):
                continue
            try:
                red_resp = self.send_command(f"GET {pins['red']}")
                white_resp = self.send_command(f"GET {pins['white']}")
                red_pwm = int(red_resp.split()[2]) if red_resp and red_resp.startswith("VALUE") else 0
                white_pwm = int(white_resp.split()[2]) if white_resp and white_resp.startswith("VALUE") else 0

                if red_pwm > white_pwm:
                    self.state[name] = round(red_pwm / 2.55)
                    self.state[f"{name}_mode"] = "red"
                else:
                    self.state[name] = round(white_pwm / 2.55)
                    self.state[f"{name}_mode"] = "white"
            except:
                pass

    def set_rgb_bug_light(self, name: str, brightness: int, mode: str = 'white') -> bool:
        config = self.RGB_BUG_LIGHTS.get(name)
        if not config:
            return False

        pwm = int(brightness * 2.55)
        if mode == 'red':
            self.send_command(f"RAMP {config['white']} 0 {self.RGB_RED_SWITCH_RAMP}")
            self.send_command(f"RAMP {config['red']} {pwm} {self.RGB_MODE_SWITCH_RAMP}")
            self.send_command(f"RAMP {config['green']} {int(pwm * 0.05)} {self.RGB_MODE_SWITCH_RAMP}")
        else:
            self.send_command(f"RAMP {config['white']} {pwm} {self.RGB_MODE_SWITCH_RAMP}")
            self.send_command(f"RAMP {config['red']} 0 {self.RGB_RED_SWITCH_RAMP}")
            self.send_command(f"RAMP {config['green']} 0 {self.RGB_RED_SWITCH_RAMP}")

        self.OPTIMISTIC_LOCK[name] = time.time() + self.OPTIMISTIC_LOCK_DURATION
        return True

    def cleanup(self):
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception as e:
                logger.error(f"Error closing serial: {e}")

    def is_connected(self) -> bool:
        """Return True if serial port is open and ready."""
        return bool(self.ser and getattr(self.ser, "is_open", False))
