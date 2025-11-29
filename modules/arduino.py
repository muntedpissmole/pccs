# modules.arduino.py
import serial
import time
import threading
import logging

logger = logging.getLogger(__name__)

class ArduinoController:
    def __init__(self, port='/dev/ttyACM0', baudrate=500000, on_event=None):
        self.lock = threading.Lock()
        self.port = port
        self.baudrate = baudrate
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

    def _reconnect(self):
        logger.info("Attempting to reconnect to Arduino...")
        try:
            if self.ser.is_open:
                self.ser.close()
            self.ser = serial.Serial(self.port, self.baudrate, timeout=1)
            time.sleep(2)  # Wait for Arduino reset
            logger.info("Reconnected successfully")
            return True
        except Exception as e:
            logger.error(f"Reconnect failed: {e}")
            return False

    def _health_thread(self):
        reconnect_attempts = 0
        max_attempts = 3
        while True:
            failed = True
            try:
                value = self.get_pwm(2)
                if value is not None:
                    failed = False
            except Exception as e:
                logger.error(f"Arduino health check failed: {e}")
            
            if failed:
                reconnect_attempts += 1
                if reconnect_attempts >= max_attempts:
                    if self._reconnect():
                        reconnect_attempts = 0
                        failed = False
            else:
                reconnect_attempts = 0
            
            if failed != self.previous_failed:
                if failed:
                    self.on_event('show_toast', {'message': 'Arduino disconnected', 'type': 'warning'})
                    logger.warning("Arduino disconnected")
                else:
                    self.on_event('show_toast', {'message': 'Arduino reconnected', 'type': 'message'})
                    logger.info("Arduino reconnected")
                self.previous_failed = failed
            
            time.sleep(30)  # Check every 30 seconds

    def set_pwm(self, pin, value):
        if not 0 <= value <= 255:
            logger.warning(f"Invalid PWM value {value} for pin {pin}")
            return
        cmd = f"SET {pin} {value}\n"
        attempts = 0
        max_attempts = 3
        while attempts < max_attempts:
            with self.lock:
                try:
                    self.ser.reset_input_buffer()
                    self.ser.write(cmd.encode())
                    self.ser.flush()
                    logger.debug(f"Set PWM on pin {pin} to {value}")
                    return
                except Exception as e:
                    logger.error(f"Error setting PWM on pin {pin} (attempt {attempts+1}): {e}")
                    attempts += 1
                    time.sleep(0.5 * attempts)
        logger.error(f"Failed to set PWM on pin {pin} after {max_attempts} attempts")
        self.on_event('show_toast', {'message': 'Failed to communicate with Arduino', 'type': 'error'})

    def ramp_pwm(self, pin, value, duration_ms):
        if not 0 <= value <= 255 or duration_ms <= 0:
            logger.warning(f"Invalid ramp PWM: value {value}, duration {duration_ms} for pin {pin}")
            return
        cmd = f"RAMP {pin} {value} {int(duration_ms)}\n"
        attempts = 0
        max_attempts = 3
        while attempts < max_attempts:
            with self.lock:
                try:
                    self.ser.reset_input_buffer()
                    self.ser.write(cmd.encode())
                    self.ser.flush()
                    logger.debug(f"Ramp PWM on pin {pin} to {value} over {duration_ms}ms")
                    return
                except Exception as e:
                    logger.error(f"Error ramping PWM on pin {pin} (attempt {attempts+1}): {e}")
                    attempts += 1
                    time.sleep(0.5 * attempts)
        logger.error(f"Failed to ramp PWM on pin {pin} after {max_attempts} attempts")
        self.on_event('show_toast', {'message': 'Failed to communicate with Arduino', 'type': 'error'})

    def get_pwm(self, pin):
        cmd = f"GET {pin}\n"
        attempts = 0
        max_attempts = 3
        while attempts < max_attempts:
            with self.lock:
                try:
                    self.ser.reset_input_buffer()
                    self.ser.write(cmd.encode())
                    self.ser.flush()
                    start_time = time.time()
                    while time.time() - start_time < 0.5:
                        if self.ser.in_waiting > 0:
                            response = self.ser.readline().decode().strip()
                            logger.debug(f"Raw response for GET PWM on pin {pin}: {response}")
                            if response.startswith("VALUE "):
                                parts = response.split()
                                if len(parts) == 3 and int(parts[1]) == pin:
                                    return int(parts[2])
                        time.sleep(0.01)
                    logger.warning(f"No response for GET PWM on pin {pin} (attempt {attempts+1})")
                    attempts += 1
                    time.sleep(0.5 * attempts)
                except Exception as e:
                    logger.error(f"Error getting PWM for pin {pin} (attempt {attempts+1}): {e}")
                    attempts += 1
                    time.sleep(0.5 * attempts)
        logger.error(f"Failed to get PWM for pin {pin} after {max_attempts} attempts")
        return None

    def get_analog(self, pin):
        cmd = f"ANALOG {pin}\n"
        attempts = 0
        max_attempts = 3
        while attempts < max_attempts:
            with self.lock:
                try:
                    self.ser.reset_input_buffer()
                    self.ser.write(cmd.encode())
                    self.ser.flush()
                    start_time = time.time()
                    while time.time() - start_time < 0.5:
                        if self.ser.in_waiting > 0:
                            response = self.ser.readline().decode().strip()
                            logger.debug(f"Raw response for ANALOG on pin {pin}: {response}")
                            if response.startswith("ANALOG "):
                                parts = response.split()
                                if len(parts) == 3 and int(parts[1]) == pin:
                                    return float(parts[2])
                        time.sleep(0.01)
                    logger.warning(f"No response for ANALOG on pin {pin} (attempt {attempts+1})")
                    attempts += 1
                    time.sleep(0.5 * attempts)
                except Exception as e:
                    logger.error(f"Error getting analog for pin {pin} (attempt {attempts+1}): {e}")
                    attempts += 1
                    time.sleep(0.5 * attempts)
        logger.error(f"Failed to get analog for pin {pin} after {max_attempts} attempts")
        return None

    def get_vcc(self):
        cmd = f"GETVCC\n"
        attempts = 0
        max_attempts = 3
        while attempts < max_attempts:
            with self.lock:
                try:
                    self.ser.reset_input_buffer()
                    self.ser.write(cmd.encode())
                    self.ser.flush()
                    start_time = time.time()
                    while time.time() - start_time < 0.5:
                        if self.ser.in_waiting > 0:
                            response = self.ser.readline().decode().strip()
                            logger.debug(f"Raw response for GETVCC: {response}")
                            if response.startswith("VCC "):
                                parts = response.split()
                                if len(parts) == 2:
                                    return int(parts[1])
                        time.sleep(0.01)
                    self.ser.reset_input_buffer()  # Clear any extra data
                    logger.warning(f"No response for GETVCC (attempt {attempts+1})")
                    attempts += 1
                    time.sleep(0.5 * attempts)
                except Exception as e:
                    logger.error(f"Error getting VCC (attempt {attempts+1}): {e}")
                    attempts += 1
                    time.sleep(0.5 * attempts)
        logger.error(f"Failed to get VCC after {max_attempts} attempts")
        return None

    def get_all_analogs_and_vcc(self):
        cmd = "GETALL\n"
        attempts = 0
        max_attempts = 3
        while attempts < max_attempts:
            with self.lock:
                try:
                    self.ser.reset_input_buffer()
                    self.ser.write(cmd.encode())
                    self.ser.flush()
                    start_time = time.time()
                    while time.time() - start_time < 0.5:
                        if self.ser.in_waiting > 0:
                            response = self.ser.readline().decode().strip()
                            logger.debug(f"Raw response for GETALL: {response}")
                            if response.startswith("ALL "):
                                parts = response.split()
                                if len(parts) == 5:
                                    vcc = int(parts[1]) if parts[1].isdigit() else None
                                    a0 = float(parts[2]) if '.' in parts[2] else None
                                    a1 = float(parts[3]) if '.' in parts[3] else None
                                    a2 = float(parts[4]) if '.' in parts[4] else None
                                    return vcc, a0, a1, a2
                        time.sleep(0.01)
                    logger.warning(f"Failed to get all via GETALL (attempt {attempts+1}); falling back to individual reads")
                    vcc = self.get_vcc()
                    a0 = self.get_analog(0)
                    a1 = self.get_analog(1)
                    a2 = self.get_analog(2)
                    return vcc, a0, a1, a2
                except Exception as e:
                    logger.error(f"Error getting all analogs and VCC (attempt {attempts+1}): {e}")
                    attempts += 1
                    time.sleep(0.5 * attempts)
        logger.error(f"Failed to get all analogs and VCC after {max_attempts} attempts")
        return None, None, None, None