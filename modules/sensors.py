# modules/sensors.py
import threading
import time
import logging
import glob
import os

logger = logging.getLogger(__name__)
logger.propagate = True


class SensorManager:
    def __init__(self, send_command_func, socketio):
        self.send_command = send_command_func
        self.socketio = socketio
        self.running = False
        self.thread = None

        # Enable 1-Wire (safe to call multiple times)
        os.system('modprobe w1-gpio')
        os.system('modprobe w1-therm')
        time.sleep(0.5)  # Give kernel time to detect sensor

        # ====================== CALIBRATION ======================
        self.BATTERY_DIVIDER = 4.675
        self.BATTERY_FULL_V = 13.4
        self.BATTERY_EMPTY_V = 10.2

        self.WATER_R_EMPTY = 240
        self.WATER_R_FULL = 33

        self.SOLAR_ZERO_OFFSET = 2.5326
        self.SOLAR_SENSITIVITY = 0.0125
        self.SOLAR_NOMINAL_V = 13.8
        # ========================================================

        logger.info("📡 SensorManager initialized (battery/water/solar + DS18B20)")

    def _read_ds18b20(self):
        """Read DS18B20 with clear debugging"""
        try:
            base_dir = '/sys/bus/w1/devices/'
            device_folders = glob.glob(base_dir + '28*')
            
            if not device_folders:
                logger.warning("No 1-Wire DS18B20 sensor found")
                return None

            device_file = device_folders[0] + '/w1_slave'
            logger.debug("   🌡️ Reading sensor: %s", device_folders[0].split('/')[-1])
            
            # Read twice for reliability (first read can be stale)
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
                        
                    logger.debug("   🌡️ Temperature = %.1f°C", temp_c)
                    return round(temp_c, 1)

            logger.error("   ⚠️ DS18B20 read failed after retries")
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
        
        logger.info("✅ SensorManager started")
        
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

    # === Calculation methods (same as before) ===
    def _calculate_battery(self, adc, vcc):
        if adc is None or vcc is None:
            return 0.0, 0
        v_a0 = adc * vcc / 1023.0
        voltage = round(v_a0 * self.BATTERY_DIVIDER, 2)
        soc = self._voltage_to_soc(voltage)
        return voltage, soc

    def _voltage_to_soc(self, voltage):
        soc_table = [
                (10.2, 0),
                (11.8, 5),
                (12.4, 10),
                (12.7, 20),
                (12.9, 30),
                (13.0, 40),
                (13.05, 50),
                (13.10, 60),
                (13.15, 70),
                (13.20, 80),
                (13.30, 90),
                (13.40, 100)
            ]
        if voltage <= soc_table[0][0]:
            return 0
        if voltage >= soc_table[-1][0]:
            return 100
        for i in range(len(soc_table) - 1):
            v1, s1 = soc_table[i]
            v2, s2 = soc_table[i + 1]
            if v1 <= voltage < v2:
                return round(s1 + (s2 - s1) * (voltage - v1) / (v2 - v1))
        return 100

    def _calculate_water(self, adc, vcc):
        if adc is None or vcc is None:
            return 0
        v_a1 = adc * vcc / 1023.0
        if abs(vcc - v_a1) < 0.02:
            return 0
        sensor_r = 100 * v_a1 / (vcc - v_a1)
        pct = (self.WATER_R_EMPTY - sensor_r) / (self.WATER_R_EMPTY - self.WATER_R_FULL) * 100
        return round(max(0, min(100, pct)))

    def _calculate_solar_current(self, adc, vcc):
        if adc is None:
            return 0.0
        v_a2 = adc * (vcc or 5.0) / 1023.0
        current = (v_a2 - self.SOLAR_ZERO_OFFSET) / self.SOLAR_SENSITIVITY
        return max(0.0, round(current, 1))

    def update_sensors(self):
        logger.info("🔄 Updating sensors...")
        
        adc_battery = self._read_analog(0)
        adc_water   = self._read_analog(1)
        adc_solar   = self._read_analog(2)   # Solar CT
        vcc         = self._read_vcc()
        temp_c      = self._read_ds18b20()

        battery_v, battery_pct = self._calculate_battery(adc_battery, vcc)
        water_pct = self._calculate_water(adc_water, vcc)
        solar_a   = self._calculate_solar_current(adc_solar, vcc)
        solar_kw  = round(solar_a * self.SOLAR_NOMINAL_V / 1000.0, 1)

        sensor_data = {
                    "battery_voltage": battery_v,
                    "battery_charge": battery_pct,
                    "water_percent": water_pct,
                    "solar_kw": solar_kw,
                    "solar_a": solar_a,
                    "temp_c": temp_c if temp_c is not None else None,
                    "temp_valid": temp_c is not None
                }

        logger.debug("📤 Emitting sensor data: %s", sensor_data)
        self.socketio.emit('sensor_update', sensor_data)

    def _loop(self):
        while self.running:
            try:
                self.update_sensors()
            except Exception as e:
                logger.error("❌ Sensor loop error: %s", e)
            time.sleep(5)

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)