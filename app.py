# app.py
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import threading
import time
import os
import logging
import sys
import math
import json
from datetime import datetime

# ====================== VERSION ======================
from modules.version import APP_VERSION

# ====================== LOGGING ======================
from modules.config import config
from modules.logger import setup_logging

logger = setup_logging(config)

# ====================== SONOS ======================
from modules.sonos import SonosManager

# ====================== BANNER ======================
logger.info("=" * 71)
logger.info(f"🚐💦  Welcome to the Pissmole Camper Control System v{APP_VERSION}  💦🚐")
logger.info("=" * 71)

level_name = config.get('logging', 'level', fallback='INFO')
log_dir = config.get('logging', 'log_directory', fallback='logs')
retention_days = config.getint('logging', 'log_retention_days', fallback=31)

logger.info(
    f"📋 Logging initialized → Level: {level_name}, "
    f"Directory: {log_dir}, Retention: {retention_days} days"
)

# ====================== EXCEPTION HANDLER ======================
def log_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.critical("💥 Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = log_exception

# ====================== RELOAD PROTECTION ======================
if hasattr(sys, '_pccs_already_started'):
    logger.warning("⚠️ Module reloaded - skipping duplicate initialization")
else:
    sys._pccs_already_started = True

logging.getLogger("werkzeug").setLevel(logging.WARNING)
logging.getLogger("engineio").setLevel(logging.WARNING)
logging.getLogger("socketio").setLevel(logging.WARNING)

# ====================== THEME HELPER ======================
def get_friendly_theme_name(theme_file: str) -> str:
    """Extract friendly name from CSS comment or fallback to pretty filename"""
    if not theme_file:
        return "Unknown"
    
    # Possible locations for the CSS file
    base_path = os.path.dirname(__file__)  # Points to the directory of app.py
    paths = [
        os.path.join(base_path, 'static', 'css', f"{theme_file}.css"),
        os.path.join(base_path, 'static', 'css', 'themes', f"{theme_file}.css"),
        os.path.join(base_path, 'static', f"{theme_file}.css")
    ]
    
    for path in paths:
        try:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    first_line = f.readline().strip()
                    if first_line.startswith('/*') and first_line.endswith('*/'):
                        comment = first_line[2:-2].strip()
                        if comment:
                            return comment
        except:
            continue
    
    # Fallback
    return theme_file.replace('-', ' ').replace('_', ' ').title()

# ====================== CONFIG ======================
from modules.config import config

class ConfigManager:
    def __init__(self, filename: str, default: dict):
        self.path = os.path.join(os.path.dirname(__file__), 'config', filename)
        self.default = default
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, 'r') as f:
                    data = json.load(f)
                    return {**self.default, **data}
        except Exception as e:
            logger.error(f"Failed to load config {self.path}: {e}")
        return self.default.copy()

    def save(self, data: dict):
        try:
            with open(self.path, 'w') as f:
                json.dump(data, f, indent=2)
            logger.debug(f"💾 Saved config: {self.path}")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")


theme_config = ConfigManager('active_theme.json', {'theme': 'base'})
dark_mode_config = ConfigManager('active_dark_mode.json', {'mode': 'dark'})

# ====================== THEME ======================
current_global_theme = theme_config.load()['theme']
friendly_name = get_friendly_theme_name(current_global_theme)

logger.info(f"🎨 Loaded theme: {friendly_name} ({current_global_theme}.css)")

# ====================== CONSTANTS & GLOBALS ======================
# These now come from /config/pccs.conf
UI_RAMP_TIME_MS = config.getint('lighting', 'ui_ramp_time_ms', 1000)
BACKGROUND_SYNC_INTERVAL = config.getint('background_sync', 'sync_interval', 45)
REED_MONITOR_INTERVAL = config.getfloat('reed_monitor', 'monitor_interval', 0.25)

first_state_read_done = False
shutdown_event = threading.Event()

# ====================== MODULES ======================
from modules.gps import GPSModule
from modules.gpio import GPIODeviceManager
from modules.reeds import ReedManager
from modules.phases import PhaseManager
from modules.sensors import SensorManager
from modules.arduino import ArduinoManager
from modules.toasts import ToastManager, toast_manager

app = Flask(__name__)
app.config['SECRET_KEY'] = config.get('system', 'secret_key')
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ====================== TOASTS ======================
toast_manager = ToastManager(config, socketio)
import modules.toasts
modules.toasts.toast_manager = toast_manager

# ====================== ARDUINO + GPIO ======================
arduino = ArduinoManager(config)
LIGHT_MAP = arduino.LIGHT_MAP
RGB_LIGHTS = arduino.RGB_BUG_LIGHTS
RGB_BUG_LIGHTS = arduino.RGB_BUG_LIGHTS

# ====================== GLOBAL STATE ======================
state = {name: 0 for name in list(LIGHT_MAP.keys()) + list(RGB_BUG_LIGHTS.keys())}


# ====================== WRAPPERS ======================
def send_command(cmd: str):
    return arduino.send_command(cmd)

def set_rgb_bug_light(name: str, brightness: int, mode: str = 'white'):
    return arduino.set_rgb_bug_light(name, brightness, mode)


# ====================== RAMP & SAFETY ======================
active_ramps: dict[str, threading.Timer] = {}
active_warnings: set[str] = set()

def cancel_ramp(name: str):
    if name in active_ramps:
        try:
            active_ramps[name].cancel()
        except:
            pass
        active_ramps.pop(name, None)


def apply_safety_constraints(name: str, target: int, source: str | None = None) -> int:
    """Centralised safety checks (rooftop tent interlock etc.)"""
    if name != 'rooftop_tent' or target <= 0:
        return target

    effective = None
    physical_closed = True

    if 'reed_manager' in globals() and reed_manager is not None:
        try:
            effective = reed_manager.get_effective_state('rooftop_tent')
            physical_closed = reed_manager.gpio.reed_states.get('rooftop_tent', True)
        except Exception as e:
            logger.warning(f"Failed to read reed state for safety check: {e}")

    if effective is True:
        logger.warning(f"🔥 rooftop_tent cannot turn on while closed (requested {target}%)")
        return 0

    elif effective is False and physical_closed and source == "user interface":
        warning_key = f"{name}_circuit_warning"
        if warning_key not in active_warnings:
            active_warnings.add(warning_key)
            
            timeout_sec = config.getfloat(
                'toasts', 
                'rooftop_tent_safety_warning_timeout', 
                fallback=30.0
            )
            
            logger.warning(
                "🔥 rooftop_tent light turned on with physical reed closed - "
                "Ensure the lighting circuit is off"
            )
            
            threading.Timer(
                timeout_sec, 
                lambda k=warning_key: active_warnings.discard(k)
            ).start()

    return target


def ramp_and_broadcast(name: str, target: int, duration_ms: int, mode: str | None = None, source: str | None = None):
    if name not in state:
        return

    target = apply_safety_constraints(name, target, source)
    cancel_ramp(name)

    mode_changed = False
    if name in RGB_LIGHTS and mode is not None:
        if state.get(f"{name}_mode") != mode:
            mode_changed = True
        state[f"{name}_mode"] = mode

    if state.get(name) == target and not mode_changed:
        return

    start = state.get(name, 0)
    steps = max(8, int(duration_ms / 50))
    delay = duration_ms / steps / 1000.0

    logger.debug(f"↗️ Starting optimistic ramp {name} {start}→{target}% "
                 f"{'[' + mode + ']' if mode else ''} ({duration_ms}ms)")

    def ramp_step(i: int):
        if i > steps:
            state[name] = target
            socketio.emit('state_update', state.copy())
            if source:
                log_light_change(name, target, source, mode)
            active_ramps.pop(name, None)
            return

        t = i / steps
        progress = 0.5 * (1 - math.cos(math.pi * t))
        current = round(start + (target - start) * progress)

        state[name] = current
        socketio.emit('state_update', state.copy())

        timer = threading.Timer(delay, ramp_step, args=(i + 1,))
        active_ramps[name] = timer
        timer.start()

    ramp_step(1)

    
def log_light_change(name: str, value: int | bool, source: str | None = None, mode: str | None = None):
    if source is None:
        return

    if name in getattr(gpio_manager, 'relays', {}) or isinstance(value, bool):
        status = "ON" if bool(value) else "OFF"
        logger.info(f"💡 {name} turned {status} [{source}]")
    else:
        colour = "🔴" if mode == "red" else "⚪" if mode == "white" else ""
        mode_str = f" {mode.title()} mode" if mode and mode != "white" else ""
        logger.info(f"💡{colour} {name} → {value}%{mode_str} [{source}]")


# ====================== UNIFIED REED TRIGGER ======================
def make_reed_trigger(reed_name: str):
    def trigger(is_closed: bool, is_phase_change: bool = False,
                desired_brightness: int = None, desired_mode: str = None):
        
        if not phase_manager or not reed_manager:
            return

        ramp = (phase_manager.get_phase_ramp_time() 
                if is_phase_change 
                else reed_manager.get_reed_ramp_time())

        light_list = gpio_manager.reed_to_light_map.get(reed_name, [reed_name])

        # ====================== SCENE OVERRIDE ======================
        if desired_brightness is not None:
            for light_name in light_list:
                if reed_manager.get_effective_state(reed_name):  # reed closed
                    continue
                mode = desired_mode or "white"
                if light_name in RGB_LIGHTS:
                    set_rgb_bug_light(light_name, desired_brightness, mode)
                else:
                    pwm = int(desired_brightness * 2.55)
                    send_command(f"RAMP {LIGHT_MAP.get(light_name)} {pwm} {ramp}")
                ramp_and_broadcast(light_name, desired_brightness, ramp,
                                   mode if light_name in RGB_LIGHTS else None, 
                                   source="scene")
            return

        # ====================== NORMAL REED / PHASE / FORCE HANDLING ======================
        effective_closed = reed_manager.get_effective_state(reed_name)

        final_closed = effective_closed

        if reed_name in reed_manager.interlocks:
            if not reed_manager.is_interlock_satisfied(reed_name):
                final_closed = True
                logger.debug(f"🛡️ Interlock safety net: {reed_name} forced CLOSED")

        phase = phase_manager.get_phase()

        for light_name in light_list:
            if final_closed:  # CLOSED → turn off
                if light_name in RGB_LIGHTS:
                    set_rgb_bug_light(light_name, 0, "white")
                else:
                    send_command(f"RAMP {LIGHT_MAP.get(light_name)} 0 {ramp}")

                ramp_and_broadcast(light_name, 0, ramp,
                                   source="reed" if not is_phase_change else "phase change")

            else:
                settings = reed_manager.get_light_settings(phase, light_name)
                if settings is None:
                    logger.debug(f"No {phase} setting for light '{light_name}' – leaving unchanged")
                    continue

                brightness, mode = settings

                if light_name in RGB_LIGHTS:
                    set_rgb_bug_light(light_name, brightness, mode)
                else:
                    pwm = int(brightness * 2.55)
                    send_command(f"RAMP {LIGHT_MAP.get(light_name)} {pwm} {ramp}")

                ramp_and_broadcast(light_name, brightness, ramp,
                                   mode if light_name in RGB_LIGHTS else None,
                                   source="reed" if not is_phase_change else "phase change")

    return trigger


# ====================== WRAPPERS ======================
def send_command(cmd: str):
    return arduino.send_command(cmd)

def set_rgb_bug_light(name: str, brightness: int, mode: str = 'white'):
    return arduino.set_rgb_bug_light(name, brightness, mode)

def read_all_states():
    arduino.read_all_states()
    socketio.emit('state_update', state.copy())
    logger.debug(f"Final synced state: {state}")


# ====================== INSTANCES ======================
gpio_manager = GPIODeviceManager(config)

reed_manager = ReedManager(
    config,
    gpio_manager=gpio_manager,
    socketio=socketio,
    rgb_lights=RGB_LIGHTS,
    light_map=LIGHT_MAP,
    set_rgb_bug_light=set_rgb_bug_light,
    send_command=send_command,
    ramp_and_broadcast=ramp_and_broadcast,
    toast_manager=toast_manager
)

gps = None
phase_manager = None
sensor_manager = None


# ====================== BACKGROUND SYNC ======================
def background_state_sync():
    while not shutdown_event.is_set():
        time.sleep(BACKGROUND_SYNC_INTERVAL)
        try:
            if arduino.ser and arduino.ser.is_open and not shutdown_event.is_set():
                read_all_states()
        except Exception as e:
            if not shutdown_event.is_set():
                logger.debug(f"Background sync skipped: {e}")
            else:
                break


# ====================== ROUTES ======================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/diag')
def diagnostics():
    return render_template('diag.html')

@app.route('/gps_json')
def gps_json():
    data = gps.get_state() if gps else {}

    if phase_manager:
        data['phase'] = phase_manager.get_phase()
        data['forced'] = phase_manager.is_forced()
        try:
            data.update(phase_manager.get_phase_times() or {})
        except Exception as e:
            logger.warning(f"Failed to get phase times: {e}")

    if gps:
        fix_quality = gps.state.get("fix_quality", 0)
        current_suburb = gps.state.get("suburb")
        last_known = gps.state.get("last_known_suburb")

        if gps.state.get("force_no_fix"):
            data['fallback_suburb'] = last_known or "No GPS Fix"
        elif fix_quality >= 1:
            data['fallback_suburb'] = current_suburb or "Acquiring location..."
        elif last_known:
            data['fallback_suburb'] = f"{last_known} (Last known)"
        else:
            data['fallback_suburb'] = "Waiting for GPS"
    else:
        data['fallback_suburb'] = "No GPS Module"

    return data

@app.route('/reed_json')
def reed_json():
    return {
        'states': reed_manager.get_states(),
        'forced': reed_manager.get_forced_states()
    }

@app.route('/api/themes')
def get_themes():
    themes = []
    seen = set()
    directories = [
        os.path.join(app.static_folder, 'css/themes'),
        os.path.join(app.static_folder, 'css')
    ]

    def process_css_file(filepath: str):
        filename = os.path.basename(filepath)
        if not filename.endswith('.css'):
            return
        base_name = filename[:-4]
        if base_name in seen:
            return
        seen.add(base_name)

        display_name = base_name.replace('-', ' ').replace('_', ' ').title()
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                first = f.readline().strip()
                if first.startswith('/*') and first.endswith('*/'):
                    comment = first[2:-2].strip()
                    if comment:
                        display_name = comment
        except Exception:
            pass

        themes.append({'file': base_name, 'name': display_name})

    for directory in directories:
        if os.path.exists(directory):
            try:
                for fn in os.listdir(directory):
                    process_css_file(os.path.join(directory, fn))
            except Exception as e:
                logger.warning(f"Failed to list themes in {directory}: {e}")

    themes.sort(key=lambda x: (x['name'].lower() != 'base', x['name'].lower()))
    return {'themes': themes}

@app.route('/api/current-theme')
def get_current_theme():
    return {'theme': current_global_theme}

@app.route('/api/current-dark-mode')
def get_current_dark_mode():
    return {'mode': phase_manager.get_current_dark_mode() if phase_manager else 'dark'}


# ====================== SOCKETIO ======================
@socketio.on('light_change')
def handle_light_change(data):
    name = data['name']
    target = max(0, min(100, int(data.get('brightness', 0))))
    mode = data.get('mode', 'white') if name in RGB_LIGHTS else None

    if name in RGB_LIGHTS:
        set_rgb_bug_light(name, target, mode or "white")
    elif name in LIGHT_MAP:
        pwm = int(target * 2.55)
        send_command(f"RAMP {LIGHT_MAP[name]} {pwm} {UI_RAMP_TIME_MS}")

    ramp_and_broadcast(name, target, UI_RAMP_TIME_MS, mode, source="user interface")

    if name in RGB_LIGHTS and mode:
        state[f"{name}_mode"] = mode


@socketio.on('force_reed')
def handle_force_reed(data):
    name = data.get('name')
    closed = data.get('closed')
    if name is None:
        return
    if closed is None:
        if name == 'all':
            reed_manager.clear_all_forces()
        else:
            reed_manager.clear_force(name)
    else:
        reed_manager.force_state(name, bool(closed))


@socketio.on('force_phase')
def handle_force_phase(data):
    if not phase_manager:
        return
    phase = data.get('phase')
    if phase is None:
        phase_manager.clear_force()
    else:
        phase_manager.force_phase(phase)


@socketio.on('connect')
def handle_connect(sid=None):
    global first_state_read_done
    logger.debug(f"🔌 Client connected from {request.remote_addr or 'unknown'} (SID: {sid})")
    
    emit('lights_config', arduino.get_frontend_config())
    emit('screens_init', {
        'screens': {
            name: {
                'on': reed_manager.screen_states.get(name, False),
                'online': True,
                'config': {
                    'friendly': conf.get('friendly', name),
                    'icon': conf.get('icon', 'fa-display'),
                    'host': conf.get('host')
                }
            }
            for name, conf in reed_manager.screens.items()
        }
    })
    
    if not first_state_read_done:
        logger.debug("🔄 First connection — reading full state from hardware")
        read_all_states()
        first_state_read_done = True
    else:
        logger.debug("📤 Sending cached state to new client")
    
    emit('state_update', state.copy())
    
    if phase_manager:
        emit('global_dark_mode_update', {
            'mode': phase_manager.get_current_dark_mode(),
            'manual': phase_manager.manual_dark_mode is not None
        })
    else:
        emit('global_dark_mode_update', {'mode': 'dark'})
    
    if gps:
        emit('gps_update', gps.get_state())
    
    emit('reed_update', {
        'states': reed_manager.get_states(),
        'forced': reed_manager.get_forced_states()
    })
    
    phase_data = {
        'phase': phase_manager.get_phase() if phase_manager else 'Day',
        'forced': phase_manager.is_forced() if phase_manager else False,
    }
    if phase_manager:
        try:
            phase_data.update(phase_manager.get_phase_times())
        except Exception as e:
            logger.warning(f"Failed to get phase times: {e}")
    
    emit('phase_update', phase_data)
    
    if phase_manager:
        current_mode = phase_manager.get_current_dark_mode()
        manual = phase_manager.manual_dark_mode is not None
        emit('global_dark_mode_update', {
            'mode': current_mode,
            'manual': manual
        })
    else:
        emit('global_dark_mode_update', {'mode': 'dark', 'manual': False})


@socketio.on('relay_change')
def handle_relay_change(data):
    name = data.get('name')
    on = bool(data.get('on', False))

    device = gpio_manager.get_relay(name)
    if not device:
        logger.warning(f"Unknown relay: {name}")
        return

    logger.info(f"💡 {name} turned {'ON' if on else 'OFF'} [user interface]")

    try:
        if on:
            device.on()
        else:
            device.off()
    except Exception as e:
        logger.error(f"Relay {name} failed: {e}")

    state[name] = on
    socketio.emit('state_update', state.copy())


@socketio.on('set_scene')
def handle_set_scene(data):
    scene = data.get('scene')
    if not scene:
        return

    from modules.scenes import activate_scene

    success = activate_scene(
        main_config=config,
        scene_name=scene,
        ramp_and_broadcast=ramp_and_broadcast,
        set_rgb_bug_light=set_rgb_bug_light,
        send_command=send_command,
        state=state,
        LIGHT_MAP=LIGHT_MAP,
        RGB_LIGHTS=RGB_LIGHTS,
        reed_manager=reed_manager
    )

    if success:
        socketio.emit('state_update', state.copy())
        
        
@app.route('/api/scenes')
def get_scenes():
    from modules.scenes import get_all_scenes
    scenes = get_all_scenes(config)
    
    scene_list = [
        {
            "key": key,
            "name": data["name"],
            "icon": data["icon"],
            "description": data["description"],
            "all_off": data["all_off"]
        }
        for key, data in scenes.items()
    ]
    return {"scenes": scene_list}


@socketio.on('set_gps_simulation')
def handle_gps_simulation(data):
    no_fix = bool(data.get('no_fix', False))
    if gps and hasattr(gps, 'set_no_fix_simulation'):
        gps.set_no_fix_simulation(no_fix)


@socketio.on('set_global_theme')
def handle_set_global_theme(data):
    global current_global_theme
    theme = data.get('theme')
    if not theme:
        return

    available = [t['file'] for t in get_themes()['themes']]
    if theme not in available:
        logger.warning(f"Unknown theme '{theme}' rejected")
        return

    current_global_theme = theme
    theme_config.save({'theme': theme})
    
    friendly = get_friendly_theme_name(theme)
    logger.info(f"🎨 Theme changed to: {friendly} ({theme}.css)")
    
    emit('global_theme_update', {'theme': theme}, broadcast=True, include_self=True)


@socketio.on('set_global_dark_mode')
def handle_set_global_dark_mode(data):
    mode = data.get('mode')
    if mode not in ('dark', 'light'):
        return

    if phase_manager:
        phase_manager.set_manual_dark_mode(mode)
    else:
        dark_mode_config.save({'mode': mode, 'manual': True})
    
    emit('global_dark_mode_update', {
        'mode': mode,
        'manual': True
    }, broadcast=True, include_self=True)
        

@socketio.on('toast_test')
def handle_toast_test(data):
    if toast_manager:
        toast_manager.send_toast(
            title=data.get('title'),
            message=data.get('message', 'Test message'),
            toast_type=data.get('type', 'info'),
            duration=data.get('duration', 4500),
            persistent=data.get('persistent', False)
        )
        logger.info(f"🍞 Toast test: {data.get('type')} - {data.get('message')[:60]}")
    else:
        logger.warning("Toast test received but toast_manager is not available")
        
        
@socketio.on('screen_manual_toggle')
def handle_screen_manual_toggle(data):
    """Manual test button for turning screens on/off from diagnostics page"""
    name = data.get('name')
    force_on = data.get('on')  # True = wake, False = sleep, None = toggle

    if name not in reed_manager.screens:
        logger.warning(f"❌ Unknown screen: {name}")
        return

    if force_on is None:
        force_on = not reed_manager.screen_states.get(name, False)

    if force_on:
        reed_manager._wake_screen(name)
    else:
        reed_manager._sleep_screen(name)
        
        
@socketio.on('sonos_command')
def handle_sonos_command(data):
    if 'sonos' not in globals() or not sonos:
        emit('toast', {'type': 'error', 'message': 'Sonos module not loaded'})
        return
    
    result = sonos.execute_command(data)
    if 'error' in result:
        emit('toast', {'type': 'error', 'message': f"Sonos: {result['error']}"})
        
        
@app.route('/api/version')
def get_version_route():
    return {
        "version": APP_VERSION,
        "base_version": APP_VERSION.split('.')[:3],  # e.g. ["3","0","1"]
        "full": APP_VERSION,
        "built": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    
    
@app.route('/screen_json')
def screen_json():
    """Basic screen data for initial load"""
    screens_data = {}
    for name, conf in reed_manager.screens.items():
        screens_data[name] = {
            'on': reed_manager.screen_states.get(name, False),
            'online': True,                    # optimistic
            'latency': None,
            'config': {
                'friendly': conf.get('friendly', name),
                'icon': conf.get('icon', 'fa-display'),
                'host': conf.get('host')
            }
        }
    return {'screens': screens_data}
    
@app.route('/screen_status_json')
def screen_status_json():
    """Full status including connectivity test"""
    if not hasattr(reed_manager, 'test_screen_connectivity'):
        return {'screens': {}, 'error': 'test_screen_connectivity not available'}

    result = {}
    for name, conf in reed_manager.screens.items():
        conn = reed_manager.test_screen_connectivity(name)
        
        result[name] = {
            'on': reed_manager.screen_states.get(name, False),
            'online': conn.get('online', False),
            'latency': conn.get('latency'),
            'last_checked': conn.get('last_checked'),
            'config': {
                'friendly': conf.get('friendly', name),
                'icon': conf.get('icon', 'fa-display'),
                'host': conf.get('host')
            }
        }
    return {'screens': result}


# ====================== CLEANUP ======================
def cleanup():
    logger.info("🧹 Cleaning up...")
    shutdown_event.set()
    
    if 'sonos' in globals() and sonos:
        sonos.stop()
    
    time.sleep(0.5)
    for name in list(active_ramps.keys()):
        cancel_ramp(name)
    try:
        if phase_manager: phase_manager.stop()
        if reed_manager: reed_manager.stop()
        if gpio_manager: gpio_manager.cleanup()
        if sensor_manager: sensor_manager.stop()
        if arduino: arduino.cleanup()
    except Exception as e:
        logger.error(f"⚠️ Error during cleanup: {e}")
    logger.info("🌙💤 Pissmole has left the campsite, goodbye!")

if __name__ == "__main__":
    logger.info("✅ System starting...")
    
    arduino.init_serial()
    gpio_manager.init_devices()

    sensor_manager = SensorManager(config, arduino.send_command, socketio)

    for reed_name in list(gpio_manager.reeds.keys()):
        reed_manager.register_trigger(reed_name, make_reed_trigger(reed_name))

    reed_manager.start_monitor(interval=REED_MONITOR_INTERVAL)
    sensor_manager.start()

    gps = GPSModule(config, socketio)
    gps.init_gps()
    gps.init_geolocator()

    phase_manager = PhaseManager(config, gps, socketio, dark_mode_config)
    phase_manager.reed_manager = reed_manager
    reed_manager.phase_manager = phase_manager
    phase_manager.start()
    
    reed_manager.apply_initial_ambient_state()
    reed_manager.apply_initial_screen_states()

    if getattr(gps, 'serial', None):
        gps.start_reader()

    global sonos
    try:
        sonos = SonosManager(socketio, config)
        sonos.start()
        logger.info("✅ Sonos integration loaded successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize SonosManager: {e}", exc_info=True)
        sonos = None

    threading.Thread(target=background_state_sync, daemon=True).start()

    logger.info("🎉🎉🎉 The Pissmole Camper Control System lives! 🎉🎉🎉")

    # ====================== START SOCKETIO ======================
    try:
        socketio.run(
            app,
            host=config.get('system', 'host', fallback='0.0.0.0'),
            port=config.getint('system', 'port', fallback=5000),
            debug=config.getboolean('system', 'debug', fallback=False),
            use_reloader=False,
            allow_unsafe_werkzeug=True
        )
    except (KeyboardInterrupt, SystemExit):
        logger.info("\n🛑 Shutdown requested...")
    finally:
        cleanup()