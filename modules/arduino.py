# modules.arduino.py
import serial
import time
import threading
import logging

logger = logging.getLogger(__name__)

class ArduinoController:
    def __init__(self, port='/dev/ttyACM0', baudrate=500000, on_event=None):
        self.lock = threading.Lock()  # Add this lock
        try:
            self.ser = serial.Serial(port, baudrate, timeout=1)
            time.sleep(2)  # Wait for Arduino to initialize
            logger.info(f"Arduino serial initialized on {port} at {baudrate}")
        except Exception as e:
            logger.error(f"Failed to initialize Arduino serial: {e}")
            raise
        self.on_event = on_event or (lambda event, data: None)
        self.previous_failed = False

    def start(self):
        logger.info("Starting Arduino health thread")
        threading.Thread(target=self._health_thread, daemon=True).start()

    def _health_thread(self):
        while True:
            failed = False
            try:
                self.get_pwm(2)
            except Exception as e:
                failed = True
                logger.error(f"Arduino health check failed: {e}")
            if failed != self.previous_failed:
                if failed:
                    self.on_event('show_toast', {'message': 'Arduino disconnected', 'type': 'warning'})
                    logger.warning("Arduino disconnected")
                else:
                    self.on_event('show_toast', {'message': 'Arduino reconnected', 'type': 'message'})
                    logger.info("Arduino reconnected")
                self.previous_failed = failed
            time.sleep(60)

    def set_pwm(self, pin, value):
        if not 0 <= value <= 255:
            logger.warning(f"Invalid PWM value {value} for pin {pin}")
            return
        cmd = f"SET {pin} {value}\n"
        with self.lock:  # Add lock here
            try:
                self.ser.reset_input_buffer()
                self.ser.write(cmd.encode())
                logger.debug(f"Set PWM on pin {pin} to {value}")
            except Exception as e:
                logger.error(f"Error setting PWM on pin {pin}: {e}")

    def ramp_pwm(self, pin, value, duration_ms):
        if not 0 <= value <= 255 or duration_ms <= 0:
            logger.warning(f"Invalid ramp PWM: value {value}, duration {duration_ms} for pin {pin}")
            return
        cmd = f"RAMP {pin} {value} {int(duration_ms)}\n"
        with self.lock:  # Add lock here
            try:
                self.ser.reset_input_buffer()
                self.ser.write(cmd.encode())
                logger.debug(f"Ramp PWM on pin {pin} to {value} over {duration_ms}ms")
            except Exception as e:
                logger.error(f"Error ramping PWM on pin {pin}: {e}")

    def get_pwm(self, pin):
        cmd = f"GET {pin}\n"
        with self.lock:  # Add lock here
            try:
                self.ser.reset_input_buffer()
                self.ser.write(cmd.encode())
                time.sleep(0.2)
                while self.ser.in_waiting > 0:
                    response = self.ser.readline().decode().strip()
                    if response.startswith("VALUE "):
                        parts = response.split()
                        if len(parts) == 3 and int(parts[1]) == pin:
                            return int(parts[2])
                logger.warning(f"Failed to get PWM for pin {pin}")
                return None
            except Exception as e:
                logger.error(f"Error getting PWM for pin {pin}: {e}")
                return None

    def get_analog(self, pin):
        cmd = f"ANALOG {pin}\n"
        with self.lock:
            try:
                self.ser.reset_input_buffer()
                self.ser.write(cmd.encode())
                self.ser.flush()
                response = self.ser.readline().decode().strip()
                if response.startswith("ANALOG "):
                    parts = response.split()
                    if len(parts) == 3 and int(parts[1]) == pin:
                        return float(parts[2])
                logger.warning(f"Failed to get analog for pin {pin}")
                return None
            except Exception as e:
                logger.error(f"Error getting analog for pin {pin}: {e}")
                return None

    def get_vcc(self):
        cmd = f"GETVCC\n"
        with self.lock:
            try:
                self.ser.reset_input_buffer()
                self.ser.write(cmd.encode())
                self.ser.flush()
                response = self.ser.readline().decode().strip()
                if response.startswith("VCC "):
                    parts = response.split()
                    if len(parts) == 2:
                        return int(parts[1])
                # Optional: Clear any extra data if mismatched
                self.ser.reset_input_buffer()
                logger.warning("Failed to get VCC")
                return None
            except Exception as e:
                logger.error(f"Error getting VCC: {e}")
                return None
                
    def get_all_analogs_and_vcc(self):
        cmd = "GETALL\n"
        with self.lock:
            try:
                self.ser.reset_input_buffer()
                self.ser.write(cmd.encode())
                self.ser.flush()
                response = self.ser.readline().decode().strip()
                if response.startswith("ALL "):
                    parts = response.split()
                    if len(parts) == 5:
                        vcc = int(parts[1]) if parts[1].isdigit() else None
                        a0 = float(parts[2]) if '.' in parts[2] else None
                        a1 = float(parts[3]) if '.' in parts[3] else None
                        a2 = float(parts[4]) if '.' in parts[4] else None
                        return vcc, a0, a1, a2
                # If response doesn't match, fall back to individual calls as a safety net
                logger.warning("Failed to get all via GETALL; falling back to individual reads")
                vcc = self.get_vcc()
                a0 = self.get_analog(0)
                a1 = self.get_analog(1)
                a2 = self.get_analog(2)
                return vcc, a0, a1, a2
            except Exception as e:
                logger.error(f"Error getting all analogs and VCC: {e}")
                return None, None, None, None