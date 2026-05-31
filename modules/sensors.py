# modules/sensors.py
import threading
import time
import logging
import glob
import os

logger = logging.getLogger("pccs")
logger.propagate = True


class SensorManager:
    def __init__(self, config, send_command_func, socketio):
        self.config = config
        self.send_command = send_command_func
        self.socketio = socketio
        self.running = False
        self.thread = None

        os.system('modprobe w1-gpio')
        os.system('modprobe w1-therm')
        time.sleep(0.5)

        # ====================== CALIBRATION FROM CONFIG ======================
        self.WATER_R_EMPTY = config.getfloat('sensors', 'water_resistance_empty')
        self.WATER_R_FULL = config.getfloat('sensors', 'water_resistance_full')

        # Analog pin for water level sensor (via Arduino)
        self.WATER_PIN = config.getint('arduino analog', 'water_pin')

        # 1-Wire DS18B20 sensor IDs (folder names under /sys/bus/w1/devices/, e.g. "28-3ce1d4435d5a")
        # Leave blank to auto-detect first available 28* device.
        self.OUTSIDE_TEMP_ID = (config.get('sensors', 'outside_temp_sensor', fallback='') or '').strip() or None
        self.FRIDGE_TEMP_ID  = (config.get('sensors', 'fridge_temp_sensor', fallback='') or '').strip() or None
        # ========================================================

        outside_mode = "auto" if not self.OUTSIDE_TEMP_ID else "configured"
        fridge_mode = "configured" if self.FRIDGE_TEMP_ID else "not configured"
        logger.info("🔋 SensorManager initialized (water + 1-wire temps only — solar CT + battery voltage divider fully removed: outside=%s, fridge=%s)",
                    outside_mode, fridge_mode)

    def _read_ds18b20(self, sensor_id=None):
        """Read DS18B20. If sensor_id given (e.g. '28-xxx'), read that exact device; else first 28* found."""
        try:
            base_dir = '/sys/bus/w1/devices/'

            if sensor_id:
                device_folder = os.path.join(base_dir, sensor_id)
                if not os.path.isdir(device_folder):
                    logger.warning("   🌡️ Configured 1-Wire sensor not present: %s", sensor_id)
                    return None
                device_folders = [device_folder]
            else:
                device_folders = glob.glob(base_dir + '28*')
                if not device_folders:
                    logger.warning("No 1-Wire DS18B20 sensor found")
                    return None

            device_file = device_folders[0] + '/w1_slave'
            sensor_name = device_folders[0].split('/')[-1]
            logger.debug("   🌡️ Reading sensor: %s", sensor_name)
            
            # Read twice for reliability
            for i in range(2):
                with open(device_file, 'r') as f:
                    lines = f.readlines()
                
                if len(lines) < 2:
                    time.sleep(0.2)
                    continue
                    
                if "YES" not in lines[0]:
                    logger.warning("   🌡️ CRC check failed, retrying...")
                    time.sleep(0.25)
                    continue
                
                equals_pos = lines[1].find('t=')
                if equals_pos != -1:
                    temp_string = lines[1][equals_pos + 2:].strip()
                    temp_c = float(temp_string) / 1000.0
                    
                    if temp_c == 85.0:
                        logger.info("   🌡️ Sensor returned power-on reset value (85°C) — invalid")
                        time.sleep(0.3)
                        continue
                    if abs(temp_c) < 0.1:
                        logger.warning("   🌡️ Sensor returned near-zero — possibly bad read")
                        time.sleep(0.3)
                        continue
                        
                    logger.debug("   🌡️ Temperature = %.1f°C [%s]", temp_c, sensor_name)
                    return round(temp_c, 1)

            logger.error("   ⚠️ DS18B20 read failed after retries [%s]", sensor_name)
            return None

        except Exception as e:
            logger.error("DS18B20 read error: %s", e)
            return None

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        
        logger.debug("✅ SensorManager started")
        
        time.sleep(0.5)
        self.update_sensors()

    def _read_analog(self, pin):
        for attempt in range(3):
            resp = self.send_command(f"ANALOG {pin}")
            if resp and resp.startswith("ANALOG"):
                try:
                    value = float(resp.split()[2])
                    logger.debug("   ADC A%d = %.1f", pin, value)
                    return value
                except:
                    pass
            time.sleep(0.05)
        logger.warning("   ⚠️ Failed to read ANALOG %d", pin)
        return None

    def _read_vcc(self):
        resp = self.send_command("GETVCC")
        if resp and resp.startswith("VCC"):
            try:
                v = float(resp.split()[1]) / 1000.0
                logger.debug("   VCC = %.3fV", v)
                return v
            except:
                pass
        logger.warning("   ⚠️ Failed to read VCC")
        return 5.0

    def _calculate_water(self, adc, vcc):
        if adc is None or vcc is None:
            return 0
        v_a1 = adc * vcc / 1023.0
        if abs(vcc - v_a1) < 0.02:
            return 0
        sensor_r = 100 * v_a1 / (vcc - v_a1)
        pct = (self.WATER_R_EMPTY - sensor_r) / (self.WATER_R_EMPTY - self.WATER_R_FULL) * 100
        return round(max(0, min(100, pct)))

    def update_sensors(self):
        logger.debug("🔄 Updating sensors (water + temperature)...")
        
        adc_water   = self._read_analog(self.WATER_PIN)
        vcc         = self._read_vcc()
        outside_temp = self._read_ds18b20(self.OUTSIDE_TEMP_ID)
        fridge_temp  = self._read_ds18b20(self.FRIDGE_TEMP_ID) if self.FRIDGE_TEMP_ID else None

        water_pct = self._calculate_water(adc_water, vcc)

        sensor_data = {
            "water_percent": water_pct,
            "temp_c": outside_temp if outside_temp is not None else None,  # legacy key
            "outside_temp_c": outside_temp,
            "fridge_temp_c": fridge_temp,
            "temp_valid": outside_temp is not None
        }

        logger.debug("📤 Emitting sensor data: %s", sensor_data)
        self.socketio.emit('sensor_update', sensor_data)

    def _loop(self):
        while self.running:
            try:
                self.update_sensors()
            except Exception as e:
                logger.error("❌ Sensor loop error: %s", e)
            time.sleep(self.config.getfloat('sensors', 'update_interval', fallback=5.0))

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)