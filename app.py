# app.py
from flask import Flask, render_template, request, Response
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import threading
import time
import os
import logging
import sys
import math
import flask
import importlib.metadata
import json
import psutil
import platform
import socket
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

# Respect [logging] suppress_* from pccs.conf (instead of hardcoding)
if config.getboolean('logging', 'suppress_werkzeug', fallback=True):
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
if config.getboolean('logging', 'suppress_engineio', fallback=True):
    logging.getLogger("engineio").setLevel(logging.WARNING)
if config.getboolean('logging', 'suppress_socketio', fallback=True):
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


theme_config = ConfigManager('active_theme.json', {'theme': config.get('ui', 'default_theme', fallback='base')})
dark_mode_config = ConfigManager('active_dark_mode.json', {'mode': 'dark'})

# Pull [ui] settings (currently only used for default + whether base.css is always first)
UI_DEFAULT_THEME = config.get('ui', 'default_theme', fallback='base')
UI_LOAD_BASE_FIRST = config.getboolean('ui', 'load_base_first', fallback=True)

# ====================== THEME ======================
current_global_theme = theme_config.load()['theme']
friendly_name = get_friendly_theme_name(current_global_theme)

logger.info(f"🎨 Loaded theme: {friendly_name} ({current_global_theme}.css)")

# ====================== CONSTANTS & GLOBALS ======================
# These now come from /config/pccs.conf
UI_RAMP_TIME_MS = config.getint('lighting', 'ui_ramp_time_ms', 1000)
BACKGROUND_SYNC_INTERVAL = config.getint('background_sync', 'sync_interval', 45)

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
from modules.system import SystemInfoManager

app = Flask(__name__)
app.config['SECRET_KEY'] = config.get('system', 'secret_key')
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Dev-friendly settings for frontend iteration (templates + static/JS/CSS).
# Edit config/pccs.conf to set debug = true, then restart app.py *once*.
# After that you can edit templates/index.html or files under static/ (JS/CSS)
# and see updates just by refreshing the browser (no more python restarts for
# frontend-only changes).
# For JS/CSS changes you will usually need a *hard* refresh (Ctrl+Shift+R / Cmd+Shift+R)
# or DevTools → Network → "Disable cache", because browsers aggressively cache
# same-URL static assets even when the server says "no-cache".
# Set back to false for normal/production use.
debug_mode = config.getboolean('system', 'debug', fallback=False)
if debug_mode:
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    app.jinja_env.auto_reload = True
    # Explicitly disable Jinja's compiled template cache so changed .html files
    # are always re-parsed from disk on the next render_template() call.
    app.jinja_env.cache = None
    logger.info("🛠️ Debug mode ON — TEMPLATES_AUTO_RELOAD + static no-cache + jinja cache disabled. Edit frontend files then hard-refresh browser (Ctrl+Shift+R).")

# ====================== SYSTEM INFO MANAGER ======================
system_manager = SystemInfoManager(config, socketio, APP_VERSION)

# ====================== TOASTS ======================
toast_manager = ToastManager(config, socketio)
import modules.toasts
modules.toasts.toast_manager = toast_manager

logger = setup_logging(config, toast_manager=toast_manager)

# ====================== ERROR & WARNING TOAST HELPERS ======================
def send_error_toast(message: str, title: str = "Error"):
    """Log error → automatically becomes persistent toast"""
    logger.error(message)


def send_warning_toast(message: str, title: str = "Warning"):
    """Log warning → becomes toast"""
    logger.warning(message)

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

def set_rgb_bug_light(name: str, brightness: int, mode: str = 'white', ramp_ms: int | None = None):
    return arduino.set_rgb_bug_light(name, brightness, mode, ramp_ms)


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
            # Logging is now done immediately at command time in the callers
            # (handle_light_change, reed trigger, etc.) so that logs appear promptly
            # instead of being delayed until the end of the ramp duration.
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
                    set_rgb_bug_light(light_name, desired_brightness, mode, ramp)
                else:
                    pin = LIGHT_MAP.get(light_name)
                    if pin is None:
                        logger.warning(f"⚠️ No LIGHT_MAP pin for reed-controlled light '{light_name}' (reed {reed_name})")
                        continue
                    pwm = int(desired_brightness * 2.55)
                    send_command(f"RAMP {pin} {pwm} {ramp}")
                log_light_change(light_name, desired_brightness, "scene", mode)
                ramp_and_broadcast(light_name, desired_brightness, ramp,
                                   mode if light_name in RGB_LIGHTS else None, 
                                   source=None)
            return

        # ====================== NORMAL REED / PHASE / FORCE HANDLING ======================
        effective_closed = reed_manager.get_effective_state(reed_name)

        final_closed = effective_closed

        if reed_name in reed_manager.interlocks:
            if not reed_manager.is_interlock_satisfied(reed_name):
                final_closed = True
                logger.debug(f"🛡️ Interlock safety net: {reed_name} forced CLOSED")

        phase = phase_manager.get_phase()

        # Use the ramp time from config (reed_ramp_time_ms for normal reed events,
        # phase_ramp_time_ms for phase changes) for BOTH opening (to level) and
        # closing (to 0). This ensures that when a reed closes (including interlocked
        # dependents like kitchen_bench when kitchen_panel closes), all affected
        # lights fade out simultaneously over the configured ramp time.
        for light_name in light_list:
            if final_closed:  # CLOSED → turn off
                if light_name in RGB_LIGHTS:
                    set_rgb_bug_light(light_name, 0, "white", ramp)
                else:
                    pin = LIGHT_MAP.get(light_name)
                    if pin is None:
                        logger.warning(f"⚠️ No LIGHT_MAP pin for reed-controlled light '{light_name}' (reed {reed_name})")
                        continue
                    send_command(f"RAMP {pin} 0 {ramp}")

                log_light_change(light_name, 0, "reed" if not is_phase_change else "phase change")
                ramp_and_broadcast(light_name, 0, ramp,
                                   source=None)

                # Real reed close transition (not a phase re-apply) clears any prior manual override
                if not is_phase_change and reed_manager:
                    reed_manager.clear_user_overrides([light_name])

            else:
                if is_phase_change and reed_manager and reed_manager.user_overrides.get(light_name):
                    # Phase-change / startup re-apply: do not clobber a manual user-set level.
                    # (True phase changes pre-clear overrides in reapply_all_reed_lights.)
                    continue

                # Normal reed open (or phase re-apply without override): apply the configured
                # "its level" for this phase. Reed open events always (re)establish the reed's
                # defined level and clear manual overrides (the reed "chooses" the level).
                settings = reed_manager.get_light_settings(phase, light_name)
                if settings is None:
                    logger.debug(f"No {phase} setting for light '{light_name}' – leaving unchanged")
                    continue

                brightness, mode = settings

                if light_name in RGB_LIGHTS:
                    set_rgb_bug_light(light_name, brightness, mode, ramp)
                else:
                    pin = LIGHT_MAP.get(light_name)
                    if pin is None:
                        logger.warning(f"⚠️ No LIGHT_MAP pin for reed-controlled light '{light_name}' (reed {reed_name})")
                        continue
                    pwm = int(brightness * 2.55)
                    send_command(f"RAMP {pin} {pwm} {ramp}")

                log_light_change(light_name, brightness, "reed" if not is_phase_change else "phase change", mode)
                ramp_and_broadcast(light_name, brightness, ramp,
                                   mode if light_name in RGB_LIGHTS else None,
                                   source=None)

                # Real reed open transition (physical or force) clears override (the reed action chose the level)
                if not is_phase_change and reed_manager:
                    reed_manager.clear_user_overrides([light_name])

    return trigger


# ====================== WRAPPERS ======================
def send_command(cmd: str):
    return arduino.send_command(cmd)

def set_rgb_bug_light(name: str, brightness: int, mode: str = 'white', ramp_ms: int | None = None):
    return arduino.set_rgb_bug_light(name, brightness, mode, ramp_ms)

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

# Note: gpio device init and event handler registration is now done later in the
# __main__ block (after light-control triggers are registered) for better ordering
# and reliability of runtime reed events.

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


# ====================== NETWORK TILE SUPPORT (for dashboard glanceable tile) ======================
def build_network_status():
    """Assemble the payload consumed by the Network tile (Iteration 2 design)."""
    payload = {
        "internet": {
            "connected": False,
            "friendly_name": "No Internet",
            "rx_kbps": 0.0,
            "tx_kbps": 0.0,
            "ping_ms": None,
            "ping_status": "unknown",   # good | slow | fail | unknown
            "signal_quality": None,     # e.g. "87%" or "—"
        },
        "right": {
            "core_temp_c": None,
            "uptime": None,
            "dhcp_clients": 0,
        },
        "timestamp": None,
    }

    # Internet data (throughput + basic connectivity) from SystemInfoManager
    try:
        net = system_manager.get_network_status()
        inet = net.get("internet", {})
        payload["internet"].update({
            "connected": inet.get("connected", False),
            "friendly_name": inet.get("friendly_name", "No Internet"),
            "rx_kbps": inet.get("rx_kbps", 0.0),
            "tx_kbps": inet.get("tx_kbps", 0.0),
            "signal_quality": inet.get("signal_quality"),
        })
        payload["timestamp"] = net.get("last_updated")
    except Exception as e:
        logger.debug(f"build_network_status net error: {e}")

    # Pi Core Temp
    try:
        payload["right"]["core_temp_c"] = system_manager._get_cpu_temp()
    except Exception:
        pass

    # DHCP clients count (already cached)
    try:
        payload["right"]["dhcp_clients"] = len(system_manager.dhcp_clients_cache)
    except Exception:
        pass

    # App Uptime (labeled simply as "Uptime" in the UI)
    try:
        start_time = getattr(app, '_start_time', None)
        if start_time:
            payload["right"]["uptime"] = _format_uptime(datetime.now() - start_time)
    except Exception:
        pass

    # Ping (lightweight + cached inside system_manager or here)
    try:
        ping_ms, ping_status = _get_cached_ping()
        payload["internet"]["ping_ms"] = ping_ms
        payload["internet"]["ping_status"] = ping_status
    except Exception:
        pass

    return payload


# Simple module-level ping cache (30-45s) to avoid hammering the network on every tile update
_ping_cache = {"ts": 0, "ms": None, "status": "unknown"}
_PING_CACHE_TTL = 35


def _get_cached_ping():
    """Return (ping_ms, status) using a short cache.
    Tries real ping first, falls back to curl for latency measurement.
    This makes it much more reliable across different environments.
    """
    import time as _t
    import subprocess

    now = _t.time()
    is_first_call = _ping_cache["ts"] == 0

    if not is_first_call and now - _ping_cache["ts"] < _PING_CACHE_TTL and _ping_cache["ms"] is not None:
        return _ping_cache["ms"], _ping_cache["status"]

    ms = None
    status = "fail"

    # Method 1: Try real ping (best when it works)
    try:
        start = _t.time()
        subprocess.check_output(
            ["ping", "-c", "1", "-W", "1", "1.1.1.1"],
            stderr=subprocess.DEVNULL,
            timeout=2.2
        )
        elapsed = (_t.time() - start) * 1000
        ms = int(round(elapsed))
    except Exception:
        ms = None

    # Method 2: Fallback using curl (very reliable on Pis and embedded systems)
    if ms is None:
        try:
            start = _t.time()
            # Capture stderr so we can see real errors on first failure
            result = subprocess.run(
                ["curl", "-I", "--connect-timeout", "2", "--max-time", "2", "http://1.1.1.1"],
                capture_output=True,
                text=True,
                timeout=2.5
            )
            if result.returncode == 0:
                elapsed = (_t.time() - start) * 1000
                ms = int(round(elapsed))
            else:
                # Log the actual curl error on first attempt
                if is_first_call:
                    logger.warning(f"curl fallback failed: returncode={result.returncode}, stderr={result.stderr.strip()}")
                ms = None
        except Exception as e:
            if is_first_call:
                logger.warning(f"curl fallback exception: {e}")
            ms = None

    if ms is not None:
        if ms < 50:
            status = "good"
        elif ms < 150:
            status = "slow"
        else:
            status = "fail"
    else:
        status = "fail"

    _ping_cache.update({"ts": now, "ms": ms, "status": status})

    # Helpful one-time log so we can see if ping is actually succeeding
    if is_first_call:
        display_ms = ms if ms is not None else "None"
        logger.info(f"🌐 First network ping measurement: {display_ms}ms (status={status})")

    return ms, status


def _format_uptime(delta):
    """Convert a timedelta into a short human string like '14d 3h' or '2h 17m'."""
    if not delta:
        return None

    total_seconds = int(delta.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60

    if days > 0:
        return f"{days}d {hours}h"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


def network_status_broadcaster():
    """Push fresh network+component status to all clients every ~8-9s."""
    import time as _time
    while not shutdown_event.is_set():
        try:
            data = build_network_status()
            socketio.emit("network_update", data)
        except Exception as e:
            if not shutdown_event.is_set():
                logger.debug(f"network_status_broadcaster error: {e}")
        _time.sleep(8.5)


# ====================== ROUTES ======================
@app.route('/')
def index():
    return render_template('index.html', load_base_first=UI_LOAD_BASE_FIRST)

@app.route('/diag')
def diagnostics():
    return render_template('diag.html', load_base_first=UI_LOAD_BASE_FIRST)

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

@app.route('/reeds/resync', methods=['POST'])
def reeds_resync():
    """Trigger a hardware re-sample of all reed pins. Returns the names that changed state.
    Use this (or the socket 'resync_reeds') when the UI state for a reed does not match
    the physical switch — the logs will include `pinctrl get` output for each pin so you
    can compare the kernel electrical level against what the app sees."""
    if not reed_manager:
        return {'error': 'no reed_manager'}, 500
    changed = reed_manager.resync_reed_states()
    return {
        'changed': changed,
        'states': reed_manager.get_states()
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
    
@app.route('/api/system_info')
def system_info():
    return system_manager.get_system_info()

@app.route('/api/network_status')
def network_status():
    """Lightweight endpoint for the dashboard network tile (and diag fallback)."""
    try:
        return build_network_status()
    except Exception as e:
        logger.warning(f"network_status error: {e}")
        return {"internet": {"connected": False, "friendly_name": "Error"}, "error": str(e)}
    
# ====================== SOCKETIO ======================
@socketio.on('light_change')
def handle_light_change(data):
    name = data['name']
    target = max(0, min(100, int(data.get('brightness', 0))))
    mode = data.get('mode', 'white') if name in RGB_LIGHTS else None

    # Clamp *before* any hardware command so rooftop interlock (and future safeties)
    # prevent turning on lights that should be locked out. The prior send-then-clamp
    # order could leave hardware on even when model said closed.
    target = apply_safety_constraints(name, target, "user interface")

    # For manual UI sets (sliders, toggle pills, etc.), always use the configured
    # ui_ramp_time_ms from pccs.conf. Previously there was a special case forcing
    # 150ms for target==0 to make "toggle off" feel snappier, but that bypassed the
    # user-configured ramp time.
    ramp_ms = UI_RAMP_TIME_MS

    if name in RGB_LIGHTS:
        set_rgb_bug_light(name, target, mode or "white", ramp_ms)
    elif name in LIGHT_MAP:
        pwm = int(target * 2.55)
        send_command(f"RAMP {LIGHT_MAP[name]} {pwm} {ramp_ms}")

    # Log immediately (command has been issued to hardware). This makes light level
    # change logs appear promptly instead of being deferred until the end of the
    # ramp duration inside ramp_and_broadcast.
    log_light_change(name, target, "user interface", mode)

    ramp_and_broadcast(name, target, ramp_ms, mode, source=None)

    if reed_manager:
        reed_manager.set_user_override(name, target, mode)

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


@socketio.on('get_reeds')
def handle_get_reeds():
    if reed_manager:
        emit('reed_update', {
            'states': reed_manager.get_states(),
            'forced': reed_manager.get_forced_states()
        })

@socketio.on('resync_reeds')
def handle_resync_reeds():
    if reed_manager:
        changed = reed_manager.resync_reed_states()
        emit('reed_update', {
            'states': reed_manager.get_states(),
            'forced': reed_manager.get_forced_states()
        })
        logger.info(f"🔄 Client requested reed hardware resync; changed: {changed}")


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
    
    # ====================== CORE LIGHTS & CONFIG ======================
    emit('lights_config', arduino.get_frontend_config())
    
    # ====================== SCREENS ======================
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
    
    # ====================== INITIAL STATE READ ======================
    if not first_state_read_done:
        logger.debug("🔄 First connection — reading full state from hardware")
        read_all_states()
        first_state_read_done = True
    else:
        logger.debug("📤 Sending cached state to new client")
    
    emit('state_update', state.copy())
    
    # ====================== PHASE & DARK MODE ======================
    if phase_manager:
        phase_data = {
            'phase': phase_manager.get_phase(),
            'forced': phase_manager.is_forced(),
        }
        try:
            phase_data.update(phase_manager.get_phase_times())
        except Exception as e:
            logger.warning(f"Failed to get phase times: {e}")
        
        emit('phase_update', phase_data)
        
        emit('global_dark_mode_update', {
            'mode': phase_manager.get_current_dark_mode(),
            'manual': phase_manager.manual_dark_mode is not None
        })
    else:
        emit('phase_update', {'phase': 'Day', 'forced': False})
        emit('global_dark_mode_update', {'mode': 'dark', 'manual': False})
    
    # ====================== REED STATES ======================
    emit('reed_update', {
        'states': reed_manager.get_states(),
        'forced': reed_manager.get_forced_states()
    })
    
    # ====================== SONOS INTEGRATION ======================
    if sonos and sonos.enabled:
        try:
            initial_sonos = sonos.get_current_state()
            emit('sonos_update', initial_sonos)
            
            # More reliable speaker list using the manager's internal state
            emit('sonos_speakers', {
                'speakers': list(sonos.speakers.keys()),
                'current': sonos.current_speaker,
                'enabled': True
            })
            
            logger.debug(f"🎵 Sent initial Sonos state → {sonos.current_speaker} "
                        f"({len(sonos.speakers)} player(s) discovered)")
            
        except Exception as e:
            logger.warning(f"Could not send initial Sonos state: {e}")
            # Fallback
            emit('sonos_speakers', {
                'speakers': list(sonos.speakers.keys()) if sonos.speakers else [],
                'current': sonos.current_speaker,
                'enabled': True
            })
    else:
        # Send disabled state so frontend knows not to show Sonos
        emit('sonos_update', {'enabled': False})
        emit('sonos_speakers', {'speakers': [], 'current': None, 'enabled': False})
    
    # ====================== INITIAL NETWORK TILE STATUS ======================
    try:
        emit('network_update', build_network_status())
    except Exception as e:
        logger.debug(f"Initial network_update emit failed: {e}")
    
    # ====================== GPS ======================
    if gps:
        emit('gps_update', gps.get_state())

    # ====================== VICTRON ======================
    if victron:
        emit('victron_update', victron.get_state())
    else:
        emit('victron_update', {'enabled': False})

        # While hardware is not installed, push a nice demo payload shortly
        # after connect so the tile is not completely blank on first load.
        def _send_demo_victron():
            try:
                demo = {
                    "enabled": True,
                    "stale": False,
                    "soc": 86,
                    "voltage": 13.38,
                    "current_a": 3.8,
                    "consumed_ah": -7.2,
                    "time_to_go_mins": 295,
                    "battery_temp": 24.5,
                    "solar_current_a": 11.4,
                    "yield_today_kwh": 1.87,
                    "charge_state": "Absorption"
                }
                socketio.emit('victron_update', demo)
            except Exception:
                pass
        threading.Timer(1.3, _send_demo_victron).start()


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
        
        
@socketio.on('sonos_switch_speaker')
def handle_sonos_switch(data):
    if not sonos or not sonos.enabled:
        emit('toast', {'type': 'error', 'message': 'Sonos not enabled'})
        return

    name = data.get('name')
    if not name:
        return

    if sonos.switch_speaker(name):
        new_state = sonos.get_current_state()

        # This is the correct way to broadcast
        emit('sonos_update', new_state, broadcast=True)
        emit('sonos_speakers', {
            'speakers': list(sonos.speakers.keys()),
            'current': sonos.current_speaker,
            'enabled': True
        }, broadcast=True)

        logger.info(f"🎵 Switched active speaker to: {name}")
    else:
        emit('toast', {'type': 'error', 'message': f'Speaker "{name}" not found'})
        
        
# ====================== SONOS STATE REQUEST ======================
@socketio.on('sonos_request_state')
def handle_sonos_request_state():
    """Frontend requests current Sonos state (called on page load)"""
    if 'sonos' not in globals() or not sonos or not sonos.enabled:
        emit('sonos_update', {'speaker': None, 'track': 'Sonos disabled', 'enabled': False})
        return

    try:
        state = sonos.get_current_state()
        emit('sonos_update', state)
        logger.debug(f"🎵 Sent Sonos state on request → {sonos.current_speaker}")
    except Exception as e:
        logger.error(f"Failed to send Sonos state: {e}")
        emit('sonos_update', {'speaker': sonos.current_speaker, 'track': 'Error fetching state'})


# ====================== VICTRON STATE REQUEST ======================
@socketio.on('get_victron_state')
def handle_get_victron_state():
    """Frontend can request a fresh push of victron state (useful on reconnects)."""
    if 'victron' not in globals() or not victron or not getattr(victron, 'enabled', False):
        emit('victron_update', {'enabled': False})
        return
    try:
        emit('victron_update', victron.get_state())
    except Exception as e:
        logger.debug(f"Failed to send victron state on request: {e}")
        emit('victron_update', {'enabled': True, 'stale': True})


@app.route('/api/sonos/status')
def sonos_status():
    """Return current Sonos status for frontend diagnostics"""
    if not sonos:
        return {'enabled': False, 'error': 'Sonos module not loaded'}
    
    return sonos.get_current_state()


# ====================== NETWORK TILE STATUS ======================
@socketio.on('get_network_status')
def handle_get_network_status():
    """Frontend can request an immediate network status push (like Sonos)."""
    try:
        emit('network_update', build_network_status())
    except Exception as e:
        logger.debug(f"get_network_status handler error: {e}")
   
@app.route('/api/version')
def get_version_route():
    return {
        "version": APP_VERSION,
        "base_version": APP_VERSION.split('.')[:3],  # e.g. ["3","0","1"]
        "full": APP_VERSION,
        "built": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    
# ====================== SONOS ALBUM ART PROXY ======================
@app.route('/sonos-art')
def proxy_sonos_album_art():
    """Proxy Sonos album art so it works through Cloudflare Tunnel"""
    art_url = request.args.get('url')
    if not art_url:
        return "Missing 'url' parameter", 400

    try:
        from urllib.parse import urlparse
        parsed = urlparse(art_url)

        # Basic security check
        if parsed.port != 1400 or not parsed.hostname:
            logger.warning(f"Blocked suspicious Sonos art URL: {art_url}")
            return "Invalid Sonos URL", 403

        import requests

        headers = {'User-Agent': 'Pissmole-Camper-Control-System'}

        resp = requests.get(
            art_url,
            headers=headers,
            timeout=10,
            stream=True
        )

        if resp.status_code != 200:
            logger.debug(f"Sonos art returned {resp.status_code}")
            return "Failed to fetch art", resp.status_code

        def generate():
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk

        return Response(
            generate(),
            content_type=resp.headers.get('content-type', 'image/jpeg'),
            headers={
                'Cache-Control': 'public, max-age=7200',
                'Access-Control-Allow-Origin': '*'
            }
        )

    except requests.exceptions.RequestException as e:
        logger.warning(f"Sonos art proxy request failed: {e}")
        return "Proxy request error", 502
    except Exception as e:
        logger.error(f"Unexpected error proxying Sonos art: {e}", exc_info=True)
        return "Proxy server error", 500
        
        
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
        
        observed_on = conn.get('on')
        result[name] = {
            'on': observed_on if observed_on is not None else reed_manager.screen_states.get(name, False),
            'brightness': conn.get('brightness'),
            'online': conn.get('online', False),
            'latency': conn.get('latency'),
            'ssh_passwordless': conn.get('ssh_passwordless'),
            'ssh_error': conn.get('ssh_error'),
            'last_checked': conn.get('last_checked'),
            'error': conn.get('error'),
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
        if 'victron' in globals() and victron:
            victron.stop()
    except Exception as e:
        logger.error(f"⚠️ Error during cleanup: {e}")
    logger.info("🌙💤 Pissmole has left the campsite, goodbye!")

if __name__ == "__main__":
    logger.info("✅ System starting...")
    logger.info(f"🛠️ Debug mode: {debug_mode} (set debug=true in config/pccs.conf, restart once; then frontend edits should appear on browser refresh/hard-refresh without further restarts)")
    
    arduino.init_serial()

    # Create phase objects (cheap), attach. Light-control triggers are now registered
    # after GPIO init (see below) so that the apply_initial_ambient_state etc. see the real reeds.
    # The full closed+open sync + poll backup ensures reed changes drive the lights promptly.
    # Arduino serial is ready early so sends from triggers work.
    gps = GPSModule(config, socketio)

    phase_manager = PhaseManager(config, gps, socketio, dark_mode_config)
    phase_manager.reed_manager = reed_manager
    reed_manager.phase_manager = phase_manager

    sensor_manager = SensorManager(config, arduino.send_command, socketio)

    # ====================== GPIO DEVICES + HARDWARE REED EVENTS + LIGHT TRIGGERS ======================
    # Init GPIO hardware first -- this populates reed_states with the real 5 reeds (and creates Buttons).
    gpio_manager.init_devices()

    # Now register light-control triggers -- now the list will have the 5 reeds.
    for reed_name in list(gpio_manager.reed_states.keys()):
        reed_manager.register_trigger(reed_name, make_reed_trigger(reed_name))
    logger.debug(f"💡 Registered light-control triggers for {len(gpio_manager.reed_states)} logical reeds "
                 "(hardware or virtual for force/UI)")

    # Attach gpiozero edge handlers (when_pressed etc). The light cbs are now registered so _apply will have targets.
    reed_manager.register_event_handlers()
    logger.info(f"🚪 Registered event handlers for {len(gpio_manager.reeds)} reeds")
    for name in sorted(gpio_manager.reeds.keys()):
        logger.debug(f"   → {name} handler attached")

    # Poll backup for reliability.
    reed_manager._start_reed_monitor()

    # Heavy init after cbs registered (events now drive lights...).
    gps.init_gps()
    gps.init_geolocator()

    sensor_manager.start()
    
    app._start_time = datetime.now()
    
    system_manager.get_dhcp_clients()

    phase_manager.start()
    
    reed_manager.apply_initial_ambient_state()
    reed_manager.apply_initial_screen_states()

    if getattr(gps, 'serial', None):
        gps.start_reader()

    threading.Thread(target=background_state_sync, daemon=True).start()
    threading.Thread(target=network_status_broadcaster, daemon=True).start()

    logger.info("🎉🎉🎉 The Pissmole Camper Control System lives! 🎉🎉🎉")

    # ====================== SONOS (optional, can take a few seconds for discovery) ======================
    global sonos
    sonos = None
    try:
        from modules.sonos import SonosManager
        sonos = SonosManager(socketio, config)
        sonos.start()
    except Exception as e:
        logger.error(f"❌ Failed to initialize SonosManager: {e}", exc_info=True)
        sonos = None

    # ====================== VICTRON (SmartShunt + MPPT via BLE) (optional) ======================
    global victron
    victron = None
    try:
        from modules.victron import VictronManager
        victron = VictronManager(socketio, config, phase_manager=phase_manager)
        if victron and victron.enabled:
            victron.start()
            if phase_manager:
                phase_manager.register_night_listener(victron.reset_daily_generation)
    except Exception as e:
        logger.error(f"❌ Failed to initialize VictronManager: {e}", exc_info=True)
        victron = None

    # ====================== START SOCKETIO ======================
    try:
        socketio.run(
            app,
            host=config.get('system', 'host', fallback='0.0.0.0'),
            port=config.getint('system', 'port', fallback=5000),
            debug=debug_mode,
            use_reloader=debug_mode,   # enables file watcher + restart on code changes when debug=true
            allow_unsafe_werkzeug=True
        )
    except (KeyboardInterrupt, SystemExit):
        logger.info("\n🛑 Shutdown requested...")
    finally:
        cleanup()