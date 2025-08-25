from flask import Flask, render_template, request, jsonify
from logging.handlers import RotatingFileHandler
import lgpio
import json
import time
import logging
import atexit
import serial
import pynmea2
from astral.sun import sun
from astral import LocationInfo
from datetime import datetime, date, timedelta, time as dt_time
import pytz
import subprocess
import threading
import timezonefinder

# Global serial lock
serial_lock = threading.Lock()
import os
from w1thermsensor import W1ThermSensor, NoSensorFoundError, SensorNotReadyError
import tempfile
from collections import defaultdict

app = Flask(__name__)

# Setup logging with rotation
log_dir = 'log'
if not os.path.exists(log_dir):
    os.makedirs(log_dir, exist_ok=True)
file_handler = RotatingFileHandler(
    os.path.join(log_dir, 'app.log'),
    maxBytes=1_000_000,
    backupCount=5
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(), file_handler]
)

# Global GPIO handle
h = None
gps_lock = threading.Lock()

# GPS setup
try:
    ser = serial.Serial("/dev/ttyAMA0", baudrate=9600, timeout=5)
    logging.info("Initialized GPS serial connection")
except Exception as e:
    logging.error(f"Error initializing GPS: {e}")
    ser = None

# Serial setup for Arduino
ser_arduino = None
arduino_available = False

def init_serial():
    global ser_arduino, arduino_available
    if ser_arduino is not None:
        try:
            ser_arduino.close()
        except Exception as e:
            logging.warning(f"Error closing existing serial: {e}")
        ser_arduino = None
    try:
        ser_arduino = serial.Serial('/dev/ttyACM0', 500000, timeout=2)  # Increased timeout
        time.sleep(2)  # Wait for Arduino reset
        ser_arduino.flushInput()
        ser_arduino.flushOutput()
        # Test ping
        ser_arduino.write(b'P\n')
        response = ser_arduino.readline().decode().strip()
        if response == 'AA':
            logging.info("Initialized USB Serial and confirmed Arduino")
            arduino_available = True
            return True
        else:
            logging.error(f"Serial init failed: ping response {response}")
            ser_arduino.close()
            ser_arduino = None
            return False
    except Exception as e:
        logging.error(f"Serial init failed: {e}")
        if ser_arduino is not None:
            try:
                ser_arduino.close()
            except:
                pass
            ser_arduino = None
        return False

# Sensor caches
last_battery_voltage = last_battery_voltage_time = None
last_tank_level = last_tank_level_time = None
last_temperature = last_temperature_time = None
last_solar_current = last_solar_time = None
last_battery_current = last_battery_time = None
CACHE_DURATION = 10
CACHE_CURRENT = 2

# Calibrated normalized offsets (from zero-current measurements)
SOLAR_OFFSET_NORM = 538 / 1023.0  # ≈0.5259 from your log with CT disconnected
BATTERY_OFFSET_NORM = 0.5  # Temporary; calibrate when connected by removing CT from cable and using raw/1023.0

# Normalized sensitivity (span_norm / rated_current)
SPAN_NORM = 0.625 / 5.0  # 0.125 (normalized span for ±0.625V at 5V nominal)
SOLAR_SENS_NORM = SPAN_NORM / 50  # 0.0025 per A for 50A model
BATTERY_SENS_NORM = SPAN_NORM / 200  # 0.000625 per A for 200A model

def write_config_atomically(config_data, config_path):
    logging.debug(f"Writing to {config_path}")
    try:
        with tempfile.NamedTemporaryFile('w', dir=os.path.dirname(config_path), delete=False) as temp_file:
            json.dump(config_data, temp_file, indent=4)
            temp_file_path = temp_file.name
        os.replace(temp_file_path, config_path)
        logging.debug(f"Atomically wrote config to {config_path}")
    except Exception as e:
        logging.error(f"Error writing config to {config_path}: {e}")
        if 'temp_file_path' in locals() and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise

def send_ssh_display_command(display_pi_user, display_pi_ip, ssh_key, command, action_desc, brightness_value=None):
    try:
        cmd = ["ssh", "-i", ssh_key, f"{display_pi_user}@{display_pi_ip}"]
        if command[0] == "xdotool":
            cmd.append("DISPLAY=:0 " + " ".join(command))
        else:
            cmd.append(" ".join(command))
        logging.debug(f"Executing SSH command: {' '.join(cmd)}")
        result = subprocess.run(
            cmd, check=True, timeout=20, capture_output=True, text=True
        )
        logging.info(f"Successfully sent {action_desc} command to display-pi: {result.stdout.strip()}")
        if brightness_value is not None:
            ssh_command = f"echo {brightness_value} | sudo tee /sys/class/backlight/*/brightness"
            logging.debug(f"Executing brightness SSH command: {ssh_command}")
            result = subprocess.run(
                ["ssh", "-i", ssh_key, f"{display_pi_user}@{display_pi_ip}", ssh_command],
                check=True, timeout=20, capture_output=True, text=True
            )
            logging.info(f"Restored brightness to {brightness_value}: {result.stdout.strip()}")
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        error_msg = e.stderr.strip() if hasattr(e, 'stderr') and e.stderr else str(e)
        logging.error(f"Failed to send {action_desc} command to display-pi: {error_msg}")
        if command[0] in ["xset", "xdotool"]:
            fallback_value = 0 if command[0] == "xset" and command[-1] == "off" else (brightness_value if brightness_value else 127)
            logging.info(f"Attempting fallback: set backlight to {fallback_value}")
            try:
                ssh_command = f"echo {fallback_value} | sudo tee /sys/class/backlight/*/brightness"
                result = subprocess.run(
                    ["ssh", "-i", ssh_key, f"{display_pi_user}@{display_pi_ip}", ssh_command],
                    check=True, timeout=20, capture_output=True, text=True
                )
                logging.info(f"Fallback succeeded: set backlight to {fallback_value}")
                return True
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                logging.error(f"Fallback failed: {e}")
        return False

def init_gpio():
    global h
    try:
        h = lgpio.gpiochip_open(0)
        logging.info("Initialized GPIO chip")
        reed_switch_pins = [int(pin) for pin in config['reed_switches'].keys()]
        for pin in reed_switch_pins:
            lgpio.gpio_claim_input(h, pin, lgpio.SET_PULL_UP)
            logging.debug(f"Configured GPIO pin {pin} as input")
        relay_pins = [int(pin) for pin in config['channels']['relays'].keys()]
        for pin in relay_pins:
            lgpio.gpio_claim_output(h, pin, 1)
            logging.debug(f"Configured GPIO pin {pin} as output")
        relay_states = load_relay_states()
        for pin, state in relay_states.items():
            if pin in config['channels']['relays']:
                lgpio.gpio_write(h, int(pin), 0 if state == 1 else 1)
                logging.debug(f"Restored relay state for pin {pin}")
        atexit.register(cleanup_gpio)
    except Exception as e:
        logging.error(f"Error initializing GPIO: {e}")
        h = None

def cleanup_gpio():
    global h
    if h is not None:
        try:
            reed_switch_pins = [int(pin) for pin in config['reed_switches'].keys()]
            relay_pins = [int(pin) for pin in config['channels']['relays'].keys()]
            for pin in reed_switch_pins + relay_pins:
                lgpio.gpio_free(h, pin)
            lgpio.gpiochip_close(h)
            logging.info("Cleaned up GPIO resources")
        except Exception as e:
            logging.error(f"Error cleaning up GPIO: {e}")
        h = None

def read_arduino_analog(pin):
    if not arduino_available:
        logging.error("Serial not initialized")
        return None
    if not (0 <= pin <= 3):
        logging.error(f"Invalid analog pin: A{pin}")
        return None
    
    retries = 3
    for attempt in range(retries):
        with serial_lock:
            try:
                logging.debug(f"Reading analog pin A{pin}")
                ser_arduino.flushInput()
                ser_arduino.flushOutput()
                time.sleep(0.05)
                
                ser_arduino.write(f'A{pin}\n'.encode())
                response = ser_arduino.readline().decode().strip()
                if response.isdigit():
                    value = int(response)
                    if 0 <= value <= 1023:
                        logging.debug(f"Read analog value from A{pin}: {value} (attempt {attempt+1})")
                        return value
                    else:
                        logging.warning(f"Invalid analog reading on attempt {attempt+1} from pin A{pin}: {value}")
                else:
                    logging.warning(f"Non-digit response on attempt {attempt+1}: {response}")
            except Exception as e:
                logging.warning(f"Error on attempt {attempt+1} reading analog pin A{pin}: {e}")
        
        if attempt < retries - 1:
            time.sleep(0.1)
    
    logging.error(f"Failed to read analog pin A{pin} after {retries} attempts")
    return None

def get_battery_voltage():
    global last_battery_voltage, last_battery_voltage_time
    current_time = time.time()
    if last_battery_voltage is not None and (current_time - last_battery_voltage_time) < CACHE_DURATION:
        return last_battery_voltage
    try:
        raw_value = read_arduino_analog(0)
        if raw_value is None or raw_value < 0 or raw_value > 1023:
            logging.error(f"Invalid ADC reading from A0: {raw_value}")
            last_battery_voltage = None
            last_battery_voltage_time = current_time
            return None
        logging.debug(f"Raw ADC value from A0: {raw_value}")
        norm = raw_value / 1023.0
        if norm < 0.2 or norm > 0.8:
            logging.warning(f"Battery voltage sensor fault: norm={norm:.3f}")
            last_battery_voltage = None
            last_battery_voltage_time = current_time
            return None
        V_REF = 4.765  # Update with your measured rail voltage; consider stabilizing if varies
        a0_voltage = norm * V_REF
        logging.debug(f"Voltage at A0: {a0_voltage:.2f}V")
        SCALING_FACTOR = 13.02 / 2.686  # Keep, assuming divider calibrated at nominal
        battery_voltage = round(a0_voltage * SCALING_FACTOR, 2)
        if battery_voltage < 9.0 or battery_voltage > 15.0:
            logging.warning(f"Battery voltage out of range: {battery_voltage}V")
            last_battery_voltage = None
            last_battery_voltage_time = current_time
            return None
        last_battery_voltage = battery_voltage
        last_battery_voltage_time = current_time
        return battery_voltage
    except Exception as e:
        logging.error(f"Error reading battery voltage: {e}")
        return None

def get_tank_level():
    global last_tank_level, last_tank_level_time
    current_time = time.time()
    if last_tank_level is not None and (current_time - last_tank_level_time) < CACHE_DURATION:
        return last_tank_level
    try:
        raw_value = read_arduino_analog(1)
        if raw_value is None or raw_value < 0 or raw_value > 1023:
            logging.error(f"Invalid ADC reading from A1: {raw_value}")
            last_tank_level = None
            last_tank_level_time = current_time
            return None
        logging.debug(f"Raw ADC value from A1: {raw_value}")
        norm = raw_value / 1023.0
        if norm < 0.1 or norm > 0.6:  # Adjusted for ~0.5-3V /5V
            logging.warning(f"Tank level sensor fault: norm={norm:.3f}")
            last_tank_level = None
            last_tank_level_time = current_time
            return None
        V_REF = 4.765  # Update with measured
        v_out = norm * V_REF
        v_in = V_REF  # Sensor powered by same rail
        r1 = 100.0
        r2 = r1 * v_out / (v_in - v_out) if v_out < v_in else float('inf')
        logging.debug(f"Calculated r2: {r2:.1f}Ω")
        if r2 < 30 or r2 > 250:
            logging.warning(f"Tank level sensor fault: r2={r2:.1f}Ω")
            last_tank_level = None
            last_tank_level_time = current_time
            return None
        r2 = max(33, min(240, r2))
        percentage = round(((240 - r2) / (240 - 33)) * 100)
        percentage = max(0, min(100, percentage))
        logging.debug(f"Tank level percentage: {percentage}%")
        last_tank_level = percentage
        last_tank_level_time = current_time
        return percentage
    except Exception as e:
        logging.error(f"Error reading tank level: {e}")
        return None

def get_solar_current():
    global last_solar_current, last_solar_time
    current_time = time.time()
    if last_solar_current is not None and (current_time - last_solar_time) < CACHE_CURRENT:
        return last_solar_current
    try:
        raw_value = read_arduino_analog(2)
        if raw_value is None or raw_value < 0 or raw_value > 1023:
            logging.error(f"Invalid ADC reading from A2: {raw_value}")
            last_solar_current = None
            last_solar_time = current_time
            return None
        logging.debug(f"Raw ADC value from A2: {raw_value}")
        norm = raw_value / 1023.0
        logging.debug(f"Normalized value at A2: {norm:.3f}")
        if norm < 0.3 or norm > 0.7:
            logging.warning(f"Solar current sensor fault: norm={norm:.3f}")
            last_solar_current = None
            last_solar_time = current_time
            return None
        current = (norm - SOLAR_OFFSET_NORM) / SOLAR_SENS_NORM
        if current < -55 or current > 55:
            logging.warning(f"Solar current out of range: {current:.1f}A")
            last_solar_current = None
            last_solar_time = current_time
            return None
        current = max(0, current)  # Always one way
        last_solar_current = round(current, 1)
        last_solar_time = current_time
        return last_solar_current
    except Exception as e:
        logging.error(f"Error reading solar current: {e}")
        return None

def get_battery_current():
    global last_battery_current, last_battery_time
    current_time = time.time()
    if last_battery_current is not None and (current_time - last_battery_time) < CACHE_CURRENT:
        return last_battery_current
    try:
        raw_value = read_arduino_analog(3)
        if raw_value is None or raw_value < 0 or raw_value > 1023:
            logging.error(f"Invalid ADC reading from A3: {raw_value}")
            last_battery_current = None
            last_battery_time = current_time
            return None
        logging.debug(f"Raw ADC value from A3: {raw_value}")
        norm = raw_value / 1023.0
        logging.debug(f"Normalized value at A3: {norm:.3f}")
        if norm < 0.3 or norm > 0.7:
            logging.warning(f"Battery current sensor fault: norm={norm:.3f}")
            last_battery_current = None
            last_battery_time = current_time
            return None
        current = (norm - BATTERY_OFFSET_NORM) / BATTERY_SENS_NORM
        if abs(current) > 200:
            logging.warning(f"Battery current out of range: {current:.1f}A")
            last_battery_current = None
            last_battery_time = current_time
            return None
        last_battery_current = round(current, 1)
        last_battery_time = current_time
        return last_battery_current
    except Exception as e:
        logging.error(f"Error reading battery current: {e}")
        return None

def get_ds18b20_temperature():
    global last_temperature, last_temperature_time
    current_time = time.time()
    if last_temperature is not None and (current_time - last_temperature_time) < CACHE_DURATION:
        return last_temperature
    try:
        sensor = W1ThermSensor()
        temperature = round(sensor.get_temperature(), 1)
        if temperature < -20.0 or temperature > 80.0:
            logging.warning(f"Temperature out of range: {temperature}°C")
            last_temperature = None
            last_temperature_time = current_time
            return None
        last_temperature = temperature
        last_temperature_time = current_time
        return temperature
    except (NoSensorFoundError, SensorNotReadyError, Exception) as e:
        logging.error(f"Error reading DS18B20: {e}")
        return None

# GPS and sun times
gps_data = {
    "fix": "No",
    "quality": "0 satellites",
    "satellites": 0,
    "latitude": None,
    "longitude": None
}

sun_times_cache = {
    "sunrise": "",
    "sunset": "",
    "last_calculated": None,
    "last_latitude": None,
    "last_longitude": None
}

current_time_cache = {
    "time": "",
    "last_updated": None,
    "fix_obtained": False,
    "using_gps": False
}

gps_timeout_start = None
GPS_TIMEOUT_MINUTES = 5

MELBOURNE_LOCATION = LocationInfo(
    name="Melbourne",
    region="Victoria",
    timezone="Australia/Melbourne",
    latitude=-37.8136,
    longitude=144.9631
)

tf = timezonefinder.TimezoneFinder()

tz_cache = {
    "tz_str": "Australia/Melbourne",
    "last_latitude": None,
    "last_longitude": None
}

def get_local_tz_str():
    global tz_cache
    if gps_data["fix"] == "Yes" and gps_data["latitude"] and gps_data["longitude"]:
        if tz_cache["last_latitude"] is None or abs(gps_data["latitude"] - tz_cache["last_latitude"]) > 0.1 or abs(gps_data["longitude"] - tz_cache["last_longitude"]) > 0.1:
            tz_str = tf.timezone_at(lng=gps_data["longitude"], lat=gps_data["latitude"])
            if tz_str:
                tz_cache["tz_str"] = tz_str
                tz_cache["last_latitude"] = gps_data["latitude"]
                tz_cache["last_longitude"] = gps_data["longitude"]
                logging.info(f"Updated timezone to {tz_str} based on GPS location")
            else:
                logging.warning("Could not determine timezone from GPS, using fallback")
    return tz_cache["tz_str"]

SHUTDOWN_TOKEN = "kzqWazMQIO8YrefrqwEi4cFvM9pCrlCAYG05FLpjgpc"

def set_system_clock(dt):
    try:
        time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        subprocess.run(["sudo", "date", "-s", time_str], check=True)
        logging.info(f"Set system clock to {time_str}")
    except Exception as e:
        logging.error(f"Error setting system clock: {e}")

def save_relay_states(states):
    try:
        with open('config.json', 'r') as f:
            current_config = json.load(f)
        current_config['relay_states'] = states
        write_config_atomically(current_config, 'config.json')
        logging.debug(f"Saved relay states: {states}")
    except Exception as e:
        logging.error(f"Error saving relay states: {e}")

def load_relay_states():
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        return config.get('relay_states', {})
    except Exception as e:
        logging.error(f"Error loading relay states: {e}")
        return {}

def update_gps_data():
    global gps_data, current_time_cache, gps_timeout_start, sun_times_cache
    if ser is None:
        return
    try:
        while True:
            with gps_lock:
                local_tz_str = get_local_tz_str()
                local_tz = pytz.timezone(local_tz_str)
                if not current_time_cache["time"]:
                    system_time = datetime.now(local_tz)
                    current_time_cache["time"] = system_time.strftime("%A %B %d %Y %I:%M %p %Z").lstrip("0").replace(" 0", " ") + "*"
                    current_time_cache["last_updated"] = datetime.now(pytz.UTC)
                    current_time_cache["using_gps"] = False
                if not sun_times_cache["sunrise"]:
                    today = date.today()
                    s = sun(MELBOURNE_LOCATION.observer, date=today, tzinfo=local_tz)
                    sun_times_cache.update({
                        "sunrise": s["sunrise"].strftime("%I:%M %p").lstrip("0") + "*",
                        "sunset": s["sunset"].strftime("%I:%M %p").lstrip("0") + "*",
                        "last_calculated": datetime.now(pytz.UTC),
                        "last_latitude": MELBOURNE_LOCATION.latitude,
                        "last_longitude": MELBOURNE_LOCATION.longitude
                    })
                ser.reset_input_buffer()
                line = ser.readline().decode('ascii', errors='ignore').strip()
                if line and ('$GPGGA' in line or '$GNGGA' in line):
                    try:
                        msg = pynmea2.parse(line)
                        fix_quality = int(msg.data[5])
                        num_sats = int(msg.data[6]) if msg.data[6].isdigit() else 0
                        latitude = msg.latitude
                        longitude = msg.longitude
                        gps_data.update({
                            "fix": "Yes" if fix_quality in (1, 2) else "No",
                            "quality": f"{num_sats} satellites" if fix_quality == 1 else f"Differential ({num_sats} satellites)" if fix_quality == 2 else "0 satellites",
                            "satellites": num_sats,
                            "latitude": latitude,
                            "longitude": longitude
                        })
                        if fix_quality == 0:
                            gps_timeout_start = datetime.now() if gps_timeout_start is None else gps_timeout_start
                        else:
                            gps_timeout_start = None
                            current_time_cache["using_gps"] = True
                        if hasattr(msg, 'timestamp') and msg.timestamp and gps_data["fix"] == "Yes":
                            today = date.today()
                            naive_dt = datetime(
                                year=today.year,
                                month=today.month,
                                day=today.day,
                                hour=msg.timestamp.hour,
                                minute=msg.timestamp.minute
                            )
                            utc_dt = pytz.utc.localize(naive_dt)
                            local_dt = utc_dt.astimezone(local_tz)
                            current_time_cache["time"] = local_dt.strftime("%A %B %d %Y %I:%M %p %Z").lstrip("0").replace(" 0", " ")
                            current_time_cache["last_updated"] = datetime.now(pytz.UTC)
                            if not current_time_cache["fix_obtained"]:
                                current_time_cache["fix_obtained"] = True
                                set_system_clock(local_dt)
                    except pynmea2.ParseError:
                        pass
            time.sleep(1)
    except Exception as e:
        logging.error(f"Error updating GPS data: {e}")

# Load config
config_path = 'config.json'
try:
    if not os.path.exists(config_path):
        default_config = {
            "theme": {
                "darkMode": "off",
                "autoTheme": "off",
                "autoBrightness": "off",
                "defaultTheme": "light",
                "screen_brightness": "medium"
            },
            "channels": {
                "arduino": {},
                "relays": {}
            },
            "scenes": {},
            "reed_switches": {
                "23": {
                    "name": "Kitchen Panel",
                    "type": "sensor",
                    "trigger_channels": ["arduino:1", "arduino:2", "arduino:3"]
                },
                "24": {
                    "name": "Storage Panel",
                    "type": "sensor",
                    "trigger_channels": ["arduino:5"]
                },
                "25": {
                    "name": "Rear Drawer",
                    "type": "sensor",
                    "trigger_channels": ["arduino:6"]
                },
                "12": {
                    "name": "Kitchen Bench",
                    "type": "sensor",
                    "trigger_channels": ["arduino:4"]
                }
            },
            "relay_states": {}
        }
        write_config_atomically(default_config, config_path)
        logging.info("Created default config.json")
    with open(config_path, 'r') as f:
        config = json.load(f)
    if 'theme' not in config:
        config['theme'] = {
            "darkMode": "off",
            "autoTheme": "off",
            "autoBrightness": "off",
            "defaultTheme": "light",
            "screen_brightness": "medium"
        }
    if 'channels' not in config:
        config['channels'] = {"arduino": {}, "relays": {}}
    if 'arduino' not in config['channels']:
        config['channels']['arduino'] = {}
    if 'relays' not in config['channels']:
        config['channels']['relays'] = {}
    # Add display to arduino channels if missing
    for channel, info in config['channels']['arduino'].items():
        if 'display' not in info:
            info['display'] = channel not in ['3', '10']
    # Add display to relay channels if missing
    for channel, info in config['channels']['relays'].items():
        if 'display' not in info:
            info['display'] = True
    if 'scenes' not in config:
        config['scenes'] = {}
    if 'reed_switches' not in config:
        config['reed_switches'] = {}
    # Add missing reed switches
    default_reed_switches = {
        "23": {
            "name": "Kitchen Panel",
            "type": "sensor",
            "trigger_channels": ["arduino:1", "arduino:2", "arduino:3"]
        },
        "24": {
            "name": "Storage Panel",
            "type": "sensor",
            "trigger_channels": ["arduino:5"]
        },
        "25": {
            "name": "Rear Drawer",
            "type": "sensor",
            "trigger_channels": ["arduino:6"]
        },
        "12": {
            "name": "Kitchen Bench",
            "type": "sensor",
            "trigger_channels": ["arduino:4"]
        }
    }
    updated = False
    for pin, info in default_reed_switches.items():
        if pin not in config['reed_switches']:
            config['reed_switches'][pin] = info
            updated = True
            logging.info(f"Added missing reed switch entry for pin {pin}")
        elif pin == "23" and "arduino:3" not in config['reed_switches'][pin]['trigger_channels']:
            config['reed_switches'][pin]['trigger_channels'].append("arduino:3")
            updated = True
            logging.info(f"Added arduino:3 to kitchen panel trigger_channels")
    if 'relay_states' not in config:
        config['relay_states'] = {}
    if 'evening_offset' not in config:
        config['evening_offset'] = 60
        updated = True
    if 'night_time' not in config:
        config['night_time'] = "20:00"
        updated = True
    if updated:
        write_config_atomically(config, config_path)
        logging.info("Updated config with missing reed switches or trigger channels")
    else:
        logging.info("Loaded and validated config")
    
except Exception as e:
    logging.error(f"Error loading config.json: {e}")
    config = {
        "theme": {
            "darkMode": "off",
            "autoTheme": "off",
            "autoBrightness": "off",
            "defaultTheme": "light",
            "screen_brightness": "medium"
        },
        "channels": {
            "arduino": {},
            "relays": {}
        },
        "scenes": {},
        "reed_switches": {
            "23": {
                "name": "Kitchen Panel",
                "type": "sensor",
                "trigger_channels": ["arduino:1", "arduino:2", "arduino:3"]
            },
            "24": {
                "name": "Storage Panel",
                "type": "sensor",
                "trigger_channels": ["arduino:5"]
            },
            "25": {
                "name": "Rear Drawer",
                "type": "sensor",
                "trigger_channels": ["arduino:6"]
            },
            "12": {
                "name": "Kitchen Bench",
                "type": "sensor",
                "trigger_channels": ["arduino:4"]
            }
        },
        "relay_states": {},
        "evening_offset": 60,
        "night_time": "20:00"
    }
    write_config_atomically(config, config_path)
    logging.info("Created fallback config.json")

# Manual override and channel to reeds mapping
manual_override = {pin_str: False for pin_str in config['reed_switches']}
channel_to_reeds = defaultdict(list)
for pin_str, info in config['reed_switches'].items():
    for ch in info.get('trigger_channels', []):
        if ch.startswith('arduino:'):
            ch_idx = ch.split(':')[1]
            channel_to_reeds[ch_idx].append(pin_str)
reed_linked_channels = set(channel_to_reeds.keys())

def check_arduino_alive():
    if not arduino_available or ser_arduino is None:
        return False
    try:
        ser_arduino.write(b'P\n')
        response = ser_arduino.readline().decode().strip()
        return response == 'AA'
    except Exception as e:
        logging.error(f"Alive check failed: {e}")
        return False

def monitor_arduino():
    global arduino_available, ser_arduino
    failure_count = 0
    MAX_FAILURES = 3
    while True:
        if arduino_available:
            if not check_arduino_alive():
                failure_count += 1
                logging.warning(f"Arduino unresponsive (failure {failure_count}/{MAX_FAILURES})")
                if failure_count >= MAX_FAILURES:
                    logging.error("Arduino offline - disabling features")
                    try:
                        ser_arduino.close()
                    except Exception as e:
                        logging.warning(f"Error closing serial on disconnect: {e}")
                    ser_arduino = None
                    arduino_available = False
                    failure_count = 0
            else:
                failure_count = 0
        else:
            logging.info("Attempting to reconnect to Arduino")
            if init_serial():
                logging.info("Successfully reconnected to Arduino")
            else:
                logging.debug("Reconnect attempt failed, will try again later")
        time.sleep(30)  # Check every 30s

GREEN_FACTOR = 0.05  # Green PWM = % of red for red-orange mix

def set_arduino_pwm(channel, value, ramp_time=1000):
    """Send PWM value (0-255) to Arduino for the specified channel via serial, with optional ramp."""
    if not arduino_available:
        logging.error("Serial not initialized")
        return False
    if not (1 <= channel <= 12):
        logging.error(f"Invalid PWM channel: {channel}")
        return False
    value = max(0, min(255, int(value)))
    logging.debug(f"Setting PWM: channel={channel}, value={value}, ramp_time={ramp_time}ms")
    
    retries = 3
    for attempt in range(retries):
        with serial_lock:
            try:
                ser_arduino.flushInput()
                ser_arduino.flushOutput()
                time.sleep(0.05)
                
                if ramp_time > 0:
                    ser_arduino.write(f'R{channel} {value} {ramp_time}\n'.encode())
                else:
                    ser_arduino.write(f'S{channel} {value}\n'.encode())
                
                response = ser_arduino.readline().decode().strip()
                if response == 'AA':
                    logging.debug(f"Received ACK for Arduino channel {channel} (attempt {attempt+1})")
                    return True
                elif response.isdigit():
                    read_value = int(response)
                    if abs(read_value - value) <= 5:
                        logging.debug(f"Set and verified Arduino channel {channel} to PWM {value} (attempt {attempt+1})")
                        return True
                    else:
                        logging.warning(f"PWM verification failed on attempt {attempt+1}: set {value}, read {read_value}")
                else:
                    logging.warning(f"Unexpected response on attempt {attempt+1}: {response}")
            except Exception as e:
                logging.warning(f"Error on attempt {attempt+1} setting PWM for channel {channel}: {e}")
        
        if attempt < retries - 1:
            time.sleep(0.1)
    
    logging.error(f"Failed to set PWM for channel {channel} after {retries} attempts")
    return False

def get_arduino_pwm(channel):
    if not arduino_available:
        logging.error("Serial not initialized")
        return None
    if not (1 <= channel <= 12):
        logging.error(f"Invalid PWM channel: {channel}")
        return None
    
    retries = 3
    for attempt in range(retries):
        with serial_lock:
            try:
                logging.debug(f"Reading PWM for channel {channel}")
                ser_arduino.flushInput()
                ser_arduino.flushOutput()
                time.sleep(0.05)
                
                ser_arduino.write(f'G{channel}\n'.encode())
                response = ser_arduino.readline().decode().strip()
                if response.isdigit():
                    value = int(response)
                    if 0 <= value <= 255:
                        logging.debug(f"Read Arduino channel {channel}: PWM {value} (attempt {attempt+1})")
                        return value
                    else:
                        logging.warning(f"Invalid PWM value on attempt {attempt+1}: {value}")
                else:
                    logging.warning(f"Non-digit response on attempt {attempt+1}: {response}")
            except Exception as e:
                logging.warning(f"Error on attempt {attempt+1} reading PWM for channel {channel}: {e}")
        
        if attempt < retries - 1:
            time.sleep(0.1)
    
    logging.error(f"Failed to read PWM for channel {channel} after {retries} attempts")
    return None

current_scene = None

def get_target_pwms(pin_str, current_local, forced_period=None, force_operate=False):
    local_tz_str = get_local_tz_str()
    local_tz = pytz.timezone(local_tz_str)
    if gps_data["fix"] == "Yes" and gps_data["latitude"] and gps_data["longitude"]:
        loc = LocationInfo("Current", "", local_tz_str, gps_data["latitude"], gps_data["longitude"])
    else:
        loc = MELBOURNE_LOCATION
    if current_local.hour >= 12:
        today = current_local.date()
        s = sun(loc.observer, date=today, tzinfo=local_tz)
        sunset = s["sunset"]
        operate_start = sunset - timedelta(minutes=config['evening_offset'])
        tomorrow = today + timedelta(days=1)
        s_tom = sun(loc.observer, date=tomorrow, tzinfo=local_tz)
        operate_end = s_tom["sunrise"] + timedelta(minutes=30)
    else:
        today = current_local.date()
        s = sun(loc.observer, date=today, tzinfo=local_tz)
        operate_end = s["sunrise"] + timedelta(minutes=30)
        prev_day = today - timedelta(days=1)
        s_prev = sun(loc.observer, date=prev_day, tzinfo=local_tz)
        operate_start = s_prev["sunset"] - timedelta(minutes=config['evening_offset'])
    lights_operate = operate_start <= current_local < operate_end
    if not lights_operate and not force_operate:
        return {}, False
    period = forced_period
    if period is None:
        if current_scene in ['evening', 'night']:
            period = current_scene
        else:
            operate_start_date = operate_start.date()
            night_time_obj = dt_time.fromisoformat(config['night_time'])
            eight_pm = local_tz.localize(datetime.combine(operate_start_date, night_time_obj))
            if current_local < eight_pm:
                period = 'evening'
            else:
                period = 'night'
    trigger_channels = config['reed_switches'][pin_str].get('trigger_channels', [])
    arduino_triggers = [ch.split(':')[1] for ch in trigger_channels if ch.startswith('arduino:')]
    if period not in config['reed_switches'][pin_str]:
        # Fallback to full on for trigger channels
        target = {int(ch): 255 for ch in arduino_triggers}
        return target, True
    config_dict = config['reed_switches'][pin_str][period]
    target = {int(ch): 0 for ch in arduino_triggers}
    for ch_str, percent in config_dict.items():
        if ch_str.startswith('arduino:'):
            _, ch_idx = ch_str.split(':')
            ch_idx = int(ch_idx)
            if ch_idx in target:
                pwm = int(255 * percent / 100.0)
                target[ch_idx] = pwm
    # Enforce mutual exclusivity and auto green
    if 2 in target and target[2] > 0:
        target[1] = 0
        if 3 in target:  # only set if 3 is configured
            target[3] = int(target[2] * GREEN_FACTOR)
    elif 1 in target and target[1] > 0:
        target[2] = 0
        if 3 in target:
            target[3] = 0
    if 9 in target and target[9] > 0:
        target[8] = 0
        if 10 in target:
            target[10] = int(target[9] * GREEN_FACTOR)
    elif 8 in target and target[8] > 0:
        target[9] = 0
        if 10 in target:
            target[10] = 0
    return target, True
    
def get_operating_period(current_local):
    local_tz_str = get_local_tz_str()
    local_tz = pytz.timezone(local_tz_str)
    if gps_data["fix"] == "Yes" and gps_data["latitude"] and gps_data["longitude"]:
        loc = LocationInfo("Current", "", local_tz_str, gps_data["latitude"], gps_data["longitude"])
    else:
        loc = MELBOURNE_LOCATION
    if current_local.hour >= 12:
        today = current_local.date()
        s = sun(loc.observer, date=today, tzinfo=local_tz)
        sunset = s["sunset"]
        operate_start = sunset - timedelta(minutes=config['evening_offset'])
        operate_start_date = today
        tomorrow = today + timedelta(days=1)
        s_tom = sun(loc.observer, date=tomorrow, tzinfo=local_tz)
        operate_end = s_tom["sunrise"] + timedelta(minutes=30)
    else:
        today = current_local.date()
        s = sun(loc.observer, date=today, tzinfo=local_tz)
        operate_end = s["sunrise"] + timedelta(minutes=30)
        prev_day = today - timedelta(days=1)
        s_prev = sun(loc.observer, date=prev_day, tzinfo=local_tz)
        sunset = s_prev["sunset"]
        operate_start = sunset - timedelta(minutes=config['evening_offset'])
        operate_start_date = prev_day
    lights_operate = operate_start <= current_local < operate_end
    if not lights_operate:
        return None
    night_time_obj = dt_time.fromisoformat(config['night_time'])
    eight_pm = local_tz.localize(datetime.combine(operate_start_date, night_time_obj))
    period = 'evening' if current_local < eight_pm else 'night'
    return period

def update_lights_based_on_time():
    if h is None:
        return
    local_tz_str = get_local_tz_str()
    local_tz = pytz.timezone(local_tz_str)
    current_local = datetime.now(local_tz)
    for pin_str in config['reed_switches']:
        if manual_override[pin_str]:
            continue
        # Special override for kitchen bench (pin 12): if kitchen panel (23) is closed, force bench off
        if pin_str == '12':
            if lgpio.gpio_read(h, 23) == 0:
                current_pwm = get_arduino_pwm(4)
                if current_pwm is not None and current_pwm > 0:
                    set_arduino_pwm(4, 0, ramp_time=1000)
                continue  # Skip normal logic
        if lgpio.gpio_read(h, int(pin_str)) == 1:
            targets, operate = get_target_pwms(pin_str, current_local)
            if operate:
                for ch_idx, target_pwm in targets.items():
                    current_pwm = get_arduino_pwm(ch_idx)
                    if current_pwm is not None and abs(current_pwm - target_pwm) > 5:
                        set_arduino_pwm(ch_idx, target_pwm, ramp_time=2000 if pin_str == '23' else 1000)

def activate_scene_func(scene_name):
    global current_scene
    try:
        scene = config['scenes'][scene_name]
        # Infer all possible Arduino channels from configured channels
        all_arduino_channels = set(config['channels']['arduino'].keys())
        target_pwm = {}  # Don't init to 0 for all; only set specified non-reed-linked
        scene_arduino = scene.get('arduino', {})
        for channel, brightness in scene_arduino.items():
            if int(brightness) > 0 and channel in reed_linked_channels:  # Skip positive settings on reed-linked
                continue
            target_pwm[channel] = int(brightness * 255 / 100)
        # Enforce mutual exclusivity and auto green
        if '2' in target_pwm and target_pwm['2'] > 0:
            target_pwm['1'] = 0
            target_pwm['3'] = int(target_pwm['2'] * GREEN_FACTOR)
        elif '1' in target_pwm and target_pwm['1'] > 0:
            target_pwm['2'] = 0
            target_pwm['3'] = 0
        if '9' in target_pwm and target_pwm['9'] > 0:
            target_pwm['8'] = 0
            target_pwm['10'] = int(target_pwm['9'] * GREEN_FACTOR)
        elif '8' in target_pwm and target_pwm['8'] > 0:
            target_pwm['9'] = 0
            target_pwm['10'] = 0
        # Channels to set: only those in target_pwm
        channels_to_set = list(target_pwm.keys())
        if arduino_available:
            for channel in sorted(channels_to_set):
                target = target_pwm.get(channel, 0)
                if not set_arduino_pwm(int(channel), target, ramp_time=1000):
                    logging.error(f"Failed to set channel {channel} during scene activation")
            # Final verification after all ramps
            time.sleep(1.5)  # Wait for longest ramp + margin
            for channel in channels_to_set:
                current = get_arduino_pwm(int(channel))
                target = target_pwm.get(channel, 0)
                if current is None or abs(current - target) > 5:
                    logging.error(f"Final verification failed for channel {channel}: current {current}, target {target}")
        # Set manual override only for reeds whose triggers overlap with set channels
        for pin_str in config['reed_switches']:
            trigger_channels = set(ch.split(':')[1] for ch in config['reed_switches'][pin_str].get('trigger_channels', []) if ch.startswith('arduino:'))
            if trigger_channels & set(target_pwm.keys()):  # If overlap, override to block auto on those
                manual_override[pin_str] = True
        if scene_name in ['evening', 'night']:
            current_scene = scene_name
        else:
            current_scene = None
        if scene_name in ['evening', 'night'] and h:
            current_local = datetime.now(pytz.timezone(get_local_tz_str()))
            if lgpio.gpio_read(h, 23) == 1:  # Kitchen panel open
                targets, _ = get_target_pwms('23', current_local, forced_period=scene_name, force_operate=True)
                for ch_idx, pwm in targets.items():
                    set_arduino_pwm(ch_idx, pwm, ramp_time=1000)
                time.sleep(1.5)  # Wait for ramp to complete
                for ch_idx, pwm in targets.items():
                    current = get_arduino_pwm(ch_idx)
                    target = pwm
                    if current is None or abs(current - target) > 5:
                        logging.error(f"Final verification failed for kitchen channel {ch_idx}: current {current}, target {target}")
            if lgpio.gpio_read(h, 12) == 1:  # Kitchen bench open (and implicitly kitchen panel open)
                bench_targets, _ = get_target_pwms('12', current_local, forced_period=scene_name, force_operate=True)
                for ch_idx, pwm in bench_targets.items():
                    set_arduino_pwm(ch_idx, pwm, ramp_time=1000)
                time.sleep(1.5)  # Wait for ramp to complete
                for ch_idx, pwm in bench_targets.items():
                    current = get_arduino_pwm(ch_idx)
                    target = pwm
                    if current is None or abs(current - target) > 5:
                        logging.error(f"Final verification failed for bench channel {ch_idx}: current {current}, target {target}")
        config['relay_states'] = config.get('relay_states', {})
        if h:
            for pin, state in scene.get('relays', {}).items():
                if pin in config['channels']['relays']:
                    lgpio.gpio_write(h, int(pin), 1 if state == 0 else 0)
                    config['relay_states'][pin] = state
            for pin in config['channels']['relays']:
                if pin not in scene.get('relays', {}):
                    lgpio.gpio_write(h, int(pin), 1)
                    config['relay_states'][pin] = 0
            save_relay_states(config['relay_states'])
    except Exception as e:
        logging.error(f"Error in activate_scene_func: {e}")

last_all_off_trigger = None
last_evening_to_night_trigger = None
last_sunset_evening_trigger = None

def check_auto_scenes():
    local_tz_str = get_local_tz_str()
    local_tz = pytz.timezone(local_tz_str)
    current_local = datetime.now(local_tz)
    period = get_operating_period(current_local)
    if period and 'scenes' in config and period in config['scenes'] and h and lgpio.gpio_read(h, 23) == 1 and current_scene != period:
        activate_scene_func(period)
        logging.info(f"Auto-triggered {period} scene after config change")

def light_manager():
    global last_all_off_trigger, last_evening_to_night_trigger, last_sunset_evening_trigger
    while True:
        update_lights_based_on_time()
        local_tz_str = get_local_tz_str()
        local_tz = pytz.timezone(local_tz_str)
        current_local = datetime.now(local_tz)
        if gps_data["fix"] == "Yes" and gps_data["latitude"] and gps_data["longitude"]:
            loc = LocationInfo("Current", "", local_tz_str, gps_data["latitude"], gps_data["longitude"])
        else:
            loc = MELBOURNE_LOCATION
        today = current_local.date()
        s = sun(loc.observer, date=today, tzinfo=local_tz)
        sunset = s["sunset"]
        operate_start = sunset - timedelta(minutes=config['evening_offset'])  # Evening start time
        trigger_time = sunrise + timedelta(hours=1)   # All off time
        
        # New: Auto-activate evening at operate_start if kitchen open
        if current_local >= operate_start and (last_sunset_evening_trigger is None or last_sunset_evening_trigger.date() != today):
            if h and lgpio.gpio_read(h, 23) == 1:  # Kitchen open
                if 'evening' in config['scenes'] and current_scene != 'evening':
                    activate_scene_func('evening')
                    last_sunset_evening_trigger = current_local
                    logging.info(f"Auto-triggered evening scene (kitchen open) at {current_local}")
                else:
                    logging.warning("Evening scene not defined or already active")
        
        # Existing: Auto-transition from evening to night at 8 PM if kitchen open
        if current_scene == 'evening':
            # Calculate the 8 PM boundary for today (or prev if before noon, but align to operate_start)
            if current_local.hour >= 12:
                operate_start_date = today
            else:
                operate_start_date = today - timedelta(days=1)
            night_time_obj = dt_time.fromisoformat(config['night_time'])
            eight_pm = local_tz.localize(datetime.combine(operate_start_date, night_time_obj))
            if current_local >= eight_pm and (last_evening_to_night_trigger is None or last_evening_to_night_trigger.date() != operate_start_date):
                if h and lgpio.gpio_read(h, 23) == 1:  # Kitchen open
                    if 'night' in config['scenes']:
                        activate_scene_func('night')
                        last_evening_to_night_trigger = current_local
                        logging.info(f"Auto-triggered night scene from evening (kitchen open) at {current_local}")
                    else:
                        logging.warning("Night scene not defined")
        
        if current_local >= trigger_time and (last_all_off_trigger is None or last_all_off_trigger.date() != today):
            if 'all_off' in config['scenes']:
                activate_scene_func('all_off')
                last_all_off_trigger = current_local
                logging.info(f"Triggered all off scene at {current_local}")
            else:
                logging.warning("All off scene not defined")
        
        time.sleep(60)

def check_initial_reed_states():
    if h is None:
        logging.error("GPIO not initialized")
        return {}
    initial_states = {}
    local_tz_str = get_local_tz_str()
    local_tz = pytz.timezone(local_tz_str)
    for pin_str, switch_info in config['reed_switches'].items():
        pin = int(pin_str)
        try:
            initial_state = lgpio.gpio_read(h, pin)
            state_str = "closed" if initial_state == 0 else "open"
            logging.info(f"Initial state for {switch_info['name']}: {state_str}")
            initial_states[pin] = initial_state

            current_local = datetime.now(local_tz)
            # Kitchen-specific screen and light control
            if pin == 23:
                display_pi_user = "pi"
                display_pi_ip = "10.10.10.20"
                ssh_key = "/home/pi/.ssh/id_rsa_shutdown"
                if initial_state == 0:  # Closed: screen off + lights to 0
                    command = ["xset", "dpms", "force", "off"]
                    action_desc = "screen off"
                    brightness_value = None
                    # Turn off kitchen lights
                    set_arduino_pwm(1, 0, ramp_time=2000)
                    set_arduino_pwm(2, 0, ramp_time=2000)
                    set_arduino_pwm(3, 0, ramp_time=2000)
                    # Also turn off kitchen bench light
                    set_arduino_pwm(4, 0, ramp_time=1000)
                else:  # Open: wake screen + lights if operate
                    command = ["xdotool", "key", "F5"]
                    action_desc = "screen wake and refresh"
                    brightness_level = config['theme'].get('screen_brightness', 'medium')
                    brightness_map = {'low': 25, 'medium': 127, 'high': 255}
                    brightness_value = brightness_map.get(brightness_level, 127)
                    # Compute and set kitchen lights based on time/scene only if operate
                    targets, operate = get_target_pwms(pin_str, current_local)
                    if operate:
                        for ch_idx, pwm in targets.items():
                            set_arduino_pwm(ch_idx, pwm, ramp_time=2000)
                        # If kitchen bench panel is open, turn on its light based on time logic
                        if initial_states.get(12, 0) == 1:
                            bench_targets, bench_operate = get_target_pwms('12', current_local)
                            if bench_operate:
                                for ch_idx, pwm in bench_targets.items():
                                    set_arduino_pwm(ch_idx, pwm, ramp_time=1000)
                        # New: Activate scene if during evening/night and not already active
                        period = get_operating_period(current_local)
                        if current_time_cache["fix_obtained"] and period and period in config['scenes'] and current_scene != period:
                            activate_scene_func(period)
                            logging.info(f"Auto-triggered {period} scene on startup (kitchen open)")
                max_attempts = 3
                retry_interval = 10
                for attempt in range(max_attempts):
                    if send_ssh_display_command(display_pi_user, display_pi_ip, ssh_key, command, action_desc, brightness_value):
                        break
                    logging.warning(f"SSH attempt {attempt + 1}/{max_attempts} failed")
                    time.sleep(retry_interval)
                else:
                    logging.error("All SSH attempts failed")

            # For storage, rear drawer, and kitchen bench, set initial lights based on state
            elif pin in [24, 25, 12]:
                trigger_channels = switch_info.get('trigger_channels', [])
                targets, operate = get_target_pwms(pin_str, current_local)
                if initial_state == 1 and operate:  # Open and operate: set levels
                    for ch_idx, pwm in targets.items():
                        set_arduino_pwm(ch_idx, pwm, ramp_time=1000)
                elif initial_state == 0:  # Closed: set to 0
                    target_pwm = 0
                    for ch in trigger_channels:
                        if ch.startswith('arduino:'):
                            channel_idx = int(ch.split(':')[1])
                            set_arduino_pwm(channel_idx, target_pwm, ramp_time=1000)
        except Exception as e:
            logging.error(f"Error reading initial state for pin {pin}: {e}")
            initial_states[pin] = None
    return initial_states

def monitor_reed_switch(pin, initial_state):
    if h is None:
        logging.error("GPIO not initialized")
        return
    switch_info = config['reed_switches'].get(str(pin))
    if switch_info is None:
        logging.error(f"Reed switch pin {pin} not found in config")
        return
    last_state = initial_state
    debounce_count = 0
    DEBOUNCE_THRESHOLD = 2
    last_read_state = None
    logging.info(f"Starting monitor for {switch_info['name']} on GPIO {pin}")
    while True:
        try:
            current_read = lgpio.gpio_read(h, pin)
            if current_read == last_read_state:
                debounce_count += 1
            else:
                debounce_count = 0
                last_read_state = current_read
            if debounce_count >= DEBOUNCE_THRESHOLD and current_read != last_state:
                state_str = "closed" if current_read == 0 else "open"
                logging.info(f"{switch_info['name']} {state_str}")
                manual_override[str(pin)] = False

                local_tz_str = get_local_tz_str()
                local_tz = pytz.timezone(local_tz_str)
                current_local = datetime.now(local_tz)
                # Kitchen-specific: control screen and lights
                if pin == 23:
                    display_pi_user = "pi"
                    display_pi_ip = "10.10.10.20"
                    ssh_key = "/home/pi/.ssh/id_rsa_shutdown"
                    if current_read == 0:  # Closed: screen off + lights to 0
                        command = ["xset", "dpms", "force", "off"]
                        action_desc = "screen off"
                        brightness_value = None
                        # Turn off kitchen lights
                        set_arduino_pwm(1, 0, ramp_time=2000)
                        set_arduino_pwm(2, 0, ramp_time=2000)
                        set_arduino_pwm(3, 0, ramp_time=2000)
                        # Also turn off kitchen bench light
                        set_arduino_pwm(4, 0, ramp_time=1000)
                    else:  # Open: wake screen + lights if operate
                        command = ["xdotool", "key", "F5"]
                        action_desc = "screen wake and refresh"
                        brightness_level = config['theme'].get('screen_brightness', 'medium')
                        brightness_map = {'low': 25, 'medium': 127, 'high': 255}
                        brightness_value = brightness_map.get(brightness_level, 127)
                        # Compute and set kitchen lights based on time/scene only if operate
                        targets, operate = get_target_pwms(str(pin), current_local)
                        if operate:
                            for ch_idx, pwm in targets.items():
                                set_arduino_pwm(ch_idx, pwm, ramp_time=2000)
                            # If kitchen bench panel is open, turn on its light based on time logic
                            if lgpio.gpio_read(h, 12) == 1:
                                bench_targets, bench_operate = get_target_pwms('12', current_local)
                                if bench_operate:
                                    for ch_idx, pwm in bench_targets.items():
                                        set_arduino_pwm(ch_idx, pwm, ramp_time=1000)
                    send_ssh_display_command(display_pi_user, display_pi_ip, ssh_key, command, action_desc, brightness_value)
                    last_state = current_read
                # Storage, rear drawer, and kitchen bench: control lights
                elif pin in [24, 25, 12]:
                    trigger_channels = switch_info.get('trigger_channels', [])
                    targets, operate = get_target_pwms(str(pin), current_local)
                    if current_read == 1 and operate:  # Open and operate: set levels
                        for ch_idx, pwm in targets.items():
                            set_arduino_pwm(ch_idx, pwm, ramp_time=1000)
                    elif current_read == 0:  # Closed: set to 0
                        target_pwm = 0
                        for ch in trigger_channels:
                            if ch.startswith('arduino:'):
                                channel_idx = int(ch.split(':')[1])
                                set_arduino_pwm(channel_idx, target_pwm, ramp_time=1000)
                    last_state = current_read

            time.sleep(0.5)
        except Exception as e:
            logging.error(f"Error monitoring reed switch pin {pin}: {e}")
            time.sleep(5)

# Initialize GPIO
init_gpio()

# Serial init after GPIO
arduino_available = init_serial()

# Start GPS thread
gps_thread = threading.Thread(target=update_gps_data, daemon=True)
gps_thread.start()

# Wait for GPS fix before initial reed check
start_time = time.time()
while not current_time_cache["fix_obtained"] and time.time() - start_time < 30:
    time.sleep(1)
if not current_time_cache["fix_obtained"]:
    logging.warning("No GPS fix after 30s, using system time for initial setup")

# Perform initial reed switch checks for all
initial_states = check_initial_reed_states()

# Start monitoring threads for all reed switches
for pin_str in config['reed_switches']:
    pin = int(pin_str)
    initial_state = initial_states.get(pin, None)
    if initial_state is not None:
        thread = threading.Thread(target=monitor_reed_switch, args=(pin, initial_state), daemon=True)
        thread.start()

if arduino_available:
    arduino_monitor_thread = threading.Thread(target=monitor_arduino, daemon=True)
    arduino_monitor_thread.start()

# Start light manager thread
light_manager_thread = threading.Thread(target=light_manager, daemon=True)
light_manager_thread.start()

@app.route('/')
def index():
    try:
        # Filter channels based on display attribute
        filtered_arduino_channels = {k: v for k, v in config['channels']['arduino'].items() if v.get('display', True)}
        filtered_relay_channels = {k: v for k, v in config['channels']['relays'].items() if v.get('display', True)}
        
        logging.info(f"Arduino channels before filtering: {list(config['channels']['arduino'].keys())}")
        logging.info(f"Display value for channel 9: {config['channels']['arduino'].get('9', {}).get('display', 'missing')}")
        logging.info(f"Filtered Arduino channels: {list(filtered_arduino_channels.keys())}")
        logging.info(f"Filtered relay channels: {list(filtered_relay_channels.keys())}")
        
        return render_template('index.html',
                              scenes=config['scenes'].keys(),
                              arduino_channels=filtered_arduino_channels,
                              relay_channels=filtered_relay_channels,
                              reed_switches=config['reed_switches'],
                              arduino_available=arduino_available,
                              evening_offset=config.get('evening_offset', 60),
                              night_time=config.get('night_time', '20:00'))
    except Exception as e:
        logging.error(f"Error rendering index: {e}")
        return f"Error rendering page: {e}", 500
        
@app.route('/5inch')
def index_5inch():
    try:
        # Filter channels based on display attribute (same as main index)
        filtered_arduino_channels = {k: v for k, v in config['channels']['arduino'].items() if v.get('display', True)}
        filtered_relay_channels = {k: v for k, v in config['channels']['relays'].items() if v.get('display', True)}
        
        logging.info(f"Filtered Arduino channels for 5inch: {list(filtered_arduino_channels.keys())}")
        logging.info(f"Filtered relay channels for 5inch: {list(filtered_relay_channels.keys())}")
        
        return render_template('index_5inch.html',
                              scenes=config['scenes'].keys(),
                              arduino_channels=filtered_arduino_channels,
                              relay_channels=filtered_relay_channels,
                              reed_switches=config['reed_switches'],
                              arduino_available=arduino_available)
    except Exception as e:
        logging.error(f"Error rendering index_5inch: {e}")
        return f"Error rendering page: {e}", 500

@app.route('/set_brightness', methods=['POST'])
def set_brightness():
    global current_scene
    try:
        if not arduino_available:
            logging.error("set_brightness called but Arduino not detected")
            return jsonify({"error": "Arduino not detected"}), 503
        data = request.json
        logging.debug(f"Received set_brightness request: {data}")
        if not data:
            logging.error("Empty request body")
            return jsonify({"error": "Empty request body"}), 400
        
        channel_type = data.get('type')
        channel = data.get('channel')
        brightness = data.get('brightness')

        if not all([channel_type, channel, brightness is not None]):
            logging.error(f"Missing required fields: type={channel_type}, channel={channel}, brightness={brightness}")
            return jsonify({"error": "Missing required fields"}), 400

        if channel_type != 'arduino':
            logging.error(f"Invalid channel type: {channel_type}")
            return jsonify({"error": "Invalid channel type, expected 'arduino'"}), 400

        try:
            channel_idx = int(channel)
        except (ValueError, TypeError):
            logging.error(f"Invalid channel format: {channel}")
            return jsonify({"error": "Channel must be an integer"}), 400

        if str(channel_idx) not in config['channels']['arduino']:
            logging.error(f"Channel {channel_idx} not in config")
            return jsonify({"error": f"Channel {channel_idx} not configured"}), 400

        if not 1 <= channel_idx <= 12:
            logging.error(f"Invalid Arduino channel: {channel_idx}")
            return jsonify({"error": "Channel must be between 1 and 12"}), 400

        try:
            brightness = int(brightness)
            if not 0 <= brightness <= 100:
                raise ValueError
        except (ValueError, TypeError):
            logging.error(f"Invalid brightness value: {brightness}")
            return jsonify({"error": "Brightness must be an integer between 0 and 100"}), 400

        target_pwm = int(brightness * 255 / 100)
        logging.debug(f"Attempting to set channel {channel_idx} to PWM {target_pwm}")

        if not set_arduino_pwm(channel_idx, target_pwm, ramp_time=1000):
            logging.error(f"Failed to set PWM for channel {channel_idx} to {target_pwm}")
            return jsonify({"error": "Failed to set PWM"}), 500

        if channel_idx == 1 and target_pwm > 0:
            set_arduino_pwm(2, 0, ramp_time=1000)
            set_arduino_pwm(3, 0, ramp_time=1000)
        elif channel_idx == 2 and target_pwm > 0:
            set_arduino_pwm(1, 0, ramp_time=1000)
        if channel_idx == 2:
            green_value = int(target_pwm * GREEN_FACTOR)
            if not set_arduino_pwm(3, green_value, ramp_time=1000):
                logging.warning(f"Failed to auto-set green channel 3 to {green_value}")

        if channel_idx == 8 and target_pwm > 0:
            set_arduino_pwm(9, 0, ramp_time=1000)
            set_arduino_pwm(10, 0, ramp_time=1000)
        elif channel_idx == 9 and target_pwm > 0:
            set_arduino_pwm(8, 0, ramp_time=1000)
        if channel_idx == 9:
            green_value = int(target_pwm * GREEN_FACTOR)
            if not set_arduino_pwm(10, green_value, ramp_time=1000):
                logging.warning(f"Failed to auto-set green channel 10 to {green_value}")

        logging.debug(f"Successfully initiated set for channel {channel_idx} to PWM {target_pwm}")
        if current_scene and str(channel_idx) in config['scenes'].get(current_scene, {}).get('arduino', {}):
            logging.info(f"Breaking scene '{current_scene}' due to manual change on channel {channel_idx}")
            current_scene = None
        for reed in channel_to_reeds[str(channel_idx)]:
            manual_override[reed] = True
        return jsonify({"message": f"Brightness set to {brightness}%"})
    except Exception as e:
        logging.error(f"Error in set_brightness: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/toggle', methods=['POST'])
def toggle():
    global current_scene
    try:
        data = request.json
        logging.debug(f"Received toggle request: {data}")
        if not data:
            logging.error("Empty request body")
            return jsonify({"error": "Empty request body"}), 400

        channel_type = data.get('type')
        channel = data.get('channel')
        state = data.get('state')

        if not all([channel_type, channel, state]):
            logging.error(f"Missing required fields: type={channel_type}, channel={channel}, state={state}")
            return jsonify({"error": "Missing required fields"}), 400

        if channel_type != 'arduino' and channel_type != 'relays':
            logging.error(f"Invalid channel type: {channel_type}")
            return jsonify({"error": "Invalid channel type"}), 400

        if channel_type == 'arduino':
            if not arduino_available:
                logging.error("toggle called but Arduino not detected")
                return jsonify({"error": "Arduino not detected"}), 503
            try:
                channel_idx = int(channel)
            except (ValueError, TypeError):
                logging.error(f"Invalid channel format: {channel}")
                return jsonify({"error": "Channel must be an integer"}), 400
            if str(channel_idx) not in config['channels']['arduino']:
                logging.error(f"Channel {channel_idx} not in config")
                return jsonify({"error": f"Channel {channel_idx} not configured"}), 400
            if not 1 <= channel_idx <= 12:
                logging.error(f"Invalid Arduino channel: {channel_idx}")
                return jsonify({"error": "Channel must be between 1 and 12"}), 400
            target_pwm = 255 if state == 'on' else 0  # Use 50% for 'on' to match observed behavior
            logging.debug(f"Attempting to set channel {channel_idx} to PWM {target_pwm}")
            if not set_arduino_pwm(channel_idx, target_pwm):
                logging.error(f"Failed to set PWM for channel {channel_idx} to {target_pwm}")
                return jsonify({"error": "Failed to set PWM"}), 500

            # Kitchen color logic
            if channel_idx == 1 and target_pwm > 0:
                set_arduino_pwm(2, 0, ramp_time=1000)
                set_arduino_pwm(3, 0, ramp_time=1000)
            elif channel_idx == 2 and target_pwm > 0:
                set_arduino_pwm(1, 0, ramp_time=1000)
            if channel_idx == 2:
                green_value = int(target_pwm * GREEN_FACTOR)
                if not set_arduino_pwm(3, green_value):
                    logging.warning(f"Failed to auto-set green channel 3 to {green_value}")

            # Awning color logic (mirrored from kitchen)
            if channel_idx == 8 and target_pwm > 0:
                set_arduino_pwm(9, 0, ramp_time=1000)
                set_arduino_pwm(10, 0, ramp_time=1000)
            elif channel_idx == 9 and target_pwm > 0:
                set_arduino_pwm(8, 0, ramp_time=1000)
            if channel_idx == 9:
                green_value = int(target_pwm * GREEN_FACTOR)
                if not set_arduino_pwm(10, green_value):
                    logging.warning(f"Failed to auto-set green channel 10 to {green_value}")

            # Removed final verification to avoid timing issues with ramps
            logging.debug(f"Successfully initiated set for channel {channel_idx} to PWM {target_pwm}")
            if current_scene and str(channel_idx) in config['scenes'].get(current_scene, {}).get('arduino', {}):
                logging.info(f"Breaking scene '{current_scene}' due to manual change on channel {channel_idx}")
                current_scene = None
            for reed in channel_to_reeds[str(channel_idx)]:
                manual_override[reed] = True
            return jsonify({"message": f"Channel {channel} set to {state.upper()}"})
        elif channel_type == 'relays':
            if not h:
                logging.error("toggle called but GPIO not initialized")
                return jsonify({"error": "GPIO not initialized"}), 503
            try:
                channel_idx = int(channel)
            except (ValueError, TypeError):
                logging.error(f"Invalid channel format: {channel}")
                return jsonify({"error": "Channel must be an integer"}), 400
            if str(channel_idx) not in config['channels']['relays']:
                logging.error(f"Relay channel {channel_idx} not in config")
                return jsonify({"error": f"Relay channel {channel_idx} not configured"}), 400
            lgpio.gpio_write(h, channel_idx, 0 if state == 'on' else 1)
            config['relay_states'][str(channel_idx)] = 1 if state == 'on' else 0
            save_relay_states(config['relay_states'])
            logging.debug(f"Set relay channel {channel_idx} to {state.upper()}")
            return jsonify({"message": f"Relay {channel} set to {state.upper()}"})
    except Exception as e:
        logging.error(f"Error in toggle: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/activate_scene', methods=['POST'])
def activate_scene():
    global current_scene
    try:
        if not arduino_available:
            logging.warning("activate_scene called but Arduino not detected")
        data = request.json
        scene_name = data['scene']
        scene = config['scenes'][scene_name]
        target_pwm = {}
        scene_arduino = scene.get('arduino', {})
        for channel, brightness in scene_arduino.items():
            if int(brightness) > 0 and channel in reed_linked_channels:
                continue
            target_pwm[channel] = int(brightness * 255 / 100)
        # Enforce mutual exclusivity and auto green
        if '2' in target_pwm and target_pwm['2'] > 0:
            target_pwm['1'] = 0
            target_pwm['3'] = int(target_pwm['2'] * GREEN_FACTOR)
        elif '1' in target_pwm and target_pwm['1'] > 0:
            target_pwm['2'] = 0
            target_pwm['3'] = 0
        if '9' in target_pwm and target_pwm['9'] > 0:
            target_pwm['8'] = 0
            target_pwm['10'] = int(target_pwm['9'] * GREEN_FACTOR)
        elif '8' in target_pwm and target_pwm['8'] > 0:
            target_pwm['9'] = 0
            target_pwm['10'] = 0
        channels_to_set = list(target_pwm.keys())
        if arduino_available:
            for channel in sorted(channels_to_set):
                target = target_pwm.get(channel, 0)
                if not set_arduino_pwm(int(channel), target, ramp_time=1000):
                    logging.error(f"Failed to set channel {channel} during scene activation")
            time.sleep(1.5)
            for channel in channels_to_set:
                current = get_arduino_pwm(int(channel))
                target = target_pwm.get(channel, 0)
                if current is None or abs(current - target) > 5:
                    logging.error(f"Final verification failed for channel {channel}: current {current}, target {target}")
        for pin_str in config['reed_switches']:
            trigger_channels = set(ch.split(':')[1] for ch in config['reed_switches'][pin_str].get('trigger_channels', []) if ch.startswith('arduino:'))
            if trigger_channels & set(target_pwm.keys()):
                manual_override[pin_str] = True
        if scene_name in ['evening', 'night']:
            current_scene = scene_name
        else:
            current_scene = None
        config['relay_states'] = config.get('relay_states', {})
        if h:
            for pin, state in scene.get('relays', {}).items():
                if pin in config['channels']['relays']:
                    lgpio.gpio_write(h, int(pin), 1 if state == 0 else 0)
                    config['relay_states'][pin] = state
            for pin in config['channels']['relays']:
                if pin not in scene.get('relays', {}):
                    lgpio.gpio_write(h, int(pin), 1)
                    config['relay_states'][pin] = 0
            save_relay_states(config['relay_states'])
        else:
            logging.error("GPIO not initialized")
            return jsonify({"error": "GPIO not initialized"}), 503
        return jsonify({"message": f"Scene {scene_name} activated"})
    except Exception as e:
        logging.error(f"Error in activate_scene: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/get_arduino_states', methods=['GET'])
def get_arduino_states():
    try:
        if not arduino_available:
            logging.error("get_arduino_states called but Arduino not detected")
            return jsonify({"error": "Arduino not detected"}), 503
        states = {}
        with serial_lock:
            try:
                ser_arduino.flushInput()
                ser_arduino.flushOutput()
                time.sleep(0.05)
                ser_arduino.write(b'B\n')
                response = ser_arduino.readline().decode().strip()
                values = response.split()
                if len(values) == 12 and all(v.isdigit() for v in values):
                    for i, val in enumerate(values, 1):
                        brightness = int(round(int(val) / 255 * 100)) if val else 0
                        states[str(i)] = brightness
                else:
                    logging.error(f"Invalid batch response: {response}")
                    return jsonify({"error": "Invalid response"}), 500
            except Exception as e:
                logging.error(f"Error in get_arduino_states: {e}")
                return jsonify({"error": str(e)}), 500
        return jsonify(states)
    except Exception as e:
        logging.error(f"Error in get_arduino_states: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/get_relay_states', methods=['GET'])
def get_relay_states():
    try:
        if not h:
            logging.error("get_relay_states called but GPIO not initialized")
            return jsonify({"error": "GPIO not initialized"}), 503
        states = {}
        for pin in config['channels']['relays']:
            try:
                gpio_state = lgpio.gpio_read(h, int(pin))
                states[pin] = 1 if gpio_state == 0 else 0
            except Exception as e:
                logging.error(f"Error reading relay pin {pin}: {e}")
                states[pin] = config['relay_states'].get(pin, 0)
        return jsonify(states)
    except Exception as e:
        logging.error(f"Error in get_relay_states: {e}")
        return jsonify({"error": str(e)}), 500
        
@app.route('/get_active_scene', methods=['GET'])
def get_active_scene():
    return jsonify({"active_scene": current_scene})

@app.route('/get_data', methods=['GET'])
def get_data():
    global sun_times_cache, current_time_cache
    try:
        temperature = get_ds18b20_temperature()
        battery_voltage = get_battery_voltage()
        tank_level = get_tank_level()
        solar_current = get_solar_current()
        battery_current = get_battery_current()
        current_time = datetime.now(pytz.UTC)
        recalculate = False
        if sun_times_cache["last_calculated"] is None or (current_time - sun_times_cache["last_calculated"]).total_seconds() > 3600:
            recalculate = True
        if gps_data["latitude"] and gps_data["longitude"]:
            if sun_times_cache["last_latitude"] is None or abs(gps_data["latitude"] - sun_times_cache["last_latitude"]) > 0.1 or abs(gps_data["longitude"] - sun_times_cache["last_longitude"]) > 0.1:
                recalculate = True
        if recalculate and gps_data["fix"] == "Yes" and gps_data["latitude"] and gps_data["longitude"]:
            local_tz_str = get_local_tz_str()
            local_tz = pytz.timezone(local_tz_str)
            location = LocationInfo(
                name="Current Location",
                region="Unknown",
                timezone=local_tz_str,
                latitude=gps_data["latitude"],
                longitude=gps_data["longitude"]
            )
            today = date.today()
            s = sun(location.observer, date=today, tzinfo=local_tz)
            sun_times_cache.update({
                "sunrise": s["sunrise"].strftime("%I:%M %p").lstrip("0"),
                "sunset": s["sunset"].strftime("%I:%M %p").lstrip("0"),
                "last_calculated": current_time,
                "last_latitude": gps_data["latitude"],
                "last_longitude": gps_data["longitude"]
            })
        data = {
            "temperature": str(temperature) if temperature is not None else "Error",
            "battery_level": f"{battery_voltage}V" if battery_voltage is not None else "Error",
            "tank_level": f"{tank_level}" if tank_level is not None else "Error",
            "sunrise": sun_times_cache["sunrise"] or "---",
            "sunset":sun_times_cache["sunset"] or "---",
            "current_datetime": current_time_cache["time"] or "---",
            "gps_fix": gps_data["fix"],
            "gps_quality": gps_data["quality"],
            "latitude": gps_data["latitude"],
            "longitude": gps_data["longitude"],
            "solar_output": f"{solar_current:.1f}A" if solar_current is not None else "Error"
        }
        if battery_current is not None:
            if battery_current >= 0:
                data["battery_label"] = "Battery Output"
                data["battery_current"] = f"{battery_current:.1f}A"
            else:
                data["battery_label"] = "Battery Input"
                data["battery_current"] = f"{abs(battery_current):.1f}A"
        else:
            data["battery_label"] = "Battery Output"
            data["battery_current"] = "Error"
        if h:
            # Hard-code only storage_panel and rear_drawer
            data['storage_panel'] = "Open" if lgpio.gpio_read(h, 24) else "Closed"
            data['rear_drawer'] = "Open" if lgpio.gpio_read(h, 25) else "Closed"
            data['kitchen_bench'] = "Open" if lgpio.gpio_read(h, 12) else "Closed"
        else:
            data['storage_panel'] = "Unknown"
            data['rear_drawer'] = "Unknown"
            data['kitchen_bench'] = "Unknown"
        return jsonify(data)
    except Exception as e:
        logging.error(f"Error in get_data: {e}")
        return jsonify({}), 500

@app.route('/shutdown', methods=['POST'])
def shutdown():
    try:
        data = request.json or {}
        if data.get('token') != SHUTDOWN_TOKEN:
            return jsonify({"error": "Unauthorized"}), 403
        display_pi_user = "pi"
        display_pi_ip = "10.10.10.20"
        ssh_key = "/home/pi/.ssh/id_rsa_shutdown"
        try:
            subprocess.run([
                "ssh", "-i", ssh_key, f"{display_pi_user}@{display_pi_ip}",
                "sudo", "shutdown", "now"
            ], check=True, timeout=10)
            logging.info("Sent shutdown command to display-pi")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logging.warning(f"Failed to shut down display-pi: {e}")
        cleanup_gpio()
        threading.Thread(target=lambda: [
            time.sleep(2),
            subprocess.run(['sudo', 'shutdown', 'now'], check=True)
        ], daemon=True).start()
        return jsonify({"message": "Both systems are shutting down"})
    except Exception as e:
        logging.error(f"Error in shutdown: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/save_config', methods=['POST'])
def save_config():
    try:
        config_data = request.json
        config_path = 'config.json'
        if not os.access(config_path, os.W_OK):
            logging.error(f"No write permissions for {config_path}")
            return jsonify({"error": "Cannot write to config file"}), 500
        with open(config_path, 'r') as f:
            current_config = json.load(f)
        if 'theme' not in current_config:
            current_config['theme'] = {
                "darkMode": "off",
                "autoTheme": "off",
                "autoBrightness": "off",
                "defaultTheme": "light",
                "screen_brightness": "medium"
            }
        old_offset = current_config.get('evening_offset', 60)
        old_night = current_config.get('night_time', '20:00')
        new_theme = {
            "darkMode": config_data.get('theme', {}).get('darkMode', current_config['theme'].get('darkMode', 'off')),
            "autoTheme": config_data.get('theme', {}).get('autoTheme', current_config['theme'].get('autoTheme', 'off')),
            "autoBrightness": config_data.get('theme', {}).get('autoBrightness', current_config['theme'].get('autoBrightness', 'off')),
            "defaultTheme": config_data.get('theme', {}).get('defaultTheme', current_config['theme'].get('defaultTheme', 'light')),
            "screen_brightness": config_data.get('theme', {}).get('screen_brightness', current_config['theme'].get('screen_brightness', 'medium'))
        }
        current_config['theme'] = new_theme
        if 'scenes' in config_data:
            current_config['scenes'] = config_data['scenes']
        for key in ['channels', 'reed_switches', 'relay_states']:
            if key in config_data:
                current_config[key] = config_data[key]
        current_config['evening_offset'] = config_data.get('evening_offset', current_config.get('evening_offset', 60))
        current_config['night_time'] = config_data.get('night_time', current_config.get('night_time', '20:00'))
        write_config_atomically(current_config, config_path)
        config.update(current_config)
        if current_config.get('evening_offset', 60) != old_offset or current_config.get('night_time', '20:00') != old_night:
            check_auto_scenes()
        logging.info("Saved config")
        return jsonify({"message": "Config saved"})
    except Exception as e:
        logging.error(f"Error saving config: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/load_config', methods=['GET'])
def load_config():
    try:
        config_path = 'config.json'
        if not os.access(config_path, os.R_OK):
            logging.error(f"No read permissions for {config_path}")
            return jsonify({}), 500
        with open(config_path, 'r') as f:
            config_data = json.load(f)
        logging.info("Loaded full config")
        return jsonify(config_data)
    except Exception as e:
        logging.error(f"Error in load_config: {e}")
        return jsonify({}), 500

@app.route('/get_scenes', methods=['GET'])
def get_scenes():
    try:
        config_path = 'config.json'
        if not os.access(config_path, os.R_OK):
            logging.error(f"No read permissions for {config_path}")
            return jsonify({}), 500
        with open(config_path, 'r') as f:
            config_data = json.load(f)
        scenes = config_data.get('scenes', {})
        return jsonify(scenes)
    except Exception as e:
        logging.error(f"Error in get_scenes: {e}")
        return jsonify({}), 500

@app.route('/set_screen_brightness', methods=['POST'])
def set_screen_brightness():
    try:
        data = request.json
        brightness_level = data.get('brightness')
        auto_brightness = config['theme'].get('auto_brightness', 'off')
        brightness_map = {'low': 25, 'medium': 127, 'high': 255}
        if brightness_level not in brightness_map:
            logging.error(f"Invalid brightness level: {brightness_level}")
            return jsonify({"error": "Invalid brightness level"}), 400
        brightness_value = brightness_map[brightness_level]
        display_pi_user = "pi"
        display_pi_ip = "10.10.10.20"
        ssh_key = "/home/pi/.ssh/id_rsa_shutdown"
        ssh_command = f"echo {brightness_value} | sudo tee /sys/class/backlight/*/brightness"
        try:
            subprocess.run([
                "ssh", "-i", ssh_key, f"{display_pi_user}@{display_pi_ip}",
                ssh_command
            ], check=True, timeout=10, capture_output=True, text=True)
            logging.info(f"Set display-pi brightness to {brightness_level}")
            return jsonify({"message": f"Brightness set to {brightness_level}"})
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logging.error(f"Failed to set brightness: {e}")
            return jsonify({"error": f"Failed to set brightness: {str(e)}"}), 500
    except Exception as e:
        logging.error(f"Error in set_screen_brightness: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    try:
        logging.info("Starting Flask app on port 5000")
        app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
    except Exception as e:
        logging.error(f"Error starting Flask app: {e}")
        cleanup_gpio()
        raise