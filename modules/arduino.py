# modules/arduino.py
import serial
import threading
import time
import os
import logging

logger = logging.getLogger("pccs")


class ArduinoManager:
    def __init__(self):
        self.ser = None
        self.serial_lock = threading.Lock()
        self.state = {}

        # Optimistic UI locking (prevents fighting slider drags)
        self.OPTIMISTIC_LOCK: dict[str, float] = {}
        self.OPTIMISTIC_LOCK_DURATION = 2.5

        self.LIGHT_MAP = {
            "kitchen_bench": 5,
            "storage_panel": 6,
            "rear_drawer": 7,
            "accent": 8,
            "rooftop_tent": 12,
            "ensuite": 13,
        }

        self.RGB_BUG_LIGHTS = {
            "kitchen_panel": {"red": 3, "green": 4},
            "awning": {"red": 10, "green": 11}
        }

        self.RGB_LIGHTS = set(self.RGB_BUG_LIGHTS.keys())

    def init_serial(self) -> bool:
        """Try common ports and initialize Arduino"""
        ports = ['/dev/ttyACM0', '/dev/ttyUSB0', '/dev/serial0', '/dev/ttyAMA0']
        for port in ports:
            if os.path.exists(port):
                try:
                    self.ser = serial.Serial(port, 500000, timeout=0.5)
                    time.sleep(2.5)
                    self.ser.reset_input_buffer()
                    logger.info(f"💡 Arduino connected on {port}")
                    return True
                except Exception as e:
                    logger.error(f"❌ Failed to open {port}: {e}")
        
        logger.warning("⚠️ No Arduino hardware found")
        return False

    def send_command(self, cmd: str) -> str | None:
        """Thread-safe command with retry"""
        if not self.ser or not self.ser.is_open:
            return None

        with self.serial_lock:
            try:
                self.ser.reset_input_buffer()
                self.ser.write((cmd + '\n').encode('utf-8'))
                self.ser.flush()
                time.sleep(0.08)

                # First read attempt
                if self.ser.in_waiting:
                    response = self.ser.readline().decode('utf-8').strip()
                    if response:
                        return response

                # Second chance
                time.sleep(0.04)
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
        """Skip hardware read if user is currently adjusting this light via UI"""
        if name in self.OPTIMISTIC_LOCK:
            if time.time() < self.OPTIMISTIC_LOCK[name]:
                return True
            else:
                self.OPTIMISTIC_LOCK.pop(name, None)
        return False

    def read_all_states(self):
        """Sync hardware state from Arduino (skipping actively controlled lights)"""
        if not self.ser or not self.ser.is_open:
            logger.warning("⚠️ Serial not available for state read")
            return

        logger.debug("📡 Reading all states from Arduino...")

        # Normal PWM lights
        for name, pin in self.LIGHT_MAP.items():
            if self.should_ignore_for_optimistic(name):
                continue

            resp = self.send_command(f"GET {pin}")
            if resp and resp.startswith("VALUE"):
                try:
                    pwm = int(resp.split()[2])
                    new_val = round(pwm / 2.55)
                    old_val = self.state.get(name, 0)
                    if abs(old_val - new_val) > 3:
                        logger.debug(f"   {name:15} sync: {old_val} → {new_val}")
                        self.state[name] = new_val
                except Exception as e:
                    logger.error(f"   Failed parsing GET for {name}: {e}")

        # RGB bug lights
        for name, config in self.RGB_BUG_LIGHTS.items():
            if self.should_ignore_for_optimistic(name):
                continue

            red_pin = config["red"]
            white_pin = 2 if name == "kitchen_panel" else 9

            red_resp = self.send_command(f"GET {red_pin}")
            white_resp = self.send_command(f"GET {white_pin}")

            red_pwm = int(red_resp.split()[2]) if red_resp and red_resp.startswith("VALUE") else 0
            white_pwm = int(white_resp.split()[2]) if white_resp and white_resp.startswith("VALUE") else 0

            if red_pwm > white_pwm:
                brightness = round(red_pwm / 2.55)
                mode = "red"
            else:
                brightness = round(white_pwm / 2.55)
                mode = "white"

            old_brightness = self.state.get(name, 0)
            old_mode = self.state.get(f"{name}_mode")

            if abs(old_brightness - brightness) > 3 or old_mode != mode:
                logger.debug(f"   {name:15} sync: {brightness}% {mode}")

            self.state[name] = brightness
            self.state[f"{name}_mode"] = mode

    def set_rgb_bug_light(self, name: str, brightness: int, mode: str = 'white') -> bool:
        """Set RGB bug light with proper mode switching"""
        config = self.RGB_BUG_LIGHTS.get(name)
        if not config:
            logger.warning(f"Unknown RGB light: {name}")
            return False

        pwm = int(brightness * 2.55)
        white_pin = 2 if name == "kitchen_panel" else 9

        if mode == 'red':
            self.send_command(f"RAMP {white_pin} 0 180")
            self.send_command(f"RAMP {config['red']} {pwm} 250")
            self.send_command(f"RAMP {config['green']} {int(pwm * 0.05)} 250")
        else:
            self.send_command(f"RAMP {white_pin} {pwm} 250")
            self.send_command(f"RAMP {config['red']} 0 180")
            self.send_command(f"RAMP {config['green']} 0 180")

        # Set optimistic lock
        self.OPTIMISTIC_LOCK[name] = time.time() + self.OPTIMISTIC_LOCK_DURATION
        return True

    def cleanup(self):
        """Close serial connection"""
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
                logger.debug("Arduino serial port closed")
            except Exception as e:
                logger.error(f"Error closing Arduino serial: {e}")