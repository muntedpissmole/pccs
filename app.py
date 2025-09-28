# app.py
import json
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import threading
import time as time_module
import math
from datetime import datetime, timedelta
import logging
import os
from logging.handlers import RotatingFileHandler

# Configure logging
if not os.path.exists('logs'):
    os.makedirs('logs')
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler('logs/app.log', maxBytes=100000, backupCount=5)
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
socketio = SocketIO(app)
from modules.arduino import ArduinoController
from modules.gps import GPSController
from modules.weather import WeatherController
from modules.gpio import GPIOController
from modules.config import ConfigManager
from modules.phases import PhaseManager
from modules.reeds import ReedsController
def handle_event(event, data):
    logger.debug(f"Handling event: {event} with data: {data}")
    socketio.emit(event, data)
last_gps_data = {}
base_gps_datetime = None
last_sync_time = None
has_gps_fix = False
def broadcast_gps(data):
    global last_gps_data, base_gps_datetime, last_sync_time, has_gps_fix
    if 'has_fix' in data:
        has_gps_fix = data['has_fix']
    if has_gps_fix and 'gps_datetime_str' in data:
        try:
            new_gps_dt = datetime.strptime(data['gps_datetime_str'], '%Y-%m-%d %H:%M:%S')
            current_system = time_module.time()
            if base_gps_datetime is None:
                base_gps_datetime = new_gps_dt
                last_sync_time = current_system
            else:
                base_gps_datetime = new_gps_dt
                last_sync_time = current_system
        except ValueError as e:
            logger.error(f"Error parsing GPS datetime: {e}")
    last_gps_data.update(data)
    # Compute current time for broadcast
    current_system = time_module.time()
    if has_gps_fix and base_gps_datetime is not None:
        computed_dt = base_gps_datetime + timedelta(seconds=current_system - last_sync_time)
        hour = computed_dt.hour % 12 or 12
        minute = computed_dt.minute
        ampm = computed_dt.strftime('%p')
        last_gps_data['time'] = f"{hour}:{minute:02d} {ampm}"
        last_gps_data['date'] = computed_dt.strftime('%a %b %d')
    elif not has_gps_fix:
        last_gps_data['date'] = '---'
        last_gps_data['time'] = '---'
        last_gps_data['sunrise'] = '---'
        last_gps_data['sunset'] = '---'
        last_gps_data['satellites'] = '---'
        last_gps_data['location'] = '---'
        last_gps_data['weather'] = None
    socketio.emit('update_gps', last_gps_data)
weather = WeatherController(on_event=handle_event)
arduino = ArduinoController(on_event=handle_event)
gps = GPSController(on_event=handle_event, on_broadcast=broadcast_gps, weather=weather)
# Load static config from config.json
with open('config.json', 'r') as f:
    static_config = json.load(f)

def validate_static_config(config):
    required_top_keys = ['ramp_rate', 'scene_ramp_rate', 'scenes', 'ct_solar', 'ct_battery', 'reeds', 'lights', 'relays']
    for key in required_top_keys:
        if key not in config:
            raise ValueError(f"Missing required key '{key}' in config.json")
    
    # ramp_rate and scene_ramp_rate
    if not isinstance(config['ramp_rate'], (int, float)):
        raise ValueError("ramp_rate must be a number")
    if not isinstance(config['scene_ramp_rate'], (int, float)):
        raise ValueError("scene_ramp_rate must be a number")
    
    # scenes
    scenes = config['scenes']
    if not isinstance(scenes, dict):
        raise ValueError("scenes must be a dictionary")
    required_scenes = ['evening', 'night', 'bathroom', 'all off']
    for scene in required_scenes:
        if scene not in scenes:
            raise ValueError(f"Missing required scene '{scene}' in scenes")
    allowed_colors = ['white', 'red']  # Assuming based on usage
    for scene_name, scene_data in scenes.items():
        if not isinstance(scene_data, dict):
            raise ValueError(f"Scene '{scene_name}' must be a dictionary")
        for light_id_str, setting in scene_data.items():
            if not light_id_str.isdigit():
                raise ValueError(f"Light ID '{light_id_str}' in scene '{scene_name}' must be a digit string")
            if isinstance(setting, dict):
                if 'brightness' not in setting or not isinstance(setting['brightness'], (int, float)):
                    raise ValueError(f"Invalid or missing 'brightness' in setting for light '{light_id_str}' in scene '{scene_name}'")
                if 'color' not in setting or not isinstance(setting['color'], str) or setting['color'] not in allowed_colors:
                    raise ValueError(f"Invalid or missing 'color' in setting for light '{light_id_str}' in scene '{scene_name}'. Allowed: {allowed_colors}")
            elif not isinstance(setting, (int, float)):
                raise ValueError(f"Setting for light '{light_id_str}' in scene '{scene_name}' must be a number or a dict with 'brightness' and 'color'")
    
    # ct_solar and ct_battery
    for ct_key in ['ct_solar', 'ct_battery']:
        ct = config[ct_key]
        if not isinstance(ct, dict):
            raise ValueError(f"{ct_key} must be a dictionary")
        if 'zero_offset' not in ct or not isinstance(ct['zero_offset'], (int, float)):
            raise ValueError(f"Missing or invalid 'zero_offset' in {ct_key}")
        if 'sensitivity' not in ct or not isinstance(ct['sensitivity'], (int, float)):
            raise ValueError(f"Missing or invalid 'sensitivity' in {ct_key}")
    
    # reeds
    reeds = config['reeds']
    if not isinstance(reeds, dict):
        raise ValueError("reeds must be a dictionary")
    required_reed_phases = ['day', 'evening', 'night']
    for reed_name, reed_data in reeds.items():
        if not isinstance(reed_data, dict):
            raise ValueError(f"Reed '{reed_name}' must be a dictionary")
        if 'pin' not in reed_data or not isinstance(reed_data['pin'], int):
            raise ValueError(f"Missing or invalid 'pin' for reed '{reed_name}'")
        for phase in required_reed_phases:
            if phase not in reed_data:
                raise ValueError(f"Missing phase '{phase}' for reed '{reed_name}'")
            phase_data = reed_data[phase]
            if not isinstance(phase_data, dict):
                raise ValueError(f"Phase '{phase}' for reed '{reed_name}' must be a dictionary")
            # Allow empty for day, but if present, validate
            if phase_data:
                if 'channel' not in phase_data or not isinstance(phase_data['channel'], int):
                    raise ValueError(f"Missing or invalid 'channel' in phase '{phase}' for reed '{reed_name}'")
                if 'brightness' not in phase_data or not isinstance(phase_data['brightness'], (int, float)):
                    raise ValueError(f"Missing or invalid 'brightness' in phase '{phase}' for reed '{reed_name}'")
                if 'color' in phase_data and (not isinstance(phase_data['color'], str) or phase_data['color'] not in allowed_colors):
                    raise ValueError(f"Invalid 'color' in phase '{phase}' for reed '{reed_name}'. Allowed: {allowed_colors}")
    
    # lights
    lights = config['lights']
    if not isinstance(lights, dict):
        raise ValueError("lights must be a dictionary")
    for light_id_str, light_data in lights.items():
        if not light_id_str.isdigit():
            raise ValueError(f"Light ID '{light_id_str}' must be a digit string")
        if not isinstance(light_data, dict):
            raise ValueError(f"Light '{light_id_str}' must be a dictionary")
        if 'pin' in light_data:
            if not isinstance(light_data['pin'], int):
                raise ValueError(f"Invalid 'pin' for light '{light_id_str}'")
        else:
            required_color_pins = ['white_pin', 'red_pin']
            for pin_key in required_color_pins:
                if pin_key not in light_data or not isinstance(light_data[pin_key], int):
                    raise ValueError(f"Missing or invalid '{pin_key}' for light '{light_id_str}'")
            if 'green_pin' in light_data and not isinstance(light_data['green_pin'], int):
                raise ValueError(f"Invalid 'green_pin' for light '{light_id_str}'")
            if 'active' not in light_data or not isinstance(light_data['active'], str) or light_data['active'] not in allowed_colors:
                raise ValueError(f"Missing or invalid 'active' for light '{light_id_str}'. Allowed: {allowed_colors}")
        if 'description' in light_data and not isinstance(light_data['description'], str):
            raise ValueError(f"Invalid 'description' for light '{light_id_str}'")
    
    # relays
    relays = config['relays']
    if not isinstance(relays, dict):
        raise ValueError("relays must be a dictionary")
    for relay_name, pin in relays.items():
        if not isinstance(pin, int):
            raise ValueError(f"Invalid pin for relay '{relay_name}'")

try:
    validate_static_config(static_config)
    logger.info("Static config validated successfully")
except ValueError as e:
    logger.error(f"Static config validation failed: {e}")
    raise

gpio = GPIOController(on_event=handle_event, relays_config=static_config.get('relays', {}))
config_manager = ConfigManager()
config = config_manager.config
lights_config = static_config.get('lights', {})
states = {}
for lid_str, lconf in lights_config.items():
    lid = int(lid_str)
    state = {'brightness': 0}
    if 'pin' in lconf:
        state['pin'] = lconf['pin']
    else:
        state['white_pin'] = lconf['white_pin']
        state['red_pin'] = lconf['red_pin']
        if 'green_pin' in lconf:
            state['green_pin'] = lconf['green_pin']
        state['active'] = lconf.get('active', 'white')
    states[lid] = state
ramp_rate_ms = static_config.get('ramp_rate', 1) * 1000
scene_ramp_rate = static_config.get('scene_ramp_rate', 2)
gamma = config_manager.get('gamma', 2.5) # Keep gamma in dynamic config for potential future edits
def calculate_pwm(brightness):
    normalized = brightness / 100.0
    return int(math.pow(normalized, gamma) * 255)
def broadcast_states():
    response_states = {str(k): {'brightness': v['brightness'], 'active': v.get('active', None)} for k, v in states.items()}
    socketio.emit('update_states', response_states)
def find_matching_scene():
    scenes = static_config.get('scenes', {})
    for scene_id, scene in scenes.items():
        match = True
        for light_id_str, target in scene.items():
            light_id = int(light_id_str)
            if light_id not in states:
                match = False
                break
            state = states[light_id]
            if isinstance(target, dict):
                if 'brightness' not in target or 'color' not in target:
                    match = False
                    break
                if state['brightness'] != target['brightness'] or (target['brightness'] > 0 and state['active'] != target['color']):
                    match = False
                    break
            else:
                if state['brightness'] != target:
                    match = False
                    break
        if match:
            return scene_id
    return None
def update_active_scene():
    matching_scene = find_matching_scene()
    socketio.emit('set_active_scene', {'scene_id': matching_scene})
@app.route('/')
def home():
    return render_template('index.html')
def get_last_gps_data():
    return last_gps_data
def get_computed_dt():
    current_system = time_module.time()
    if has_gps_fix and base_gps_datetime is not None:
        return base_gps_datetime + timedelta(seconds=current_system - last_sync_time)
    return None
def get_has_gps_fix():
    return has_gps_fix
@socketio.on('connect')
def handle_connect():
    logger.info("Client connected")
    response_states = {str(k): {'brightness': v['brightness'], 'active': v.get('active', None)} for k, v in states.items()}
    emit('update_states', response_states)
    matching_scene = find_matching_scene()
    emit('set_active_scene', {'scene_id': matching_scene})
    emit('update_relays', gpio.get_relay_states())
    emit('update_sensors', gpio.get_sensor_states())
    emit('update_settings', config)
    emit('update_phase', {'phase': phase_manager.current_phase})
@socketio.on('set_brightness')
def handle_set_brightness(data):
    light_id = data['light_id']
    value = data['value']
    if light_id not in states:
        logger.warning(f"Invalid light_id: {light_id}")
        return
    state = states[light_id]
    pwm_value = calculate_pwm(value)
    if 'pin' in state:
        arduino.set_pwm(state['pin'], pwm_value)
    else:
        active_pin = state[state['active'] + '_pin']
        arduino.set_pwm(active_pin, pwm_value)
        inactive_color = 'red' if state['active'] == 'white' else 'white'
        inactive_pin = state[inactive_color + '_pin']
        arduino.set_pwm(inactive_pin, 0)
    state['brightness'] = value
    broadcast_states()
    update_active_scene()
    logger.debug(f"Set brightness for light {light_id} to {value}")
@socketio.on('toggle_color')
def handle_toggle_color(data):
    light_id = data['light_id']
    if light_id not in states:
        logger.warning(f"Invalid light_id: {light_id}")
        return
    state = states[light_id]
    if 'white_pin' not in state:
        logger.warning(f"Light {light_id} does not support color toggle")
        return
    current_active = state['active']
    new_active = 'red' if current_active == 'white' else 'white'
    pwm_value = calculate_pwm(state['brightness'])
    old_pin = state[current_active + '_pin']
    new_pin = state[new_active + '_pin']
    arduino.ramp_pwm(new_pin, pwm_value, ramp_rate_ms)
    arduino.ramp_pwm(old_pin, 0, ramp_rate_ms)
    state['active'] = new_active
    socketio.emit('ramp_start', {'light_id': light_id, 'ramp_duration': ramp_rate_ms})
    broadcast_states()
    update_active_scene()
    logger.debug(f"Toggled color for light {light_id} to {new_active}")
@socketio.on('ramp_brightness')
def handle_ramp_brightness(data):
    light_id = data['light_id']
    target = data['target']
    if light_id not in states or 'pin' not in states[light_id]:
        logger.warning(f"Invalid light_id or no pin for ramp: {light_id}")
        return
    state = states[light_id]
    pwm_value = calculate_pwm(target)
    arduino.ramp_pwm(state['pin'], pwm_value, ramp_rate_ms)
    state['brightness'] = target
    socketio.emit('brightness_ramp_start', {'light_id': light_id, 'target_brightness': target, 'ramp_duration': ramp_rate_ms})
    threading.Timer(static_config.get('ramp_rate', 1) + 0.5, lambda: check_levels(light_id)).start()
    broadcast_states()
    update_active_scene()
    logger.debug(f"Ramping brightness for light {light_id} to {target}")
def apply_settings(settings, duration_sec):
    duration_ms = duration_sec * 1000
    future_states = {k: v.copy() for k, v in states.items()}
    for light_id_str, target in settings.items():
        light_id = int(light_id_str)
        if light_id not in states:
            continue
        state = states[light_id]
        future_state = future_states[light_id]
        if isinstance(target, dict):
            if 'brightness' not in target or 'color' not in target:
                continue
            target_brightness = target['brightness']
            target_color = target['color']
        else:
            target_brightness = target
            target_color = None  # For non-color lights
        pwm_value = calculate_pwm(target_brightness)
        if 'pin' in state:
            arduino.ramp_pwm(state['pin'], pwm_value, duration_ms)
        else:
            # Color light
            if state['active'] == target_color or target_color is None:
                active_pin = state[state['active'] + '_pin']
                arduino.ramp_pwm(active_pin, pwm_value, duration_ms)
            else:
                new_active = target_color
                old_pin = state[state['active'] + '_pin']
                new_pin = state[new_active + '_pin']
                arduino.ramp_pwm(new_pin, pwm_value, duration_ms)
                arduino.ramp_pwm(old_pin, 0, duration_ms)
                future_state['active'] = new_active
        future_state['brightness'] = target_brightness
    # Prepare response with future states
    response_states = {str(k): {'brightness': future_states[k]['brightness'], 'active': future_states[k].get('active', None)} for k in future_states}
    socketio.emit('scene_ramp_start', {'states': response_states, 'ramp_duration': duration_ms})
    def apply_after_ramp():
        for light_id_str in settings:
            light_id = int(light_id_str)
            states[light_id]['brightness'] = future_states[light_id]['brightness']
            if 'active' in future_states[light_id]:
                states[light_id]['active'] = future_states[light_id]['active']
        broadcast_states()
        update_active_scene()
    # Schedule apply after ramp
    threading.Timer(duration_sec + 0.5, apply_after_ramp).start()
@socketio.on('apply_scene')
def handle_apply_scene(data):
    scene_id = data['scene_id']
    scenes = static_config.get('scenes', {})
    if scene_id not in scenes:
        logger.warning(f"Invalid scene_id: {scene_id}")
        return
    scene = scenes[scene_id]
    apply_settings(scene, scene_ramp_rate)
    logger.info(f"Applied scene: {scene_id}")
@socketio.on('set_relay')
def handle_set_relay(data):
    name = data['name']
    state = data['state']
    gpio.set_relay(name, state)
    logger.debug(f"Set relay {name} to {state}")
@socketio.on('set_setting')
def handle_set_setting(data):
    key = data['key']
    value = data['value']
    config_manager.set(key, value)
    if key == 'gamma':
        global gamma
        gamma = value
        check_levels()
    logger.debug(f"Set setting {key} to {value}")
def check_levels(light_id=None):
    if light_id:
        lights_to_check = {light_id: states[light_id]}
    else:
        lights_to_check = states
    for lid, state in lights_to_check.items():
        expected_pwm = calculate_pwm(state['brightness'])
        if 'pin' in state:
            pin = state['pin']
            current = arduino.get_pwm(pin)
            if current != expected_pwm:
                arduino.set_pwm(pin, expected_pwm)
                logger.warning(f"Corrected PWM for light {lid} pin {pin} from {current} to {expected_pwm}")
        else:
            active_pin = state[state['active'] + '_pin']
            inactive_pin = state['red_pin' if state['active'] == 'white' else 'white_pin']
            current_active = arduino.get_pwm(active_pin)
            current_inactive = arduino.get_pwm(inactive_pin)
            if current_active != expected_pwm or current_inactive != 0:
                arduino.set_pwm(active_pin, expected_pwm)
                arduino.set_pwm(inactive_pin, 0)
                logger.warning(f"Corrected PWM for light {lid}: active {current_active}->{expected_pwm}, inactive {current_inactive}->0")
    broadcast_states()
    update_active_scene()
def time_update_loop():
    while True:
        time_module.sleep(1)
        broadcast_gps({})
def voltage_to_soc(voltage):
    soc_table = [
        (10.0, 0),
        (10.16, 0.5),
        (11.2, 5),
        (12.0, 10),
        (12.2, 15),
        (12.7, 20),
        (12.8, 30),
        (12.9, 40),
        (12.95, 50),
        (13.0, 60),
        (13.1, 70),
        (13.2, 80),
        (13.3, 90),
        (13.5, 99),
        (13.8, 99.5),
        (14.6, 100),
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
last_battery_voltage = None
last_water_pct = None
last_solar_current = None
last_battery_current = None

# Add this helper function
def get_averaged_analog(pin, num_samples=20):
    samples = []
    for _ in range(num_samples):
        val = arduino.get_analog(pin)
        if val is not None:
            samples.append(val)
        time_module.sleep(0.01)  # Small delay between samples
    if not samples:
        return None
    return sum(samples) / len(samples)

def power_update_loop():
    global last_battery_voltage, last_water_pct, last_solar_current, last_battery_current
    alpha = 0.3  # EMA smoothing factor, adjust as needed (0.1-0.5)
    while True:
        time_module.sleep(5)
        vcc_samples = []
        for _ in range(5):  # Fewer samples for VCC since it's usually stable
            vcc = arduino.get_vcc()
            if vcc is not None:
                vcc_samples.append(vcc)
            time_module.sleep(0.01)
        vcc_mv = sum(vcc_samples) / len(vcc_samples) if vcc_samples else None
        if vcc_mv is not None and not (4000 <= vcc_mv <= 6000):
            vcc_mv = None
            logger.warning(f"Invalid VCC reading: {vcc_mv}")
        vref = vcc_mv / 1000.0 if vcc_mv else 5.0
        voltage_raw = get_averaged_analog(0)
        battery_voltage = last_battery_voltage
        if voltage_raw is not None:
            v_a0 = voltage_raw * vref / 1023.0
            battery_voltage = round(v_a0 * 5, 1)
            last_battery_voltage = battery_voltage
        else:
            logger.warning("Failed to read battery analog")
        battery_pct = voltage_to_soc(battery_voltage) if battery_voltage is not None else None
        water_raw = get_averaged_analog(1)
        water_pct = last_water_pct
        if water_raw is not None:
            v_a1 = water_raw * vref / 1023.0
            if abs(vref - v_a1) > 0.01:
                sensor_r = 100 * v_a1 / (vref - v_a1)
                pct = (240 - sensor_r) / (240 - 33) * 100
                water_pct = max(0, min(100, round(pct)))
                last_water_pct = water_pct
            else:
                water_pct = 0
        else:
            logger.warning("Failed to read water analog")
        solar_raw = get_averaged_analog(2)
        new_solar_current = None
        if solar_raw is not None:
            v_a2 = solar_raw * vref / 1023.0
            ct_solar = static_config.get('ct_solar', {'zero_offset': 2.5, 'sensitivity': 0.0125})
            zero_offset = ct_solar['zero_offset']
            sensitivity = ct_solar['sensitivity']
            new_solar_current = (v_a2 - zero_offset) / sensitivity
            new_solar_current = max(0, new_solar_current)
        else:
            logger.warning("Failed to read solar analog")
        if new_solar_current is not None:
            solar_current = alpha * new_solar_current + (1 - alpha) * last_solar_current if last_solar_current is not None else new_solar_current
            solar_current = round(solar_current, 1)
            last_solar_current = solar_current
        else:
            solar_current = last_solar_current
        battery_ct_raw = get_averaged_analog(3)
        battery_ct_ref_raw = get_averaged_analog(4)
        new_battery_current = None
        if battery_ct_raw is not None and battery_ct_ref_raw is not None:
            v_a3 = battery_ct_raw * vref / 1023.0
            v_a4 = battery_ct_ref_raw * vref / 1023.0
            delta = v_a3 - v_a4
            ct_battery = static_config.get('ct_battery', {'sensitivity': 0.003125, 'zero_offset': 0.0})
            sensitivity = ct_battery['sensitivity']
            zero_offset = ct_battery['zero_offset']
            delta -= zero_offset
            new_battery_current = delta / sensitivity
        else:
            logger.warning("Failed to read battery current analogs")
        if new_battery_current is not None:
            battery_current = alpha * new_battery_current + (1 - alpha) * last_battery_current if last_battery_current is not None else new_battery_current
            battery_current = round(battery_current, 1)
            last_battery_current = battery_current
        else:
            battery_current = last_battery_current
        load_current = None
        if solar_current is not None and battery_current is not None:
            load_current = solar_current - battery_current  # battery_current positive for charging, negative for discharging
            load_current = max(0, round(load_current, 1))  # Ensure non-negative
        # Add detailed logging for debugging
        logger.debug(f"Raw analogs: A0={f'{voltage_raw:.2f}' if voltage_raw is not None else 'None'}, A1={f'{water_raw:.2f}' if water_raw is not None else 'None'}, A2={f'{solar_raw:.2f}' if solar_raw is not None else 'None'}, A3={f'{battery_ct_raw:.2f}' if battery_ct_raw is not None else 'None'}, A4={f'{battery_ct_ref_raw:.2f}' if battery_ct_ref_raw is not None else 'None'}, delta={f'{delta:.5f}' if 'delta' in locals() else 'None'}, vref={vref:.2f}, battery_current={f'{battery_current:.2f}' if battery_current is not None else 'None'}")
        socketio.emit('update_power', {'battery': battery_voltage, 'battery_pct': battery_pct, 'water': water_pct, 'solar': solar_current, 'load': load_current})
        logger.debug(f"Power update: battery={battery_voltage}, battery_pct={battery_pct}, water={water_pct}, solar={solar_current}, load={load_current}")
phase_manager = PhaseManager(config_manager, handle_apply_scene, get_last_gps_data, get_computed_dt, get_has_gps_fix, socketio)
def apply_reed_settings(settings):
    # Convert reed phase setting to settings dict
    channel_str = str(settings['channel'])
    brightness = settings.get('brightness', 0)
    color = settings.get('color')
    if color:
        target = {'brightness': brightness, 'color': color}
    else:
        target = brightness
    settings_dict = {channel_str: target}
    apply_settings(settings_dict, scene_ramp_rate)
    logger.debug(f"Applied reed settings: {settings}")
reeds_config = static_config.get('reeds', {})
reeds_controller = ReedsController(reeds_config, apply_reed_settings, lambda: phase_manager.current_phase)
phase_manager.set_reeds_controller(reeds_controller)
@app.route('/phases')
def show_phases():
    try:
        gps_data = get_last_gps_data()
        sunrise_str = gps_data.get('sunrise', '---')
        sunset_str = gps_data.get('sunset', '---')
        location = gps_data.get('location', '')
        date_str = gps_data.get('date', '')
        computed_dt = get_computed_dt()
        has_fix = get_has_gps_fix()
        current_phase = phase_manager.current_phase or 'Unknown'
        evening_offset_str = config_manager.get('evening_offset', '-30 mins')
        morning_offset_str = config_manager.get('sunrise_offset', '+30 mins')
        night_time_str = config_manager.get('night_time', '8:00 PM')
        sunrise_offset_str = '---'
        sunset_offset_str = '---'
        if has_fix and computed_dt is not None and sunrise_str != '---':
            sunrise_time = phase_manager.parse_time(sunrise_str)
            if sunrise_time:
                morning_offset_mins = phase_manager.parse_offset(morning_offset_str)
                sunrise_dt = datetime.combine(computed_dt.date(), sunrise_time)
                sunrise_offset_dt = sunrise_dt + timedelta(minutes=morning_offset_mins)
                sunrise_offset_str = sunrise_offset_dt.strftime('%I:%M %p')
        if has_fix and computed_dt is not None and sunset_str != '---':
            sunset_time = phase_manager.parse_time(sunset_str)
            if sunset_time:
                evening_offset_mins = phase_manager.parse_offset(evening_offset_str)
                sunset_dt = datetime.combine(computed_dt.date(), sunset_time)
                sunset_offset_dt = sunset_dt + timedelta(minutes=evening_offset_mins)
                sunset_offset_str = sunset_offset_dt.strftime('%I:%M %p')
        title = "Sunrise and Sunset Times"
        if location and date_str:
            title += f" ({location}, {date_str})"
        html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Sun Phases</title>
    </head>
    <body>
        <h1>{title}</h1>
        <p><strong>Sunrise:</strong> {sunrise_str}</p>
        <p><strong>Sunrise with offset ({morning_offset_str}):</strong> {sunrise_offset_str}</p>
        <p><strong>Sunset:</strong> {sunset_str}</p>
        <p><strong>Sunset with offset ({evening_offset_str}):</strong> {sunset_offset_str}</p>
        <p><strong>Night start time:</strong> {night_time_str}</p>
        <p><strong>Current Phase:</strong> {current_phase}</p>
    </body>
    </html>
        """
        return html
    except Exception as e:
        logger.error(f"Error generating phases page: {e}")
        return f"Error generating phases page: {str(e)}", 500
if __name__ == '__main__':
    logger.info("Starting application")
    arduino.start()
    gps.start()
    threading.Thread(target=time_update_loop, daemon=True).start()
    threading.Thread(target=power_update_loop, daemon=True).start()
    phase_manager.start()
    socketio.run(app, debug=True, use_reloader=False, host='0.0.0.0', allow_unsafe_werkzeug=True)
    logger.info("Application shutdown")