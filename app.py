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
import queue
import statistics
import flask

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
from modules.rules import RulesEngine
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
    computed_dt = None
    if has_gps_fix and base_gps_datetime is not None:
        computed_dt = base_gps_datetime + timedelta(seconds=current_system - last_sync_time)
        hour = computed_dt.hour % 12 or 12
        minute = computed_dt.minute
        ampm = computed_dt.strftime('%p')
        last_gps_data['time'] = f"{hour}:{minute:02d} {ampm}"
        last_gps_data['date'] = computed_dt.strftime('%a %b %d')
        last_gps_data['full_date'] = computed_dt.strftime('%Y-%m-%d')
    elif not has_gps_fix:
        last_gps_data['date'] = '---'
        last_gps_data['time'] = '---'
        last_gps_data['sunrise'] = '---'
        last_gps_data['sunset'] = '---'
        last_gps_data['satellites'] = '---'
        last_gps_data['location'] = '---'
        last_gps_data['weather'] = None
        last_gps_data['full_date'] = '---'
    last_gps_data['has_fix'] = has_gps_fix
    # Compute offsets
    evening_offset_str = config_manager.get('evening_offset', '-30 mins')
    morning_offset_str = config_manager.get('sunrise_offset', '+30 mins')
    night_time_str = config_manager.get('night_time', '8:00 PM')
    last_gps_data['evening_offset_str'] = evening_offset_str
    last_gps_data['morning_offset_str'] = morning_offset_str
    last_gps_data['night_time'] = night_time_str
    last_gps_data['sunrise_offset'] = '---'
    last_gps_data['sunset_offset'] = '---'
    if has_gps_fix and computed_dt is not None and 'sunrise' in last_gps_data and last_gps_data['sunrise'] != '---':
        sunrise_time = phase_manager.parse_time(last_gps_data['sunrise'])
        if sunrise_time:
            morning_offset_mins = phase_manager.parse_offset(morning_offset_str)
            sunrise_dt = datetime.combine(computed_dt.date(), sunrise_time)
            sunrise_offset_dt = sunrise_dt + timedelta(minutes=morning_offset_mins)
            last_gps_data['sunrise_offset'] = sunrise_offset_dt.strftime('%I:%M %p')
    if has_gps_fix and computed_dt is not None and 'sunset' in last_gps_data and last_gps_data['sunset'] != '---':
        sunset_time = phase_manager.parse_time(last_gps_data['sunset'])
        if sunset_time:
            evening_offset_mins = phase_manager.parse_offset(evening_offset_str)
            sunset_dt = datetime.combine(computed_dt.date(), sunset_time)
            sunset_offset_dt = sunset_dt + timedelta(minutes=evening_offset_mins)
            last_gps_data['sunset_offset'] = sunset_offset_dt.strftime('%I:%M %p')
    logger.debug(f"Broadcasting 'update_gps' with data: {last_gps_data}")
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
    if 'sensitivity' in config['ct_solar'] and not isinstance(config['ct_solar']['sensitivity'], (int, float)):
        raise ValueError("Invalid 'sensitivity' in ct_solar")
    for key in ['sensitivity_charging', 'sensitivity_discharging']:
        if key in config['ct_battery'] and not isinstance(config['ct_battery'][key], (int, float)):
            raise ValueError(f"Invalid '{key}' in ct_battery")
    
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
            if 'green_pin' in light_data:
                if not isinstance(light_data['green_pin'], int):
                    raise ValueError(f"Invalid 'green_pin' for light '{light_id_str}'")
                if 'green_factor' not in light_data or not isinstance(light_data['green_factor'], (int, float)):
                    raise ValueError(f"Missing or invalid 'green_factor' for light '{light_id_str}' with green_pin")
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

    # screens
    if 'screens' in config:
        screens = config['screens']
        if not isinstance(screens, dict):
            raise ValueError("screens must be a dictionary")
        for name, sconf in screens.items():
            if not isinstance(sconf, dict):
                raise ValueError(f"Screen '{name}' must be a dictionary")
            required = ['ip', 'brightness_path', 'levels']
            for r in required:
                if r not in sconf:
                    raise ValueError(f"Missing '{r}' for screen '{name}'")
            if not isinstance(sconf['ip'], str):
                raise ValueError(f"Invalid 'ip' for screen '{name}'")
            if not isinstance(sconf['brightness_path'], str):
                raise ValueError(f"Invalid 'brightness_path' for screen '{name}'")
            levels = sconf['levels']
            if not isinstance(levels, dict):
                raise ValueError(f"'levels' for screen '{name}' must be dict")
            for l in ['low', 'medium', 'high']:
                if l not in levels or not isinstance(levels[l], int):
                    raise ValueError(f"Missing or invalid level '{l}' for screen '{name}'")

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
screens_config = static_config.get('screens', {})
current_screen_levels = {name: 'medium' for name in screens_config}
screen_sids = {}
states = {}
for lid_str, lconf in lights_config.items():
    lid = int(lid_str)
    state = {'brightness': 0, 'locked': False}
    if 'pin' in lconf:
        state['pin'] = lconf['pin']
    else:
        state['white_pin'] = lconf['white_pin']
        state['red_pin'] = lconf['red_pin']
        if 'green_pin' in lconf:
            state['green_pin'] = lconf['green_pin']
            state['green_factor'] = lconf.get('green_factor', 0.0)
        state['active'] = lconf.get('active', 'white')
    states[lid] = state
# Initialize all PWM pins to 0
for lid, state in states.items():
    if 'pin' in state:
        arduino.set_pwm(state['pin'], 0)
    else:
        arduino.set_pwm(state['white_pin'], 0)
        arduino.set_pwm(state['red_pin'], 0)
        if 'green_pin' in state:
            arduino.set_pwm(state['green_pin'], 0)
ramp_rate_ms = static_config.get('ramp_rate', 1) * 1000
scene_ramp_rate = static_config.get('scene_ramp_rate', 2)
gamma = config_manager.get('gamma', 2.5) # Keep gamma in dynamic config for potential future edits
def calculate_pwm(brightness, active_color=None):
    normalized = brightness / 100.0
    return int(normalized * 255)
def broadcast_states():
    response_states = {str(k): {'brightness': v['brightness'], 'active': v.get('active', None), 'locked': v.get('locked', False)} for k, v in states.items()}
    logger.debug(f"Broadcasting 'update_states' with data: {response_states}")
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
    logger.debug(f"Broadcasting 'set_active_scene' with data: {{'scene_id': {matching_scene}}}")
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
def sync_client(is_screen, screen_name=None):
    response_states = {str(k): {'brightness': v['brightness'], 'active': v.get('active', None), 'locked': v.get('locked', False)} for k, v in states.items()}
    emit('update_states', response_states)
    logger.debug(f"Emitting 'update_states' to client with data: {response_states}")

    matching_scene = find_matching_scene()
    emit('set_active_scene', {'scene_id': matching_scene})
    logger.debug(f"Emitting 'set_active_scene' to client with data: {{'scene_id': {matching_scene}}}")

    relay_states = gpio.get_relay_states()
    emit('update_relays', relay_states)
    logger.debug(f"Emitting 'update_relays' to client with data: {relay_states}")

    sensor_states = gpio.get_sensor_states()
    emit('update_sensors', sensor_states)
    logger.debug(f"Emitting 'update_sensors' to client with data: {sensor_states}")

    emit('update_settings', config)
    logger.debug(f"Emitting 'update_settings' to client with data: {config}")

    emit('update_phase', {'phase': phase_manager.current_phase})
    logger.debug(f"Emitting 'update_phase' to client with data: {{'phase': {phase_manager.current_phase}}}")

    emit('update_gps', last_gps_data)
    logger.debug(f"Emitting 'update_gps' to client with data: {last_gps_data}")

    # Emit current reed states
    for reed_id, button in reeds_controller.reeds.items():
        state = "Closed" if button.is_pressed else "Open"
        emit('update_reed_state', {'reed_id': reed_id, 'state': state})
        logger.debug(f"Emitting 'update_reed_state' to client with data: {{'reed_id': {reed_id}, 'state': {state}}}")

    emit('set_brightness_controls_enabled', {'enabled': is_screen})
    logger.debug(f"Emitting 'set_brightness_controls_enabled' to client with data: {{'enabled': {is_screen}}}")

    if is_screen and screen_name:
        level = current_screen_levels.get(screen_name, 'medium')
        emit('update_brightness_level', {'level': level})
        logger.debug(f"Emitting 'update_brightness_level' to client with data: {{'level': {level}}}")

@socketio.on('connect')
def handle_connect():
    logger.info("Client connected")
    remote_addr = flask.request.remote_addr
    is_screen = any(remote_addr == conf['ip'] for conf in screens_config.values())
    screen_name = None
    if is_screen:
        screen_name = next((name for name, conf in screens_config.items() if conf['ip'] == remote_addr), None)
        if screen_name:
            screen_sids[screen_name] = flask.request.sid
    sync_client(is_screen, screen_name)

@socketio.on('request_sync')
def handle_request_sync():
    logger.debug("Received 'request_sync'")
    remote_addr = flask.request.remote_addr
    is_screen = any(remote_addr == conf['ip'] for conf in screens_config.values())
    screen_name = None
    if is_screen:
        screen_name = next((name for name, conf in screens_config.items() if conf['ip'] == remote_addr), None)
    sync_client(is_screen, screen_name)

@socketio.on('set_brightness')
def handle_set_brightness(data):
    logger.debug(f"Received 'set_brightness' with data: {data}")
    light_id = data['light_id']
    value = data['value']
    if light_id not in states:
        logger.warning(f"Invalid light_id: {light_id}")
        return
    if states[light_id].get('locked', False):
        logger.warning(f"Ignoring set_brightness for locked light {light_id}")
        return
    state = states[light_id]
    pwm_value = calculate_pwm(value, state.get('active'))
    if 'pin' in state:
        arduino.set_pwm(state['pin'], pwm_value)
    else:
        active_pin = state[state['active'] + '_pin']
        arduino.set_pwm(active_pin, pwm_value)
        inactive_color = 'red' if state['active'] == 'white' else 'white'
        inactive_pin = state[inactive_color + '_pin']
        arduino.set_pwm(inactive_pin, 0)
        if 'green_pin' in state:
            if state['active'] == 'red':
                green_pwm = int(pwm_value * state['green_factor'])
                arduino.set_pwm(state['green_pin'], green_pwm)
            else:
                arduino.set_pwm(state['green_pin'], 0)
    state['brightness'] = value
    broadcast_states()
    update_active_scene()
    logger.debug(f"Set brightness for light {light_id} to {value}")

@socketio.on('toggle_color')
def handle_toggle_color(data):
    logger.debug(f"Received 'toggle_color' with data: {data}")
    light_id = data['light_id']
    if light_id not in states:
        logger.warning(f"Invalid light_id: {light_id}")
        return
    if states[light_id].get('locked', False):
        logger.warning(f"Ignoring toggle_color for locked light {light_id}")
        return
    state = states[light_id]
    if 'white_pin' not in state:
        logger.warning(f"Light {light_id} does not support color toggle")
        return
    current_active = state['active']
    new_active = 'red' if current_active == 'white' else 'white'
    pwm_value = calculate_pwm(state['brightness'], new_active)
    old_pin = state[current_active + '_pin']
    new_pin = state[new_active + '_pin']
    arduino.ramp_pwm(new_pin, pwm_value, ramp_rate_ms)
    arduino.ramp_pwm(old_pin, 0, ramp_rate_ms)
    if 'green_pin' in state:
        if new_active == 'red':
            green_pwm = int(pwm_value * state['green_factor'])
            arduino.ramp_pwm(state['green_pin'], green_pwm, ramp_rate_ms)
        else:
            arduino.ramp_pwm(state['green_pin'], 0, ramp_rate_ms)
    state['active'] = new_active
    logger.debug(f"Emitting 'ramp_start' to all with data: {{'light_id': {light_id}, 'ramp_duration': {ramp_rate_ms}}}")
    socketio.emit('ramp_start', {'light_id': light_id, 'ramp_duration': ramp_rate_ms})
    broadcast_states()
    update_active_scene()
    logger.debug(f"Toggled color for light {light_id} to {new_active}")

@socketio.on('ramp_brightness')
def handle_ramp_brightness(data):
    logger.debug(f"Received 'ramp_brightness' with data: {data}")
    light_id = data['light_id']
    target = data['target']
    if light_id not in states or 'pin' not in states[light_id]:
        logger.warning(f"Invalid light_id or no pin for ramp: {light_id}")
        return
    if states[light_id].get('locked', False):
        logger.warning(f"Ignoring ramp_brightness for locked light {light_id}")
        return
    state = states[light_id]
    pwm_value = calculate_pwm(target)
    arduino.ramp_pwm(state['pin'], pwm_value, ramp_rate_ms)
    state['brightness'] = target
    logger.debug(f"Emitting 'brightness_ramp_start' to all with data: {{'light_id': {light_id}, 'target_brightness': {target}, 'ramp_duration': {ramp_rate_ms}}}")
    socketio.emit('brightness_ramp_start', {'light_id': light_id, 'target_brightness': target, 'ramp_duration': ramp_rate_ms})
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
        if states[light_id].get('locked', False):
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
        pwm_value = calculate_pwm(target_brightness, target_color or state.get('active'))
        if 'pin' in state:
            arduino.ramp_pwm(state['pin'], pwm_value, duration_ms)
        else:
            # Color light
            if state['active'] == target_color or target_color is None:
                active_pin = state[state['active'] + '_pin']
                arduino.ramp_pwm(active_pin, pwm_value, duration_ms)
                if 'green_pin' in state:
                    if state['active'] == 'red':
                        green_pwm = int(pwm_value * state['green_factor'])
                        arduino.ramp_pwm(state['green_pin'], green_pwm, duration_ms)
                    else:
                        arduino.ramp_pwm(state['green_pin'], 0, duration_ms)
            else:
                new_active = target_color
                old_pin = state[state['active'] + '_pin']
                new_pin = state[new_active + '_pin']
                arduino.ramp_pwm(new_pin, pwm_value, duration_ms)
                arduino.ramp_pwm(old_pin, 0, duration_ms)
                if 'green_pin' in state:
                    if new_active == 'red':
                        green_pwm = int(pwm_value * state['green_factor'])
                        arduino.ramp_pwm(state['green_pin'], green_pwm, duration_ms)
                    else:
                        arduino.ramp_pwm(state['green_pin'], 0, duration_ms)
                future_state['active'] = new_active
        future_state['brightness'] = target_brightness
    # Prepare response with future states
    response_states = {str(k): {'brightness': future_states[k]['brightness'], 'active': future_states[k].get('active', None)} for k in future_states}
    logger.debug(f"Broadcasting 'scene_ramp_start' with data: {{'states': {response_states}, 'ramp_duration': {duration_ms}}}")
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
def apply_scene(scene_id):
    scenes = static_config.get('scenes', {})
    if scene_id not in scenes:
        logger.warning(f"Invalid scene_id: {scene_id}")
        return
    scene = scenes[scene_id]
    apply_settings(scene, scene_ramp_rate)
    logger.info(f"Applied scene: {scene_id}")
@socketio.on('apply_scene')
def handle_apply_scene(data):
    logger.debug(f"Received 'apply_scene' with data: {data}")
    scene_id = data['scene_id']
    apply_scene(scene_id)
@socketio.on('set_relay')
def handle_set_relay(data):
    logger.debug(f"Received 'set_relay' with data: {data}")
    name = data['name']
    state = data['state']
    gpio.set_relay(name, state)
    logger.debug(f"Set relay {name} to {state}")
@socketio.on('set_setting')
def handle_set_setting(data):
    logger.debug(f"Received 'set_setting' with data: {data}")
    key = data['key']
    value = data['value']
    config_manager.set(key, value)
    if key == 'gamma':
        global gamma
        gamma = value
    logger.debug(f"Broadcasting 'update_settings' with data: {config_manager.config}")
    socketio.emit('update_settings', config_manager.config)
    if key in ['sunrise_offset', 'evening_offset', 'night_time']:
        broadcast_gps({})
    if key == 'auto_brightness' and value:
        current_phase = phase_manager.current_phase
        if current_phase:
            brightness_level = {'day': 'high', 'evening': 'medium', 'night': 'low'}.get(current_phase)
            if brightness_level:
                for s_name in screens_config:
                    set_screen_brightness(s_name, brightness_level)
                    current_screen_levels[s_name] = brightness_level
                    if s_name in screen_sids:
                        logger.debug(f"Emitting 'update_brightness_level' to sid {screen_sids[s_name]} with data: {{'level': {brightness_level}}}")
                        socketio.emit('update_brightness_level', {'level': brightness_level}, to=screen_sids[s_name])
    logger.debug(f"Set setting {key} to {value}")
@socketio.on('set_brightness_level')
def handle_set_brightness_level(data):
    logger.debug(f"Received 'set_brightness_level' with data: {data}")
    level = data.get('level')
    if level not in ['low', 'medium', 'high']:
        logger.warning(f"Invalid brightness level: {level}")
        return
    remote_addr = flask.request.remote_addr
    screen_name = None
    for name, conf in screens_config.items():
        if conf['ip'] == remote_addr:
            screen_name = name
            break
    if screen_name:
        set_screen_brightness(screen_name, level)
        current_screen_levels[screen_name] = level
    else:
        logger.warning(f"No screen found for IP: {remote_addr}")
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

# Add this helper function
def get_averaged_analog(pin, num_samples=15):
    samples = []
    for _ in range(num_samples):
        val = arduino.get_analog(pin)
        if val is not None:
            samples.append(val)
        time_module.sleep(0.01)  # Small delay between samples
    if not samples:
        return None
    return statistics.median(samples)

def power_update_loop():
    global last_battery_voltage, last_water_pct, last_solar_current
    alpha = 0.3  # EMA smoothing factor, adjust as needed (0.1-0.5)
    while True:
        time_module.sleep(1)
        vcc_mv, voltage_raw, water_raw, solar_raw = arduino.get_all_analogs_and_vcc()
        
        battery_voltage = last_battery_voltage
        water_pct = last_water_pct
        solar_current = last_solar_current
        
        if vcc_mv is not None and 4000 <= vcc_mv <= 6000:
            vref = vcc_mv / 1000.0
        else:
            vref = 5.0
            if vcc_mv is not None:
                logger.warning(f"Invalid VCC reading: {vcc_mv}")
        
        if voltage_raw is not None:
            v_a0 = voltage_raw * vref / 1023.0
            new_battery_voltage = round(v_a0 * 5, 1)
            battery_voltage = alpha * new_battery_voltage + (1 - alpha) * last_battery_voltage if last_battery_voltage is not None else new_battery_voltage
            battery_voltage = round(battery_voltage, 1)
            last_battery_voltage = battery_voltage
        else:
            logger.warning("Failed to read battery analog")
        
        if water_raw is not None:
            v_a1 = water_raw * vref / 1023.0
            if abs(vref - v_a1) > 0.01:
                sensor_r = 100 * v_a1 / (vref - v_a1)
                pct = (240 - sensor_r) / (240 - 33) * 100
                new_water_pct = max(0, min(100, round(pct)))
                water_pct = alpha * new_water_pct + (1 - alpha) * last_water_pct if last_water_pct is not None else new_water_pct
                water_pct = round(water_pct)
                last_water_pct = water_pct
            else:
                water_pct = 0
        else:
            logger.warning("Failed to read water analog")
        
        if solar_raw is not None:
            v_a2 = solar_raw * vref / 1023.0
            ct_solar = static_config.get('ct_solar', {'zero_offset': 2.5326, 'sensitivity': 0.0125})
            zero_offset = ct_solar['zero_offset']
            sensitivity = ct_solar['sensitivity']
            new_solar_current = (v_a2 - zero_offset) / sensitivity
            new_solar_current = max(0, new_solar_current)
            solar_current = alpha * new_solar_current + (1 - alpha) * last_solar_current if last_solar_current is not None else new_solar_current
            solar_current = round(solar_current, 1)
            last_solar_current = solar_current
        else:
            logger.warning("Failed to read solar analog")
        
        # Add detailed logging for debugging
        logger.debug(f"Raw values: VCC={vcc_mv if vcc_mv is not None else 'None'}, A0={f'{voltage_raw:.2f}' if voltage_raw is not None else 'None'}, A1={f'{water_raw:.2f}' if water_raw is not None else 'None'}, A2={f'{solar_raw:.2f}' if solar_raw is not None else 'None'}, vref={vref:.2f}")
        
        battery_pct = voltage_to_soc(battery_voltage) if battery_voltage is not None else None
        power_data = {'battery': battery_voltage, 'battery_pct': battery_pct, 'water': water_pct, 'solar': solar_current, 'phase': phase_manager.current_phase}
        logger.debug(f"Broadcasting 'update_power' with data: {power_data}")
        socketio.emit('update_power', power_data)
        logger.debug(f"Power update: battery={battery_voltage}, battery_pct={battery_pct}, water={water_pct}, solar={solar_current}, phase={phase_manager.current_phase}")

def set_screen_brightness(screen_name, level):
    if screen_name not in screens_config:
        logger.warning(f"Unknown screen {screen_name}")
        return
    conf = screens_config[screen_name]
    if level not in conf['levels']:
        logger.warning(f"Unknown level {level} for {screen_name}")
        return
    value = conf['levels'][level]
    ip = conf['ip']
    path = conf['brightness_path']
    username = 'pi'
    cmd = f"ssh {username}@{ip} \"echo {value} > {path}\""
    result = os.system(cmd)
    if result == 0:
        logger.info(f"Set {screen_name} brightness to {level} ({value})")
    else:
        logger.error(f"Failed to set {screen_name} brightness, code {result}")
phase_manager = PhaseManager(config_manager, handle_apply_scene, get_last_gps_data, get_computed_dt, get_has_gps_fix, socketio, screens_config, set_screen_brightness, current_screen_levels, screen_sids)
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
state_queue = queue.Queue()
def process_state_updates():
    while True:
        reed_id, state = state_queue.get()
        logger.debug(f"Broadcasting 'update_reed_state' with data: {{'reed_id': {reed_id}, 'state': {state}}}")
        socketio.emit('update_reed_state', {'reed_id': reed_id, 'state': state})
socketio.start_background_task(process_state_updates)
def broadcast_reed_state(reed_id, state):
    state_queue.put((reed_id, state))
def set_light_locked(light_id, locked):
    if light_id in states:
        states[light_id]['locked'] = locked
        broadcast_states()
reeds_config = static_config.get('reeds', {})
reeds_controller = ReedsController(reeds_config, apply_reed_settings, lambda: phase_manager.current_phase, broadcast_reed_state, on_lock=set_light_locked)
phase_manager.set_reeds_controller(reeds_controller)
def auto_wake_screen(screen_name):
    current_phase = phase_manager.current_phase
    level_map = {'day': 'high', 'evening': 'medium', 'night': 'low'}
    level = level_map.get(current_phase, 'medium')
    set_screen_brightness(screen_name, level)
    current_screen_levels[screen_name] = level
    if screen_name in screen_sids:
        socketio.emit('update_brightness_level', {'level': level}, to=screen_sids[screen_name])

def sleep_screen(screen_name):
    conf = screens_config[screen_name]
    ip = conf['ip']
    path = conf['brightness_path']
    username = 'pi'
    cmd = f"ssh {username}@{ip} \"echo 0 > {path}\""
    result = os.system(cmd)
    if result == 0:
        logger.info(f"Slept screen {screen_name}")
    else:
        logger.error(f"Failed to sleep screen {screen_name}, code {result}")
    current_screen_levels[screen_name] = 'off'
    if screen_name in screen_sids:
        socketio.emit('update_brightness_level', {'level': 'off'}, to=screen_sids[screen_name])
action_handlers = {
    'apply_scene': apply_scene,
    'auto_wake_screen': auto_wake_screen,
    'sleep_screen': sleep_screen
}
rules_engine = RulesEngine('rules.json', phase_manager, reeds_controller, get_computed_dt, action_handlers)
reeds_controller.set_rules_engine(rules_engine)
phase_manager.set_rules_engine(rules_engine)
rules_engine.evaluate_on_startup()
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
        sunrise_offset_str = gps_data.get('sunrise_offset', '---')
        sunset_offset_str = gps_data.get('sunset_offset', '---')
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
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.8.1/socket.io.js"></script>
    <script>
        var socket = io();
        socket.on('update_gps', function(data) {{
            document.getElementById('title').innerText = 'Sunrise and Sunset Times' + (data.location && data.date ? ' (' + data.location + ', ' + data.date + ')' : '');
            document.getElementById('sunrise').innerText = data.sunrise || '---';
            document.getElementById('sunset').innerText = data.sunset || '---';
            document.getElementById('sunrise_offset').innerText = data.sunrise_offset || '---';
            document.getElementById('sunset_offset').innerText = data.sunset_offset || '---';
            document.getElementById('morning_offset_str').innerText = data.morning_offset_str || '+30 mins';
            document.getElementById('evening_offset_str').innerText = data.evening_offset_str || '-30 mins';
            document.getElementById('night_time').innerText = data.night_time || '8:00 PM';
        }});
        socket.on('update_phase', function(data) {{
            document.getElementById('current_phase').innerText = data.phase || 'Unknown';
        }});
        socket.on('update_settings', function(config) {{
            document.getElementById('morning_offset_str').innerText = config.sunrise_offset || '+30 mins';
            document.getElementById('evening_offset_str').innerText = config.evening_offset || '-30 mins';
            document.getElementById('night_time').innerText = config.night_time || '8:00 PM';
        }});
    </script>
</head>
<body>
    <h1 id="title">{title}</h1>
    <p><strong>Sunrise:</strong> <span id="sunrise">{sunrise_str}</span></p>
    <p><strong>Sunrise with offset (<span id="morning_offset_str">{morning_offset_str}</span>):</strong> <span id="sunrise_offset">{sunrise_offset_str}</span></p>
    <p><strong>Sunset:</strong> <span id="sunset">{sunset_str}</span></p>
    <p><strong>Sunset with offset (<span id="evening_offset_str">{evening_offset_str}</span>):</strong> <span id="sunset_offset">{sunset_offset_str}</span></p>
    <p><strong>Night start time:</strong> <span id="night_time">{night_time_str}</span></p>
    <p><strong>Current Phase:</strong> <span id="current_phase">{current_phase}</span></p>
</body>
</html>
        """
        return html
    except Exception as e:
        logger.error(f"Error generating phases page: {e}")
        return f"Error generating phases page: {str(e)}", 500

@app.route('/reeds')
def show_reeds():
    try:
        html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Reed Switch States</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.8.1/socket.io.js"></script>
    <script>
        var socket = io();
        socket.on('update_reed_state', function(data) {
            var element = document.getElementById('reed-' + data.reed_id);
            if (element) {
                var displayName = data.reed_id.replace(/_/g, ' ').split(' ').map(function(word) {
                    return word.charAt(0).toUpperCase() + word.slice(1);
                }).join(' ');
                element.innerText = displayName + ': ' + data.state;
            }
        });
    </script>
</head>
<body>
    <h1>Reed Switch States</h1>
    <ul>
"""
        for reed_id in sorted(reeds_config.keys()):
            button = reeds_controller.reeds.get(reed_id)
            if button:
                state = "Closed" if button.is_pressed else "Open"
            else:
                state = "Unknown"
            display_name = reed_id.replace('_', ' ').title()
            html += f"<li id=\"reed-{reed_id}\">{display_name}: {state}</li>\n"
        html += """
    </ul>
</body>
</html>
"""
        return html
    except Exception as e:
        logger.error(f"Error generating reeds page: {e}")
        return f"Error generating reeds page: {str(e)}", 500

if __name__ == '__main__':
    logger.info("Starting application")
    arduino.start()
    gps.start()
    threading.Thread(target=time_update_loop, daemon=True).start()
    threading.Thread(target=power_update_loop, daemon=True).start()
    phase_manager.start()
    socketio.run(app, debug=True, use_reloader=False, host='0.0.0.0', allow_unsafe_werkzeug=True)
    reeds_controller.stop_polling()
    logger.info("Application shutdown")