# app.py — PCCS bridge (desired-state architecture)
from flask import Flask, render_template, request, Response
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import threading
import time
import os
import logging
import sys
import json
import subprocess
from datetime import datetime

from modules.version import APP_VERSION
from modules.config import config
from modules.logger import setup_logging
from modules.gps import GPSModule
from modules.phases import PhaseManager
from modules.sensors import SensorManager
from modules.toasts import ToastManager, toast_manager
from modules.system import SystemInfoManager
import modules.toasts

from bridge.runtime import PCCSRuntime

# ====================== LOGGING ======================
logger = setup_logging(config)

logger.info("=" * 71)
logger.info(f"🚐💦  Welcome to the Pissmole Camper Control System v{APP_VERSION}  💦🚐")
logger.info("=" * 71)

if config.getboolean('logging', 'suppress_werkzeug', fallback=True):
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
if config.getboolean('logging', 'suppress_engineio', fallback=True):
    logging.getLogger("engineio").setLevel(logging.WARNING)
if config.getboolean('logging', 'suppress_socketio', fallback=True):
    logging.getLogger("socketio").setLevel(logging.WARNING)


def log_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.critical("💥 Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))


sys.excepthook = log_exception

if hasattr(sys, '_pccs_already_started'):
    logger.warning("⚠️ Module reloaded - skipping duplicate initialization")
else:
    sys._pccs_already_started = True


# ====================== THEME ======================
def _extract_css_friendly_name(filepath: str, fallback: str) -> str:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            first = f.readline().strip()
            if first.startswith('/*') and first.endswith('*/'):
                comment = first[2:-2].strip()
                if comment:
                    return comment
    except Exception:
        pass
    return fallback


def get_friendly_theme_name(theme_file: str) -> str:
    if not theme_file:
        return "Unknown"
    base_path = os.path.dirname(__file__)
    for sub in ('static/css', 'static/css/themes', 'static'):
        path = os.path.join(base_path, sub, f"{theme_file}.css")
        if os.path.exists(path):
            return _extract_css_friendly_name(
                path, theme_file.replace('-', ' ').replace('_', ' ').title()
            )
    return theme_file.replace('-', ' ').replace('_', ' ').title()


class ConfigManager:
    def __init__(self, filename: str, default: dict):
        self.path = os.path.join(os.path.dirname(__file__), 'config', filename)
        self.default = default
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, 'r') as f:
                    return {**self.default, **json.load(f)}
        except Exception as e:
            logger.error(f"Failed to load config {self.path}: {e}")
        return self.default.copy()

    def save(self, data: dict):
        try:
            with open(self.path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save config: {e}")


theme_config = ConfigManager('active_theme.json', {'theme': config.get('ui', 'default_theme', fallback='base')})
dark_mode_config = ConfigManager('active_dark_mode.json', {'mode': 'dark'})
UI_LOAD_BASE_FIRST = config.getboolean('ui', 'load_base_first', fallback=True)
current_global_theme = theme_config.load()['theme']

# ====================== FLASK ======================
app = Flask(__name__)
app.config['SECRET_KEY'] = config.get('system', 'secret_key')
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

debug_mode = config.getboolean('system', 'debug', fallback=False)
if debug_mode:
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    app.jinja_env.auto_reload = True
    app.jinja_env.cache = None

system_manager = SystemInfoManager(config, socketio, APP_VERSION)
toast_manager = ToastManager(config, socketio)
modules.toasts.toast_manager = toast_manager
logger = setup_logging(config, toast_manager=toast_manager)

shutdown_event = threading.Event()
first_state_read_done = False

# ====================== RUNTIME ======================
runtime = PCCSRuntime(config, socketio=socketio, dark_mode_config=dark_mode_config)

gps = None
phase_manager = None
sensor_manager = None
sonos = None
victron = None

_ping_cache = {"ts": 0, "ms": None, "status": "fail"}
_PING_CACHE_TTL = 35


# ====================== NETWORK HELPERS ======================
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
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def build_network_status():
    """Assemble the payload consumed by the Network tile."""
    payload = {
        "internet": {
            "connected": False,
            "friendly_name": "No Internet",
            "rx_kbps": 0.0,
            "tx_kbps": 0.0,
            "ping_ms": None,
            "ping_status": "unknown",
            "signal_quality": None,
            "link_speed_mbps": None,
        },
        "right": {
            "core_temp_c": None,
            "uptime": None,
            "dhcp_clients": 0,
        },
        "timestamp": None,
    }

    try:
        net = system_manager.get_network_status()
        inet = net.get("internet", {})
        payload["internet"].update({
            "connected": inet.get("connected", False),
            "friendly_name": inet.get("friendly_name", "No Internet"),
            "rx_kbps": inet.get("rx_kbps", 0.0),
            "tx_kbps": inet.get("tx_kbps", 0.0),
            "signal_quality": inet.get("signal_quality"),
            "link_speed_mbps": inet.get("link_speed_mbps"),
        })
        payload["timestamp"] = net.get("last_updated")
    except Exception as e:
        logger.debug(f"build_network_status net error: {e}")

    try:
        payload["right"]["core_temp_c"] = system_manager._get_cpu_temp()
    except Exception:
        pass

    try:
        payload["right"]["dhcp_clients"] = len(system_manager.dhcp_clients_cache)
    except Exception:
        pass

    try:
        start_time = getattr(app, '_start_time', None)
        if start_time:
            payload["right"]["uptime"] = _format_uptime(datetime.now() - start_time)
    except Exception:
        pass

    try:
        ping_ms, ping_status = _get_cached_ping()
        payload["internet"]["ping_ms"] = ping_ms
        payload["internet"]["ping_status"] = ping_status
    except Exception:
        pass

    return payload


def _get_cached_ping():
    now = time.time()
    if _ping_cache["ts"] and now - _ping_cache["ts"] < _PING_CACHE_TTL and _ping_cache["ms"] is not None:
        return _ping_cache["ms"], _ping_cache["status"]
    ms, status = None, "fail"
    try:
        start = time.time()
        subprocess.check_output(["ping", "-c", "1", "-W", "1", "1.1.1.1"], stderr=subprocess.DEVNULL, timeout=2.2)
        ms = int(round((time.time() - start) * 1000))
    except Exception:
        pass
    if ms is None:
        try:
            start = time.time()
            r = subprocess.run(
                ["curl", "-I", "--connect-timeout", "2", "--max-time", "2", "http://1.1.1.1"],
                capture_output=True, text=True, timeout=2.5,
            )
            if r.returncode == 0:
                ms = int(round((time.time() - start) * 1000))
        except Exception:
            pass
    if ms is not None:
        status = "good" if ms < 50 else ("slow" if ms < 150 else "fail")
    _ping_cache.update({"ts": now, "ms": ms, "status": status})
    return ms, status


def network_status_broadcaster():
    while not shutdown_event.is_set():
        try:
            socketio.emit("network_update", build_network_status())
        except Exception:
            pass
        time.sleep(8.5)


# ====================== ROUTES ======================
@app.route('/')
def index():
    return render_template('index.html', load_base_first=UI_LOAD_BASE_FIRST)


@app.route('/diag')
def diagnostics():
    return render_template('diag.html', load_base_first=UI_LOAD_BASE_FIRST)


@app.route('/gps_json')
def gps_json():
    """Diagnostics REST — includes phase force metadata."""
    data = gps.get_state() if gps else {}
    if phase_manager:
        data['phase'] = phase_manager.get_phase()
        data['phase_forced'] = phase_manager.is_forced()
        try:
            data.update(phase_manager.get_phase_times() or {})
        except Exception:
            pass
    return data


@app.route('/reed_json')
def reed_json():
    """Diagnostics REST — raw hardware reeds + force overrides."""
    return runtime.get_reed_diag_json()


@app.route('/api/explain')
def explain_json():
    """Policy decision snapshot: desired vs observed, sources, drift."""
    return runtime.get_explain_json()


@app.route('/reeds/resync', methods=['POST'])
def reeds_resync():
    changed = runtime.reed_input.resync() if runtime.reed_input else []
    diag = runtime.get_reed_diag_json()
    return {'changed': changed, 'states': diag['states'], 'forced': diag['forced']}


@app.route('/api/themes')
def get_themes():
    themes, seen = [], set()
    for directory in (
        os.path.join(app.static_folder, 'css/themes'),
        os.path.join(app.static_folder, 'css'),
    ):
        if not os.path.exists(directory):
            continue
        for fn in os.listdir(directory):
            if not fn.endswith('.css'):
                continue
            base = fn[:-4]
            if base in seen:
                continue
            seen.add(base)
            path = os.path.join(directory, fn)
            fallback = base.replace('-', ' ').replace('_', ' ').title()
            themes.append({'file': base, 'name': _extract_css_friendly_name(path, fallback)})
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
    try:
        return build_network_status()
    except Exception as e:
        return {"internet": {"connected": False}, "error": str(e)}


@app.route('/api/wifi/scan')
def wifi_scan():
    try:
        return {
            "networks": system_manager.wifi_scan() if system_manager else [],
            "current": system_manager.get_current_wifi() if system_manager else {"connected": False},
        }
    except Exception as e:
        return {"networks": [], "current": {"connected": False}, "error": str(e)}


@app.route('/api/wifi/connect', methods=['POST'])
def wifi_connect():
    data = request.get_json(silent=True) or {}
    ssid = (data.get('ssid') or '').strip()
    password = data.get('password')
    if not ssid:
        return {"success": False, "message": "SSID is required"}, 400
    result = system_manager.wifi_connect(ssid, password or None) if system_manager else \
        {"success": False, "message": "System manager unavailable"}
    return result


@app.route('/api/scenes')
def get_scenes():
    scenes = dict(
        sorted(runtime.compiled.scenes.items(), key=lambda item: item[1].get("order", 999))
    )
    return {"scenes": [
        {"key": k, "name": d["name"], "icon": d["icon"], "description": d["description"], "all_off": d["all_off"]}
        for k, d in scenes.items()
    ]}


@app.route('/api/version')
def get_version_route():
    return {"version": APP_VERSION, "full": APP_VERSION, "built": datetime.now().strftime("%Y-%m-%d %H:%M")}


@app.route('/screen_json')
def screen_json():
    if not runtime.screen_actuator:
        return {'screens': {}}
    screens = {}
    for name, conf in runtime.compiled.screens.items():
        screens[name] = {
            'on': runtime.screen_actuator._observed.get(name, False),
            'online': True,
            'config': {'friendly': conf.get('friendly', name), 'icon': conf.get('icon'), 'host': conf.get('host')},
        }
    return {'screens': screens}


@app.route('/screen_status_json')
def screen_status_json():
    if not runtime.screen_actuator:
        return {'screens': {}}
    result = {}
    for name, conf in runtime.compiled.screens.items():
        conn = runtime.screen_actuator.test_connectivity(name)
        result[name] = {
            'on': conn.get('on') if conn.get('on') is not None else runtime.screen_actuator._observed.get(name, False),
            'online': conn.get('online', False),
            'brightness': conn.get('brightness'),
            'ssh_passwordless': conn.get('ssh_passwordless'),
            'ssh_error': conn.get('ssh_error'),
            'config': {'friendly': conf.get('friendly', name), 'icon': conf.get('icon'), 'host': conf.get('host')},
        }
    return {'screens': result}


@app.route('/api/sonos/status')
def sonos_status():
    return sonos.get_current_state() if sonos else {'enabled': False}


@app.route('/sonos-art')
def proxy_sonos_album_art():
    art_url = request.args.get('url')
    if not art_url:
        return "Missing url", 400
    try:
        from urllib.parse import urlparse
        import requests
        parsed = urlparse(art_url)
        if parsed.port != 1400:
            return "Invalid", 403
        resp = requests.get(art_url, timeout=10, stream=True)
        if resp.status_code != 200:
            return "Failed", resp.status_code
        return Response(
            resp.iter_content(8192),
            content_type=resp.headers.get('content-type', 'image/jpeg'),
            headers={'Cache-Control': 'public, max-age=7200'},
        )
    except Exception as e:
        logger.warning(f"Sonos art proxy: {e}")
        return "Error", 502


# ====================== SOCKETIO ======================
@socketio.on('light_change')
def handle_light_change(data):
    name = data['name']
    target = max(0, min(100, int(data.get('brightness', 0))))
    mode = data.get('mode', 'white') if name in runtime.compiled.rgb_lights else None
    runtime.set_light_intent(name, target, mode)


@socketio.on('relay_change')
def handle_relay_change(data):
    runtime.set_relay_intent(data.get('name'), bool(data.get('on', False)))


@socketio.on('set_scene')
def handle_set_scene(data):
    scene = data.get('scene')
    if scene:
        runtime.set_scene(scene)


@socketio.on('force_reed')
def handle_force_reed(data):
    name = data.get('name')
    if name is None:
        return
    runtime.force_reed(name, data.get('closed'))


@socketio.on('get_reeds')
def handle_get_reeds():
    emit('reed_update', {'states': runtime.effective_reed_states()})


@socketio.on('get_reeds_diag')
def handle_get_reeds_diag():
    emit('reed_diag_update', runtime.get_reed_diag_json())


@socketio.on('resync_reeds')
def handle_resync_reeds():
    if runtime.reed_input:
        runtime.reed_input.resync()
    emit('reed_update', {'states': runtime.effective_reed_states()})
    emit('reed_diag_update', runtime.get_reed_diag_json())


@socketio.on('force_phase')
def handle_force_phase(data):
    runtime.force_phase(data.get('phase'))


@socketio.on('set_gps_simulation')
def handle_gps_simulation(data):
    if gps and hasattr(gps, 'set_no_fix_simulation'):
        gps.set_no_fix_simulation(bool(data.get('no_fix', False)))


@socketio.on('set_global_theme')
def handle_set_global_theme(data):
    global current_global_theme
    theme = data.get('theme')
    if not theme:
        return
    current_global_theme = theme
    theme_config.save({'theme': theme})
    emit('global_theme_update', {'theme': theme}, broadcast=True)


@socketio.on('set_global_dark_mode')
def handle_set_global_dark_mode(data):
    mode = data.get('mode')
    if mode not in ('dark', 'light'):
        return
    if phase_manager:
        phase_manager.set_manual_dark_mode(mode)
    emit('global_dark_mode_update', {'mode': mode, 'manual': True}, broadcast=True)


@socketio.on('toast_test')
def handle_toast_test(data):
    if toast_manager:
        toast_manager.send_toast(
            title=data.get('title'), message=data.get('message', 'Test'),
            toast_type=data.get('type', 'info'), duration=data.get('duration', 4500),
            persistent=data.get('persistent', False),
        )


@socketio.on('screen_manual_toggle')
def handle_screen_manual_toggle(data):
    if runtime.screen_actuator:
        runtime.screen_actuator.manual_toggle(data.get('name'), data.get('on'))


@socketio.on('sonos_command')
def handle_sonos_command(data):
    if sonos:
        result = sonos.execute_command(data)
        if 'error' in result:
            emit('toast', {'type': 'error', 'message': f"Sonos: {result['error']}"})


@socketio.on('sonos_switch_speaker')
def handle_sonos_switch(data):
    if sonos and sonos.switch_speaker(data.get('name')):
        emit('sonos_update', sonos.get_current_state(), broadcast=True)


@socketio.on('sonos_request_state')
def handle_sonos_request_state():
    if sonos and sonos.enabled:
        emit('sonos_update', sonos.get_current_state())


@socketio.on('get_victron_state')
def handle_get_victron_state():
    if victron:
        emit('victron_update', victron.get_state())
    else:
        emit('victron_update', {'stale': True})


@socketio.on('get_network_status')
def handle_get_network_status():
    emit('network_update', build_network_status())


@socketio.on('connect')
def handle_connect(sid=None):
    global first_state_read_done
    emit('lights_config', runtime.get_frontend_config())

    if runtime.screen_actuator:
        emit('screens_init', {'screens': screen_json()['screens']})

    if not first_state_read_done:
        runtime.reconciler.read_hardware()
        first_state_read_done = True
    emit('state_update', runtime.get_ui_state())

    if phase_manager:
        phase_data = {'phase': phase_manager.get_phase()}
        try:
            phase_data.update(phase_manager.get_phase_times())
        except Exception:
            pass
        emit('phase_update', phase_data)
        emit('phase_diag_update', {'forced': phase_manager.is_forced()})
        emit('global_dark_mode_update', {
            'mode': phase_manager.get_current_dark_mode(),
            'manual': phase_manager.manual_dark_mode is not None,
        })

    emit('reed_update', {'states': runtime.effective_reed_states()})
    emit('reed_diag_update', runtime.get_reed_diag_json())

    if sonos and sonos.enabled:
        try:
            emit('sonos_update', sonos.get_current_state())
            emit('sonos_speakers', {'speakers': list(sonos.speakers.keys()), 'current': sonos.current_speaker, 'enabled': True})
        except Exception:
            pass
    else:
        emit('sonos_update', {'enabled': False})

    try:
        emit('network_update', build_network_status())
    except Exception:
        pass

    if gps:
        emit('gps_update', gps.get_state())
    if victron:
        emit('victron_update', victron.get_state())


def cleanup():
    logger.info("🧹 Cleaning up...")
    shutdown_event.set()
    if sonos:
        sonos.stop()
    runtime.stop()
    logger.info("🌙💤 Pissmole has left the campsite, goodbye!")


if __name__ == "__main__":
    logger.info("✅ System starting (desired-state engine)...")

    app._start_time = datetime.now()
    runtime.start_hardware()

    gps = GPSModule(config, socketio)
    phase_manager = PhaseManager(config, gps, socketio, dark_mode_config)
    phase_manager.on_phase_change = lambda p, f, inv: runtime.on_phase_change(p, f, inv)
    runtime.phase_manager = phase_manager
    runtime.gps = gps

    sensor_manager = SensorManager(config, runtime.arduino.send_command, socketio)
    runtime.sensor_manager = sensor_manager

    gps.init_gps()
    gps.init_geolocator()

    # Phase before first reconcile — avoids guessing Evening on open reeds at boot
    runtime.bootstrap_phase()
    runtime.finish_startup()

    sensor_manager.start()
    phase_manager.start()

    runtime.start_background_threads()
    threading.Thread(target=network_status_broadcaster, daemon=True).start()

    if getattr(gps, 'serial', None):
        gps.start_reader()

    system_manager.get_dhcp_clients()
    logger.info("🎉🎉🎉 The Pissmole Camper Control System lives! 🎉🎉🎉")

    try:
        from modules.sonos import SonosManager
        sonos = SonosManager(socketio, config)
        sonos.start()
    except Exception as e:
        logger.error(f"Sonos init failed: {e}")
        sonos = None

    try:
        from modules.victron import VictronManager
        victron = VictronManager(socketio, config, phase_manager=phase_manager)
        victron.start()
        phase_manager.register_night_listener(victron.reset_daily_generation)
    except Exception as e:
        logger.error(f"Victron init failed: {e}")
        victron = None

    try:
        socketio.run(
            app,
            host=config.get('system', 'host', fallback='0.0.0.0'),
            port=config.getint('system', 'port', fallback=5000),
            debug=debug_mode,
            use_reloader=debug_mode,
            allow_unsafe_werkzeug=True,
        )
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Shutdown requested...")
    finally:
        cleanup()