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

def log_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.critical("💥 Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = log_exception

# ====================== LOGGING ======================
from modules.logger import setup_logging
logger = setup_logging(logging.INFO)

if hasattr(sys, '_pccs_already_started'):
    logger.warning("⚠️ Module reloaded - skipping duplicate initialization")
else:
    sys._pccs_already_started = True

logging.getLogger("werkzeug").setLevel(logging.WARNING)
logging.getLogger("engineio").setLevel(logging.WARNING)
logging.getLogger("socketio").setLevel(logging.WARNING)

# ====================== CONFIG ======================
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
            logger.info(f"💾 Saved config: {self.path}")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")


theme_config = ConfigManager('active_theme.json', {'theme': 'stealth'})
dark_mode_config = ConfigManager('active_dark_mode.json', {'mode': 'dark'})

current_global_theme = theme_config.load()['theme']
logger.info(f"🎨 Loaded theme: {current_global_theme}")

# ====================== CONSTANTS & GLOBALS ======================
UI_RAMP_TIME_MS = 1000
first_state_read_done = False

# ====================== MODULES ======================
from modules.gps import GPSModule
from modules.gpio import GPIODeviceManager
from modules.reeds import ReedManager
from modules.phases import PhaseManager
from modules.sensors import SensorManager
from modules.arduino import ArduinoManager
from modules.scenes import activate_scene
from modules.toasts import ToastManager, toast_manager

app = Flask(__name__)
app.config['SECRET_KEY'] = 'pccs-secret'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ====================== TOASTS ======================
toast_manager = ToastManager(socketio)
import modules.toasts
modules.toasts.toast_manager = toast_manager

# ====================== ARDUINO ======================
arduino = ArduinoManager()
LIGHT_MAP = arduino.LIGHT_MAP
RGB_LIGHTS = arduino.RGB_LIGHTS
RGB_BUG_LIGHTS = arduino.RGB_BUG_LIGHTS

state = {name: 0 for name in list(LIGHT_MAP.keys()) + list(RGB_BUG_LIGHTS.keys())}
state.update({"floodlights": False, "kitchen_panel_mode": "white", "awning_mode": "white"})
arduino.state = state

# ====================== GPIO ======================
GPIO_DEVICES = {
    'floodlights': {'type': 'output', 'pin': 17, 'active_high': False, 'initial': False},
    'kitchen_panel': {'type': 'input', 'pin': 23, 'pull_up': True, 'bounce_time': 0.5},
    'kitchen_bench': {'type': 'input', 'pin': 12, 'pull_up': True, 'bounce_time': 0.5},
    'storage_panel': {'type': 'input', 'pin': 24, 'pull_up': True, 'bounce_time': 0.5},
    'rear_drawer': {'type': 'input', 'pin': 25, 'pull_up': True, 'bounce_time': 0.5},
    'rooftop_tent': {'type': 'input', 'pin': 26, 'pull_up': True, 'bounce_time': 0.5},
}

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
    if name == 'rooftop_tent' and target > 0:
        effective = reed_manager.get_effective_state('rooftop_tent') if 'reed_manager' in globals() else None
        physical_closed = (reed_manager.gpio.reed_states.get('rooftop_tent', True)
                          if 'reed_manager' in globals() and hasattr(reed_manager, 'gpio') else True)

        if effective is True:
            logger.warning(f"🔥 rooftop_tent cannot turn on while closed (requested {target}%)")
            return 0
        elif effective is False and physical_closed and source == "user interface":
            warning_key = f"{name}_circuit_warning"
            if warning_key not in active_warnings:
                active_warnings.add(warning_key)
                logger.warning("🔥 rooftop_tent light turned on with physical reed closed - Ensure the lighting circuit is off")
                threading.Timer(30.0, lambda k=warning_key: active_warnings.discard(k)).start()
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
                colour = "🔴" if mode == "red" else "⚪" if mode == "white" else ""
                mode_str = f" {mode.title()} mode" if mode and mode != "white" else ""
                logger.info(f"💡{colour} {name} → {target}%{mode_str} [{source}]")
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


# ====================== UNIFIED REED TRIGGER ======================
def make_reed_trigger(reed_name: str):
    def trigger(is_closed: bool, is_phase_change: bool = False,
                desired_brightness: int = None, desired_mode: str = None):
        if not phase_manager or not reed_manager:
            return

        ramp = (phase_manager.get_phase_ramp_time() 
                if is_phase_change 
                else reed_manager.get_reed_ramp_time())

        # Scene override
        if desired_brightness is not None:
            if reed_manager.get_effective_state(reed_name):
                logger.debug(f"🚪 {reed_name} change ignored (reed closed) [scene]")
                return

            mode = desired_mode or "white"
            if reed_name in RGB_LIGHTS:
                set_rgb_bug_light(reed_name, desired_brightness, mode)
            else:
                pwm = int(desired_brightness * 2.55)
                send_command(f"RAMP {LIGHT_MAP.get(reed_name)} {pwm} {ramp}")

            ramp_and_broadcast(reed_name, desired_brightness, ramp,
                               mode if reed_name in RGB_LIGHTS else None, source="scene")
            return

        # Normal reed / phase logic
        effective_closed = reed_manager.get_effective_state(reed_name)
        if effective_closed is not None:
            is_closed = effective_closed

        phase = phase_manager.get_phase()

        if not is_closed:  # OPEN
            brightness, mode = reed_manager.get_light_settings(phase, reed_name)
            if reed_name in RGB_LIGHTS:
                set_rgb_bug_light(reed_name, brightness, mode)
            else:
                pwm = int(brightness * 2.55)
                send_command(f"RAMP {LIGHT_MAP.get(reed_name)} {pwm} {ramp}")

            ramp_and_broadcast(reed_name, brightness, ramp,
                               mode if reed_name in RGB_LIGHTS else None,
                               source="reed" if not is_phase_change else "phase change")
        else:  # CLOSED
            if reed_name in RGB_LIGHTS:
                set_rgb_bug_light(reed_name, 0, "white")
            else:
                send_command(f"RAMP {LIGHT_MAP.get(reed_name)} 0 {ramp}")

            ramp_and_broadcast(reed_name, 0, ramp,
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
gpio_manager = GPIODeviceManager()
reed_manager = ReedManager(
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
    while True:
        time.sleep(45)
        try:
            if arduino.ser and arduino.ser.is_open:
                read_all_states()
        except Exception as e:
            logger.debug(f"Background sync skipped: {e}")


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
            logger.warning(f"Failed to get phase times for gps_json: {e}")
    if gps:
        data['fallback_suburb'] = gps.FALLBACK_NAME
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
            for fn in os.listdir(directory):
                if fn.endswith('.css'):
                    process_css_file(os.path.join(directory, fn))

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
def handle_connect():
    global first_state_read_done
    logger.debug(f"🔌 Client connected from {request.remote_addr or 'unknown'}")
    
    if not first_state_read_done:
        logger.debug("🔄 First connection — reading full state from Arduino")
        read_all_states()
        first_state_read_done = True
    else:
        logger.debug("📤 Sending cached state to new client")
    
    emit('state_update', state.copy())
    
    if phase_manager:
        emit('global_dark_mode_update', {'mode': phase_manager.get_current_dark_mode()})
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


@socketio.on('flood_change')
def handle_flood_change(data):
    on = bool(data.get('on', False))
    logger.info(f"💡 Floodlights turned {'On' if on else 'Off'} [user interface]")
    state["floodlights"] = on
    device = gpio_manager.get_device('floodlights')
    if device:
        try:
            if on:
                device.on()
            else:
                device.off()
        except Exception as e:
            logger.error(f"⚠️ Floodlights error: {e}")
    socketio.emit('state_update', state)


@socketio.on('set_scene')
def handle_set_scene(data):
    scene = data.get('scene')
    if not scene:
        return
    logger.info(f"🎬 Scene activated: {scene}")
    success = activate_scene(
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
        logger.warning(f"⚠️ Unknown theme: {theme}")
        return

    current_global_theme = theme
    theme_config.save({'theme': theme})
    
    logger.info(f"🎨 Broadcasting global theme change → {theme}")
    
    # Force broadcast to ALL clients including sender
    socketio.emit('global_theme_update', {'theme': theme}, 
                  broadcast=True, 
                  include_self=True)

@socketio.on('set_global_dark_mode')
def handle_set_global_dark_mode(data):
    mode = data.get('mode')
    if mode in ('dark', 'light'):
        dark_mode_config.save({'mode': mode})
        logger.info(f"🌗 Theme mode changed to: {mode}")
        emit('global_dark_mode_update', {'mode': mode}, broadcast=True, include_self=True)
        

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
        logger.info(f"🧪 Toast test: {data.get('type')} - {data.get('message')[:60]}")
    else:
        logger.warning("Toast test received but toast_manager is not available")


# ====================== CLEANUP ======================
def cleanup():
    logger.info("🧹 Cleaning up resources...")
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
    logger.info("✅ Cleanup completed")


# ====================== STARTUP ======================
if __name__ == "__main__":
    logger.info("="*58)
    logger.info("🚐💦  Welcome to the Pissmole Camper Control System  💦🚐")
    logger.info("="*58)
    
    logger.info("✅ System starting...")
    
    arduino.init_serial()
    sensor_manager = SensorManager(send_command, socketio)
    gpio_manager.init_devices(GPIO_DEVICES)

    # Register unified reed triggers
    for reed_name in [n for n, d in GPIO_DEVICES.items() if d['type'] == 'input']:
        reed_manager.register_trigger(reed_name, make_reed_trigger(reed_name))

    reed_manager.start_monitor(interval=0.25)
    sensor_manager.start()

    gps = GPSModule(socketio)
    gps.init_gps()
    gps.init_geolocator()

    phase_manager = PhaseManager(gps, socketio)
    phase_manager.reed_manager = reed_manager
    reed_manager.phase_manager = phase_manager
    phase_manager.start()

    if getattr(gps, 'serial', None):
        gps.start_reader()

    threading.Thread(target=background_state_sync, daemon=True).start()

    logger.info("🎉🎉🎉 The Pissmole Camper Control System lives! 🎉🎉🎉")

    try:
        socketio.run(
            app,
            host="0.0.0.0",
            port=5000,
            debug=True,
            use_reloader=False,
            allow_unsafe_werkzeug=True
        )
    except (KeyboardInterrupt, SystemExit):
        logger.info("\n🛑 Shutdown requested...")
    finally:
        cleanup()