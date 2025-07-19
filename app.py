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
from datetime import datetime, date
import pytz
import subprocess
import threading

# Global serial lock
serial_lock = threading.Lock()
import os
from w1thermsensor import W1ThermSensor, NoSensorFoundError, SensorNotReadyError
import tempfile

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
            return False
    except Exception as e:
        logging.error(f"Serial init failed: {e}")
        return False

# Sensor caches
last_battery_voltage = last_battery_voltage_time = None
last_tank_level = last_tank_level_time = None
last_temperature = last_temperature_time = None
CACHE_DURATION = 10

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
    if not (0 <= pin <= 1):
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
        V_REF = 4.98
        a0_voltage = (raw_value / 1023.0) * V_REF
        logging.debug(f"Voltage at A0: {a0_voltage:.2f}V")
        SCALING_FACTOR = 13.02 / 2.686
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
        v_in = 4.98
        v_out = (raw_value / 1023.0) * v_in
        logging.debug(f"Voltage at A1: {v_out:.2f}V")
        if v_out < 0.5 or v_out > 3.0:
            logging.warning(f"Tank level sensor fault: V_out={v_out:.3f}V")
            last_tank_level = None
            last_tank_level_time = current_time
            return None
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
                if not current_time_cache["time"]:
                    system_time = datetime.now(pytz.timezone("Australia/Melbourne"))
                    current_time_cache["time"] = system_time.strftime("%A %B %d %Y %I:%M %p %Z").lstrip("0").replace(" 0", " ") + "*"
                    current_time_cache["last_updated"] = datetime.now(pytz.UTC)
                    current_time_cache["using_gps"] = False
                if not sun_times_cache["sunrise"]:
                    local_tz = pytz.timezone("Australia/Melbourne")
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
                            local_dt = utc_dt.astimezone(pytz.timezone("Australia/Melbourne"))
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
                "screenBrightness": "medium"
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
                    "state": "open",
                    "trigger_channels": ["arduino:1", "arduino:2", "arduino:3"],
                    "display": False
                },
                "24": {
                    "name": "Storage Panel",
                    "type": "sensor",
                    "state": "closed",
                    "trigger_channels": ["arduino:5", "arduino:6"],
                    "display": True
                },
                "25": {
                    "name": "Rear Drawer",
                    "type": "sensor",
                    "state": "closed",
                    "trigger_channels": ["arduino:8"],
                    "display": True
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
            "screenBrightness": "medium"
        }
    if 'channels' not in config:
        config['channels'] = {"arduino": {}, "relays": {}}
    if 'arduino' not in config['channels']:
        config['channels']['arduino'] = {}
    if 'relays' not in config['channels']:
        config['channels']['relays'] = {}
    if 'scenes' not in config:
        config['scenes'] = {}
    if 'reed_switches' not in config:
        config['reed_switches'] = {
            "23": {
                "name": "Kitchen Panel",
                "type": "sensor",
                "state": "open",
                "trigger_channels": ["arduino:1", "arduino:2", "arduino:3"],
                "display": False
            },
            "24": {
                "name": "Storage Panel",
                "type": "sensor",
                "state": "closed",
                "trigger_channels": ["arduino:5", "arduino:6"],
                "display": True
            },
            "25": {
                "name": "Rear Drawer",
                "type": "sensor",
                "state": "closed",
                "trigger_channels": ["arduino:8"],
                "display": True
            }
        }
    if 'relay_states' not in config:
        config['relay_states'] = {}
    write_config_atomically(config, config_path)
    logging.info("Loaded and validated config")
except Exception as e:
    logging.error(f"Error loading config.json: {e}")
    config = {
        "theme": {
            "darkMode": "off",
            "autoTheme": "off",
            "autoBrightness": "off",
            "defaultTheme": "light",
            "screenBrightness": "medium"
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
                "state": "open",
                "trigger_channels": ["arduino:1", "arduino:2", "arduino:3"],
                "display": False
            },
            "24": {
                "name": "Storage Panel",
                "type": "sensor",
                "state": "closed",
                "trigger_channels": ["arduino:5", "arduino:6"],
                "display": True
            },
            "25": {
                "name": "Rear Drawer",
                "type": "sensor",
                "state": "closed",
                "trigger_channels": ["arduino:8"],
                "display": True
            }
        },
        "relay_states": {}
    }
    write_config_atomically(config, config_path)
    logging.info("Created fallback config.json")

def check_arduino_alive():
    if not arduino_available:
        return False
    try:
        ser_arduino.write(b'P\n')
        response = ser_arduino.readline().decode().strip()
        return response == 'AA'
    except Exception as e:
        logging.error(f"Alive check failed: {e}")
        return False

def monitor_arduino():
    global arduino_available
    failure_count = 0
    MAX_FAILURES = 3
    while True:
        if not check_arduino_alive():
            failure_count += 1
            logging.warning(f"Arduino unresponsive (failure {failure_count}/{MAX_FAILURES})")
            if failure_count >= MAX_FAILURES:
                arduino_available = False
                logging.error("Arduino offline - disabling features")
        else:
            if not arduino_available:
                logging.info("Arduino back online")
                arduino_available = True
            failure_count = 0
        time.sleep(30)  # Check every 30s

GREEN_FACTOR = 0.1  # Green PWM = % of red for red-orange mix

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
                if response.isdigit():
                    read_value = int(response)
                    if abs(read_value - value) <= 5:
                        logging.debug(f"Set and verified Arduino channel {channel} to PWM {value} (attempt {attempt+1})")
                        return True
                    else:
                        logging.warning(f"PWM verification failed on attempt {attempt+1}: set {value}, read {read_value}")
                else:
                    logging.warning(f"Non-digit response on attempt {attempt+1}: {response}")
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

def check_initial_reed_states():
    if h is None:
        logging.error("GPIO not initialized")
        return {}
    initial_states = {}
    for pin_str, switch_info in config['reed_switches'].items():
        pin = int(pin_str)
        try:
            initial_state = lgpio.gpio_read(h, pin)
            state_str = "closed" if initial_state == 0 else "open"
            logging.info(f"Initial state for {switch_info['name']}: {state_str}")
            config['reed_switches'][pin_str]['state'] = state_str
            initial_states[pin] = initial_state

            # Kitchen-specific screen and light control
            if pin == 23:
                display_pi_user = "pi"
                display_pi_ip = "10.10.10.20"
                ssh_key = "/home/pi/.ssh/id_rsa_shutdown"
                if initial_state == 0:  # Closed
                    command = ["xset", "dpms", "force", "off"]
                    action_desc = "screen off"
                    brightness_value = None
                    # Turn off kitchen lights
                    set_arduino_pwm(1, 0, ramp_time=1000)
                    set_arduino_pwm(2, 0, ramp_time=1000)
                    set_arduino_pwm(3, 0, ramp_time=1000)
                else:  # Open
                    command = ["xdotool", "key", "Shift"]
                    action_desc = "screen wake"
                    brightness_level = config['theme'].get('screenBrightness', 'medium')
                    brightness_map = {'low': 25, 'medium': 127, 'high': 255}
                    brightness_value = brightness_map.get(brightness_level, 127)
                    # Compute and set kitchen lights based on time
                    local_tz = pytz.timezone("Australia/Melbourne")
                    current_local = datetime.now(local_tz)
                    if gps_data["fix"] == "Yes" and gps_data["latitude"] and gps_data["longitude"]:
                        loc = LocationInfo("Current", "", "Australia/Melbourne", gps_data["latitude"], gps_data["longitude"])
                    else:
                        loc = MELBOURNE_LOCATION
                    today = current_local.date()
                    s = sun(loc.observer, date=today, tzinfo=local_tz)
                    sunrise = s["sunrise"]
                    sunset = s["sunset"]
                    ten_pm = current_local.replace(hour=22, minute=0, second=0, microsecond=0)
                    white_pwm = 0
                    red_pwm = 0
                    if sunrise <= current_local < sunset:
                        white_pwm = 255
                    else:
                        if sunset <= current_local < ten_pm:
                            red_pwm = 255
                        else:
                            red_pwm = int(0.3 * 255)
                    green_pwm = int(red_pwm * GREEN_FACTOR)
                    set_arduino_pwm(1, white_pwm, ramp_time=1000)
                    set_arduino_pwm(2, red_pwm, ramp_time=1000)
                    set_arduino_pwm(3, green_pwm, ramp_time=1000)
                max_attempts = 3
                retry_interval = 10
                for attempt in range(max_attempts):
                    if send_ssh_display_command(display_pi_user, display_pi_ip, ssh_key, command, action_desc, brightness_value):
                        break
                    logging.warning(f"SSH attempt {attempt + 1}/{max_attempts} failed")
                    time.sleep(retry_interval)
                else:
                    logging.error("All SSH attempts failed")

            # For storage and rear drawer, set initial lights based on state
            elif pin in [24, 25]:
                trigger_channels = switch_info.get('trigger_channels', [])
                target_pwm = 255 if initial_state == 1 else 0  # Open: on, Closed: off
                for ch in trigger_channels:
                    if ch.startswith('arduino:'):
                        channel_idx = int(ch.split(':')[1])
                        if not set_arduino_pwm(channel_idx, target_pwm, ramp_time=1000):
                            logging.error(f"Failed to set initial PWM for channel {channel_idx} to {target_pwm}")
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
                config['reed_switches'][str(pin)]['state'] = state_str

                # Kitchen-specific: control screen and lights
                if pin == 23:
                    display_pi_user = "pi"
                    display_pi_ip = "10.10.10.20"
                    ssh_key = "/home/pi/.ssh/id_rsa_shutdown"
                    if current_read == 0:  # Closed
                        command = ["xset", "dpms", "force", "off"]
                        action_desc = "screen off"
                        brightness_value = None
                        # Turn off kitchen lights
                        set_arduino_pwm(1, 0, ramp_time=1000)
                        set_arduino_pwm(2, 0, ramp_time=1000)
                        set_arduino_pwm(3, 0, ramp_time=1000)
                    else:  # Open
                        command = ["xdotool", "key", "Shift"]
                        action_desc = "screen wake"
                        brightness_level = config['theme'].get('screenBrightness', 'medium')
                        brightness_map = {'low': 25, 'medium': 127, 'high': 255}
                        brightness_value = brightness_map.get(brightness_level, 127)
                        # Compute and set kitchen lights based on time
                        local_tz = pytz.timezone("Australia/Melbourne")
                        current_local = datetime.now(local_tz)
                        if gps_data["fix"] == "Yes" and gps_data["latitude"] and gps_data["longitude"]:
                            loc = LocationInfo("Current", "", "Australia/Melbourne", gps_data["latitude"], gps_data["longitude"])
                        else:
                            loc = MELBOURNE_LOCATION
                        today = current_local.date()
                        s = sun(loc.observer, date=today, tzinfo=local_tz)
                        sunrise = s["sunrise"]
                        sunset = s["sunset"]
                        ten_pm = current_local.replace(hour=22, minute=0, second=0, microsecond=0)
                        white_pwm = 0
                        red_pwm = 0
                        if sunrise <= current_local < sunset:
                            white_pwm = 255
                        else:
                            if sunset <= current_local < ten_pm:
                                red_pwm = 255
                            else:
                                red_pwm = int(0.3 * 255)
                        green_pwm = int(red_pwm * GREEN_FACTOR)
                        set_arduino_pwm(1, white_pwm, ramp_time=1000)
                        set_arduino_pwm(2, red_pwm, ramp_time=1000)
                        set_arduino_pwm(3, green_pwm, ramp_time=1000)
                    if send_ssh_display_command(display_pi_user, display_pi_ip, ssh_key, command, action_desc, brightness_value):
                        last_state = current_read

                # Storage and rear drawer: control lights
                else:
                    trigger_channels = switch_info.get('trigger_channels', [])
                    target_pwm = 255 if current_read == 1 else 0  # Open: on, Closed: off
                    success = True
                    for ch in trigger_channels:
                        if ch.startswith('arduino:'):
                            channel_idx = int(ch.split(':')[1])
                            if not set_arduino_pwm(channel_idx, target_pwm, ramp_time=1000):
                                logging.error(f"Failed to set PWM for channel {channel_idx} to {target_pwm}")
                                success = False
                    if success:
                        last_state = current_read

            time.sleep(0.5)
        except Exception as e:
            logging.error(f"Error monitoring reed switch pin {pin}: {e}")
            time.sleep(5)

# Initialize GPIO
init_gpio()

# Serial init after GPIO
arduino_available = init_serial()

# Perform initial reed switch checks for all
initial_states = check_initial_reed_states()

# Start monitoring threads for all reed switches
for pin_str in config['reed_switches']:
    pin = int(pin_str)
    initial_state = initial_states.get(pin, None)
    if initial_state is not None:
        thread = threading.Thread(target=monitor_reed_switch, args=(pin, initial_state), daemon=True)
        thread.start()

# Start GPS thread
gps_thread = threading.Thread(target=update_gps_data, daemon=True)
gps_thread.start()

if arduino_available:
    arduino_monitor_thread = threading.Thread(target=monitor_arduino, daemon=True)
    arduino_monitor_thread.start()

@app.route('/')
def index():
    try:
        return render_template('index.html',
                              scenes=config['scenes'].keys(),
                              arduino_channels=config['channels']['arduino'],
                              relay_channels=config['channels']['relays'],
                              reed_switches=config['reed_switches'],
                              arduino_available=arduino_available)
    except Exception as e:
        logging.error(f"Error rendering index: {e}")
        return f"Error rendering page: {e}", 500

@app.route('/set_brightness', methods=['POST'])
def set_brightness():
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

        # Use ramping via Arduino with 1-second total duration
        if not set_arduino_pwm(channel_idx, target_pwm, ramp_time=1000):
            logging.error(f"Failed to set PWM for channel {channel_idx} to {target_pwm}")
            return jsonify({"error": "Failed to set PWM"}), 500

        if channel_idx == 2:
            green_value = int(target_pwm * GREEN_FACTOR)
            if not set_arduino_pwm(3, green_value, ramp_time=1000):
                logging.warning(f"Failed to auto-set green channel 3 to {green_value}")

        # Optional final verification
        final_pwm = get_arduino_pwm(channel_idx)
        if final_pwm is None or abs(final_pwm - target_pwm) > 10:
            logging.error(f"PWM verification failed for channel {channel_idx}: expected {target_pwm}, got {final_pwm}")
            return jsonify({"error": "PWM verification failed"}), 500
        logging.debug(f"Successfully set channel {channel_idx} to PWM {final_pwm}")
        return jsonify({"message": f"Brightness set to {brightness}%"})
    except Exception as e:
        logging.error(f"Error in set_brightness: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/toggle', methods=['POST'])
def toggle():
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

            if channel_idx == 2:
                green_value = int(target_pwm * GREEN_FACTOR)
                if not set_arduino_pwm(3, green_value):
                    logging.warning(f"Failed to auto-set green channel 3 to {green_value}")

            final_pwm = get_arduino_pwm(channel_idx)
            if final_pwm is None or abs(final_pwm - target_pwm) > 10:
                logging.error(f"PWM verification failed for channel {channel_idx}: expected {target_pwm}, got {final_pwm}")
                return jsonify({"error": "PWM verification failed"}), 500
            logging.debug(f"Successfully set channel {channel_idx} to PWM {final_pwm}")
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
    try:
        if not arduino_available:
            logging.warning("activate_scene called but Arduino not detected")
        data = request.json
        scene_name = data['scene']
        scene = config['scenes'][scene_name]
        target_pwm = {ch: 0 for ch in config['channels']['arduino']}
        for channel, brightness in scene.get('arduino', {}).items():
            if channel in config['channels']['arduino']:
                target_pwm[channel] = int(brightness * 255 / 100)
        if '2' in config['channels']['arduino']:
            target_pwm['3'] = int(target_pwm.get('2', 0) * GREEN_FACTOR)
        if arduino_available:
            # Batch ramp all Arduino channels to their targets (or 0) over 1s for simultaneous starts
            with serial_lock:
                ser_arduino.flushInput()
                ser_arduino.flushOutput()
                time.sleep(0.05)  # Single settle time for all channels
                channels_to_set = list(config['channels']['arduino'].keys())
                # Send all ramp commands with small delay to pace processing
                for channel in channels_to_set:
                    channel_idx = int(channel)
                    target = target_pwm.get(channel, 0)
                    ser_arduino.write(f'R{channel_idx} {target} 1000\n'.encode())
                    time.sleep(0.02)  # Pace sends to avoid overwhelming Arduino parser/buffer
                # Read all responses (echoed targets) in order, with retry for empties
                for channel in channels_to_set:
                    target = target_pwm.get(channel, 0)
                    response = ser_arduino.readline().decode().strip()
                    if not response:  # If empty, try one more read (delayed line)
                        logging.warning(f"Empty response for channel {channel}, retrying readline")
                        response = ser_arduino.readline().decode().strip()
                    if response.isdigit():
                        read_value = int(response)
                        if read_value != target:
                            logging.warning(f"Batch ramp echo mismatch for channel {channel}: expected {target}, got {read_value}")
                    else:
                        logging.warning(f"Invalid batch ramp response for channel {channel}: {response}")
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

@app.route('/get_data', methods=['GET'])
def get_data():
    global sun_times_cache, current_time_cache
    try:
        temperature = get_ds18b20_temperature()
        battery_voltage = get_battery_voltage()
        tank_level = get_tank_level()
        current_time = datetime.now(pytz.UTC)
        recalculate = False
        if sun_times_cache["last_calculated"] is None or (current_time - sun_times_cache["last_calculated"]).total_seconds() > 3600:
            recalculate = True
        if gps_data["latitude"] and gps_data["longitude"]:
            if sun_times_cache["last_latitude"] is None or abs(gps_data["latitude"] - sun_times_cache["last_latitude"]) > 0.1 or abs(gps_data["longitude"] - sun_times_cache["last_longitude"]) > 0.1:
                recalculate = True
        if recalculate and gps_data["fix"] == "Yes" and gps_data["latitude"] and gps_data["longitude"]:
            local_tz = pytz.timezone("Australia/Melbourne")
            location = LocationInfo(
                name="Current Location",
                region="Unknown",
                timezone="UTC",
                latitude=gps_data["latitude"],
                longitude=gps_data["longitude"]
            )
            today = date.today()
            s = sun(location.observer, date=today, tzinfo=local_tz)
            sun_times_cache.update({
                "sunrise": s["sunrise"].astimezone(local_tz).strftime("%I:%M %p").lstrip("0"),
                "sunset": s["sunset"].astimezone(local_tz).strftime("%I:%M %p").lstrip("0"),
                "last_calculated": current_time,
                "last_latitude": gps_data["latitude"],
                "last_longitude": gps_data["longitude"]
            })
        data = {
            "temperature": str(temperature) if temperature is not None else "Error",
            "battery_level": f"{battery_voltage}V" if battery_voltage is not None else "Error",
            "tank_level": f"{tank_level}" if tank_level is not None else "Error",
            "sunrise": sun_times_cache["sunrise"] or "---",
            "sunset": sun_times_cache["sunset"] or "---",
            "current_datetime": current_time_cache["time"] or "---",
            "gps_fix": gps_data["fix"],
            "gps_quality": gps_data["quality"],
            "latitude": gps_data["latitude"],
            "longitude": gps_data["longitude"]
        }
        if h:
            for pin, switch_info in config['reed_switches'].items():
                name = switch_info['name'].lower().replace(" ", "_")
                state = "Open" if lgpio.gpio_read(h, int(pin)) else "Closed"
                data[name] = state
        else:
            for pin, switch_info in config['reed_switches'].items():
                name = switch_info['name'].lower().replace(" ", "_")
                data[name] = "Unknown"
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
                "screenBrightness": "medium"
            }
        new_theme = {
            "darkMode": config_data.get('theme', {}).get('darkMode', current_config['theme'].get('darkMode', 'off')),
            "autoTheme": config_data.get('theme', {}).get('autoTheme', current_config['theme'].get('autoTheme', 'off')),
            "autoBrightness": config_data.get('theme', {}).get('autoBrightness', current_config['theme'].get('autoBrightness', 'off')),
            "defaultTheme": config_data.get('theme', {}).get('defaultTheme', current_config['theme'].get('defaultTheme', 'light')),
            "screenBrightness": config_data.get('theme', {}).get('screenBrightness', current_config['theme'].get('screenBrightness', 'medium'))
        }
        current_config['theme'] = new_theme
        if 'scenes' in config_data:
            current_config['scenes'] = config_data['scenes']
        for key in ['channels', 'reed_switches', 'relay_states']:
            if key in config_data:
                current_config[key] = config_data[key]
        write_config_atomically(current_config, config_path)
        config.update(current_config)
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
            return jsonify({
                "theme": {
                    "darkMode": "off",
                    "autoTheme": "off",
                    "autoBrightness": "off",
                    "defaultTheme": "light",
                    "screenBrightness": "medium"
                },
                "screenBrightness": "medium"
            }), 500
        with open(config_path, 'r') as f:
            config_data = json.load(f)
        theme = config_data.get('theme', {
            "darkMode": "off",
            "autoTheme": "off",
            "autoBrightness": "off",
            "defaultTheme": "light",
            "screenBrightness": "medium"
        })
        screen_brightness = theme.get('screen brightness', 'medium')
        response = {
            "theme": {
                "darkMode": theme.get("darkMode", "off"),
                "autoTheme": theme.get("autoTheme", "off"),
                "autoBrightness": theme.get("autoBrightness", "off"),
                "defaultTheme": theme.get("defaultTheme", "light"),
                "screenBrightness": screen_brightness
            },
            "screenBrightness": screen_brightness
        }
        logging.info("Loaded config")
        return jsonify(response)
    except Exception as e:
        logging.error(f"Error in load_config: {e}")
        return jsonify({
            "theme": {
                "darkMode": "off",
                "autoTheme": "off",
                "autoBrightness": "off",
                "defaultTheme": "light",
                "screenBrightness": "medium"
            },
            "screenBrightness": "medium"
        }), 500

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
        auto_brightness = config['theme'].get('autoBrightness', 'off')
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