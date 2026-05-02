from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import threading
import time
import os
import logging
import sys
import math

def log_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.critical("💥 Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = log_exception

# ====================== LOGGING SETUP ======================
from modules.logger import setup_logging
logger = setup_logging(logging.INFO)
logging.getLogger("werkzeug").setLevel(logging.WARNING)
logging.getLogger("engineio").setLevel(logging.WARNING)
logging.getLogger("socketio").setLevel(logging.WARNING)

# ====================== USER CONFIG ======================
UI_RAMP_TIME_MS = 1000      # Ramp time for manual slider / UI changes (ms)

# ====================== RAMP CONTROL ======================
active_ramps: dict[str, threading.Timer] = {}
active_warnings: set[str] = set()

# ====================== MODULES ======================
from modules.gps import GPSModule
from modules.gpio import GPIODeviceManager
from modules.reeds import ReedManager
from modules.phases import PhaseManager
from modules.sensors import SensorManager
from modules.arduino import ArduinoManager
from modules.scenes import activate_scene

app = Flask(__name__)
app.config['SECRET_KEY'] = 'pccs-secret'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ====================== REAL-TIME LOG HANDLER ======================
class SocketIOHandler(logging.Handler):
    def emit(self, record):
        try:
            log_entry = self.format(record)
            socketio.emit('new_log', {
                'timestamp': time.strftime('%H:%M:%S'),
                'level': record.levelname,
                'message': log_entry,
                'full': f"[{time.strftime('%H:%M:%S')}] {record.levelname:8} {record.getMessage()}"
            }, broadcast=True)
        except Exception:
            pass

socket_handler = SocketIOHandler()
socket_handler.setLevel(logging.DEBUG)  # Capture everything
formatter = logging.Formatter('%(message)s')
socket_handler.setFormatter(formatter)

if not any(isinstance(h, SocketIOHandler) for h in logger.handlers):
    logger.addHandler(socket_handler)
    logger.info("📡 SocketIO log handler attached")

# ====================== STATE SYNC CONTROL ======================
first_state_read_done = False   # Ensures we only do full Arduino read on first connection

# ====================== ARDUINO ======================
arduino = ArduinoManager()
LIGHT_MAP = arduino.LIGHT_MAP
RGB_BUG_LIGHTS = arduino.RGB_BUG_LIGHTS
RGB_LIGHTS = arduino.RGB_LIGHTS
__all__ = ['RGB_LIGHTS', 'LIGHT_MAP', 'set_rgb_bug_light', 'send_command', 'ramp_and_broadcast']

# Current state cache
state = {name: 0 for name in list(LIGHT_MAP.keys()) + list(RGB_BUG_LIGHTS.keys())}
state["floodlights"] = False
state["kitchen_panel_mode"] = "white"
state["awning_mode"] = "white"

arduino.state = state  # Link shared state

# GPIO Configuration
GPIO_DEVICES = {
    # Floodlights - Digital Output
    'floodlights': {
        'type': 'output',
        'pin': 17,
        'active_high': False,
        'initial': False
    },
    # Reed Switches - Digital Inputs
    'kitchen_panel':  {'type': 'input', 'pin': 23, 'pull_up': True, 'bounce_time': 0.5},
    'kitchen_bench':  {'type': 'input', 'pin': 12, 'pull_up': True, 'bounce_time': 0.5},
    'storage_panel':  {'type': 'input', 'pin': 24, 'pull_up': True, 'bounce_time': 0.5},
    'rear_drawer':    {'type': 'input', 'pin': 25, 'pull_up': True, 'bounce_time': 0.5},
    'rooftop_tent':   {'type': 'input', 'pin': 26, 'pull_up': True, 'bounce_time': 0.5},
}

# ====================== ARDUINO WRAPPERS (unchanged interface) ======================
def send_command(cmd: str):
    return arduino.send_command(cmd)

def set_rgb_bug_light(name: str, brightness: int, mode: str = 'white'):
    return arduino.set_rgb_bug_light(name, brightness, mode)

def read_all_states():
    arduino.read_all_states()
    socketio.emit('state_update', state.copy())
    logger.debug(f"Final synced state: {state}")

# ====================== LIGHT CONTROL ======================
def set_floodlights(on: bool):
    global state
    state["floodlights"] = on
    device = gpio_manager.get_device('floodlights')
    if device:
        try:
            if on:
                device.on()
            else:
                device.off()
            return True
        except Exception as e:
            logger.error(f"⚠️ Floodlights error: {e}")
            return False
    else:
        logger.error("⚠️ Floodlights device not initialized")
        return False

# ====================== SMOOTH RAMP BROADCAST (OPTIMISTIC) ======================
def cancel_ramp(name: str):
    """Cancel any active ramp for a light"""
    if name in active_ramps:
        try:
            active_ramps[name].cancel()
        except:
            pass
        active_ramps.pop(name, None)

def ramp_and_broadcast(name: str, target: int, duration_ms: int, mode: str | None = None, source: str | None = None):
    if name not in state:
        return

    # === Rooftop tent safety check ===
    if name == 'rooftop_tent' and target > 0:
        effective = reed_manager.get_effective_state('rooftop_tent') if reed_manager else None
        physical_closed = (reed_manager.gpio.reed_states.get('rooftop_tent', True)
                          if reed_manager and hasattr(reed_manager, 'gpio') else True)

        if effective is True:
            logger.warning(f"🔥 rooftop_tent cannot turn on while closed (requested {target}%)")
            target = 0

        elif effective is False and physical_closed:
            if source == "user interface":
                warning_key = f"{name}_circuit_warning"
                if warning_key not in active_warnings:
                    active_warnings.add(warning_key)
                    logger.warning(
                        f"🔥 rooftop_tent light turned on with physical reed closed - Ensure the lighting circuit is off"
                    )
                    threading.Timer(30.0, lambda k=warning_key: active_warnings.discard(k)).start()

    cancel_ramp(name)

    start = state.get(name, 0)

    # === MODE HANDLING FIRST ===
    mode_changed = False
    if name in RGB_LIGHTS:
        if mode is not None:
            old_mode = state.get(f"{name}_mode")
            if old_mode != mode:
                mode_changed = True
                logger.debug(f"🎨 Mode change for {name}: {old_mode} → {mode}")
            state[f"{name}_mode"] = mode
        elif f"{name}_mode" in state:
            state.pop(f"{name}_mode", None)

    if start == target and not mode_changed:
        return

    steps = max(8, int(duration_ms / 50))
    delay = duration_ms / steps / 1000.0

    logger.debug(f"↗️ Starting optimistic ramp {name} {start}→{target}% "
                 f"{'[' + mode + ']' if mode else ''} ({duration_ms}ms)")

    def ramp_step(i: int):
        if i > steps:
            # Final step
            state[name] = target
            socketio.emit('state_update', state.copy())

            if source:
                colour = ""
                mode_str = ""

                if name in RGB_LIGHTS and mode:
                    if mode == "red":
                        colour = "🔴"
                    elif mode == "white":
                        colour = "⚪"
                    if mode != "white":
                        mode_str = f" {mode.title()} mode"

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


# ====================== MODULE INSTANCES ======================
gpio_manager = GPIODeviceManager()

reed_manager = ReedManager(
    gpio_manager=gpio_manager,
    socketio=socketio,
    rgb_lights=RGB_LIGHTS,
    light_map=LIGHT_MAP,
    set_rgb_bug_light=set_rgb_bug_light,
    send_command=send_command,
    ramp_and_broadcast=ramp_and_broadcast
)

gps = None
phase_manager = None
sensor_manager = None

# ====================== BACKGROUND STATE SYNC ======================
def background_state_sync():
    """Periodically re-sync with Arduino in case of drift or missed updates"""
    while True:
        time.sleep(45)  # Check every 45 seconds
        try:
            if arduino.ser and arduino.ser.is_open:
                logger.debug("🔄 Background state sync running...")
                read_all_states()
                socketio.emit('state_update', state.copy())
        except Exception as e:
            logger.debug(f"Background sync skipped: {e}")

# ====================== REED TRIGGERS ======================
def make_reed_trigger(reed_name: str):
    light_name = reed_name

    def trigger(is_closed: bool, is_phase_change: bool = False, 
                desired_brightness: int = None, desired_mode: str = None):
        if not phase_manager or not reed_manager:
            return

        ramp = (phase_manager.get_phase_ramp_time() 
                if is_phase_change 
                else reed_manager.get_reed_ramp_time())

        # ====================== SCENE OVERRIDE ======================
        if desired_brightness is not None:
            # CENTRAL SAFETY CHECK - works for ANY reed light
            if reed_manager.get_effective_state(light_name):
                logger.debug(f"🚪 {light_name} change ignored (reed closed) [scene]")
                return

            brightness = desired_brightness
            mode = desired_mode or "white"

            if light_name in RGB_LIGHTS:
                set_rgb_bug_light(light_name, brightness, mode)
            else:
                pwm = int(brightness * 2.55)
                send_command(f"RAMP {LIGHT_MAP[light_name]} {pwm} {ramp}")

            ramp_and_broadcast(light_name, brightness, ramp, 
                               mode if light_name in RGB_LIGHTS else None,
                               source="scene")
            return

        # ====================== NORMAL REED / PHASE LOGIC ======================
        phase = phase_manager.get_phase()
        
        effective_closed = reed_manager.get_effective_state(reed_name)
        if effective_closed is not None:
            is_closed = effective_closed

        if not is_closed:   # OPEN
            brightness, mode = reed_manager.get_light_settings(phase, light_name)
            if light_name in RGB_LIGHTS:
                set_rgb_bug_light(light_name, brightness, mode)
            else:
                pwm = int(brightness * 2.55)
                send_command(f"RAMP {LIGHT_MAP[light_name]} {pwm} {ramp}")

            ramp_and_broadcast(light_name, brightness, ramp, 
                               mode if light_name in RGB_LIGHTS else None,
                               source="reed" if not is_phase_change else "phase change")
        else:  # CLOSED
            if light_name in RGB_LIGHTS:
                set_rgb_bug_light(light_name, 0, "white")
            else:
                send_command(f"RAMP {LIGHT_MAP[light_name]} 0 {ramp}")

            ramp_and_broadcast(light_name, 0, ramp, 
                               source="reed" if not is_phase_change else "phase change")

    return trigger

# ====================== SPECIAL KITCHEN LOGIC ======================
def make_kitchen_panel_trigger():
    def trigger(is_closed: bool, is_phase_change: bool = False,
                desired_brightness: int = None, desired_mode: str = None):
        if not phase_manager or not reed_manager:
            return

        ramp = (phase_manager.get_phase_ramp_time() 
                if is_phase_change 
                else reed_manager.get_reed_ramp_time())
        phase = phase_manager.get_phase()

        # ====================== SCENE OVERRIDE ======================
        if desired_brightness is not None:
            if reed_manager.get_effective_state("kitchen_panel"):   # closed
                logger.debug("🚪 kitchen_panel change ignored (panel closed) [scene]")
                return

            # Panel is open → apply scene
            set_rgb_bug_light("kitchen_panel", desired_brightness, desired_mode or "white")
            ramp_and_broadcast("kitchen_panel", desired_brightness, ramp, 
                               desired_mode or "white", source="scene")

            # Turn on bench too
            bright_b, _ = reed_manager.get_light_settings(phase, "kitchen_bench")
            pwm = int(bright_b * 2.55)
            send_command(f"RAMP {LIGHT_MAP['kitchen_bench']} {pwm} {ramp}")
            ramp_and_broadcast("kitchen_bench", bright_b, ramp, source="scene")
            return

        # ====================== NORMAL REED LOGIC ======================
        effective_closed = reed_manager.get_effective_state("kitchen_panel")
        if effective_closed is not None:
            is_closed = effective_closed

        if not is_closed:  # Panel OPEN
            bright_p, mode_p = reed_manager.get_light_settings(phase, "kitchen_panel")
            set_rgb_bug_light("kitchen_panel", bright_p, mode_p)
            ramp_and_broadcast("kitchen_panel", bright_p, ramp, mode_p, 
                               source="reed" if not is_phase_change else "phase change")

            if not reed_manager.get_effective_state("kitchen_bench"):
                bright_b, _ = reed_manager.get_light_settings(phase, "kitchen_bench")
                pwm = int(bright_b * 2.55)
                send_command(f"RAMP {LIGHT_MAP['kitchen_bench']} {pwm} {ramp}")
                ramp_and_broadcast("kitchen_bench", bright_b, ramp, 
                                   source="reed" if not is_phase_change else "phase change")
        else:  # CLOSED
            set_rgb_bug_light("kitchen_panel", 0, "white")
            ramp_and_broadcast("kitchen_panel", 0, ramp, 
                               source="reed" if not is_phase_change else "phase change")

            send_command(f"RAMP {LIGHT_MAP['kitchen_bench']} 0 {ramp}")
            ramp_and_broadcast("kitchen_bench", 0, ramp, 
                               source="reed" if not is_phase_change else "phase change")

    return trigger

def make_kitchen_bench_trigger():
    def trigger(is_closed: bool, is_phase_change: bool = False,
                desired_brightness: int = None, desired_mode: str = None):
        if not phase_manager or not reed_manager:
            return

        # Panel is closed → always ignore bench
        if reed_manager.get_effective_state("kitchen_panel"):
            if desired_brightness is not None:
                logger.debug("🚪 kitchen_bench change ignored (panel closed) [scene]")
            else:
                logger.debug("🚪 kitchen_bench change ignored (panel closed)")
            return

        ramp = (phase_manager.get_phase_ramp_time() 
                if is_phase_change 
                else reed_manager.get_reed_ramp_time())
        phase = phase_manager.get_phase()

        if desired_brightness is not None or not is_closed:
            brightness = desired_brightness if desired_brightness is not None \
                        else reed_manager.get_light_settings(phase, "kitchen_bench")[0]

            pwm = int(brightness * 2.55)
            send_command(f"RAMP {LIGHT_MAP['kitchen_bench']} {pwm} {ramp}")
            ramp_and_broadcast("kitchen_bench", brightness, ramp, 
                               source="scene" if desired_brightness is not None else "reed")
        else:
            send_command(f"RAMP {LIGHT_MAP['kitchen_bench']} 0 {ramp}")
            ramp_and_broadcast("kitchen_bench", 0, ramp, source="reed")

    return trigger

# ====================== SOCKETIO ======================
@socketio.on('light_change')
def handle_light_change(data):
    name = data['name']
    target = max(0, min(100, int(data.get('brightness', 0))))
    mode = data.get('mode', 'white')

    is_rgb = name in RGB_LIGHTS

    if not is_rgb:
        mode = None

    if is_rgb:
        set_rgb_bug_light(name, target, mode or "white")
    elif name in LIGHT_MAP:
        pwm = int(target * 2.55)
        send_command(f"RAMP {LIGHT_MAP[name]} {pwm} {UI_RAMP_TIME_MS}")

    ramp_and_broadcast(name, target, UI_RAMP_TIME_MS, mode, source="user interface")

    if is_rgb:
        state[f"{name}_mode"] = mode or "white"


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
    logger.debug(f"🔌 Client connected from {request.remote_addr or 'unknown'}")
    
    global first_state_read_done
    if not first_state_read_done:
        logger.debug("🔄 First connection — reading full state from Arduino")
        read_all_states()
        first_state_read_done = True
    else:
        logger.debug("📤 Sending cached state to new client")
    
    emit('state_update', state)
    
    if gps:
        emit('gps_update', gps.get_state())
    
    emit('reed_update', {
        'states': reed_manager.get_states(),
        'forced': reed_manager.get_forced_states()
    })
    emit('phase_update', {
        'phase': phase_manager.get_phase() if phase_manager else 'Day',
        'forced': phase_manager.is_forced() if phase_manager else False,
        **(phase_manager.get_phase_times() if phase_manager else {})
    })


@socketio.on('flood_change')
def handle_flood_change(data):
    on = bool(data.get('on', False))

    logger.info(f"💡 Floodlights turned {'On' if on else 'Off'} [user interface]")

    set_floodlights(on)
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
        logger.debug(f"🎬 Scene '{scene}' applied successfully")
    else:
        logger.warning(f"⚠️ Unknown scene requested: {scene}")


@socketio.on('set_gps_simulation')
def handle_gps_simulation(data):
    """Handle 'No GPS Fix' simulation toggle from the diag page."""
    no_fix = bool(data.get('no_fix', False))
    if hasattr(gps, 'set_no_fix_simulation'):   # 'gps' is your GPSModule instance
        gps.set_no_fix_simulation(no_fix)
    else:
        logger.error("GPS module not initialized")


# ====================== GPS ======================
def init_gps_module():
    global gps
    gps = GPSModule(socketio)
    gps.init_gps()
    gps.init_geolocator()


# ====================== ROUTES ======================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/gps')
def gps_diagnostics():
    return render_template('gps.html', gps=gps.get_state() if gps else {})

@app.route('/reeds')
def reed_diagnostics():
    return render_template('reeds.html')

@app.route('/gps_json')
def gps_json():
    data = gps.get_state() if gps else {}
    
    if phase_manager:
        data['phase'] = phase_manager.get_phase()
        data['forced'] = phase_manager.is_forced()
        data.update(phase_manager.get_phase_times())
    
    if gps:
        data['fallback_suburb'] = gps.FALLBACK_NAME
    
    return data

@app.route('/reed_json')
def reed_json():
    return {
        'states': reed_manager.get_states(),
        'forced': reed_manager.get_forced_states()
    }
    
@app.route('/log')
def log_diagnostics():
    return render_template('log.html')


# ====================== CLEANUP ======================
def cleanup():
    logger.info("🧹 Cleaning up resources...")
    
    for name in list(active_ramps.keys()):
        cancel_ramp(name)

    try:
        if phase_manager:
            phase_manager.stop()
        if reed_manager:
            reed_manager.stop()
        if gpio_manager:
            gpio_manager.cleanup()
        if sensor_manager:
            sensor_manager.stop()
        arduino.cleanup()
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

    for reed_name in GPIO_DEVICES:
        if GPIO_DEVICES[reed_name]['type'] != 'input':
            continue

        if reed_name == "kitchen_panel":
            trigger_func = make_kitchen_panel_trigger()
        elif reed_name == "kitchen_bench":
            trigger_func = make_kitchen_bench_trigger()
        else:
            trigger_func = make_reed_trigger(reed_name)

        reed_manager.register_trigger(reed_name, trigger_func)

    reed_manager.start_monitor(interval=0.25)
    sensor_manager.start()
    init_gps_module()

    # ====================== PHASE MANAGER ======================
    if not hasattr(app, '_phase_manager_initialized'):
        phase_manager = PhaseManager(gps, socketio)
        phase_manager.reed_manager = reed_manager
        reed_manager.phase_manager = phase_manager
        phase_manager.start()
        app._phase_manager_initialized = True
    else:
        logger.warning("⚠️ PhaseManager already initialized (debug reload protection)")

    phase_manager.clear_force()
    logger.debug("🧹 All forced states cleared on startup")
    
    if gps and getattr(gps, 'serial', None):
        gps.start_reader()
        logger.debug("🛰️ GPS reader started")
    else:
        logger.warning("⚠️ GPS not fully ready when starting PhaseManager")

    # Background sync thread
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