#!/usr/bin/env python3
"""Extract diag.html inline CSS/JS into static assets."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIAG_SRC = ROOT / "templates" / "diag.html"
DIAG_BACKUP = ROOT / "templates" / "diag.html.monolith.bak"
DIAG_JS = ROOT / "static" / "js" / "diag"


def read_source() -> str:
    if DIAG_BACKUP.exists():
        return DIAG_BACKUP.read_text()
    return DIAG_SRC.read_text()


def extract_style(html: str) -> str:
    m = re.search(r"<style>\s*(.*?)\s*</style>", html, re.DOTALL)
    if not m:
        raise RuntimeError("style block not found")
    return m.group(1).strip() + "\n"


def extract_inline_js(html: str) -> str:
    m = re.search(r"<script>\s*\n(.*?)</script>\s*</body>", html, re.DOTALL)
    if not m:
        raise RuntimeError("inline script block not found")
    return m.group(1)


def slice_js(js: str, start: str, end: str | None = None) -> str:
    s = js.find(start)
    if s < 0:
        raise RuntimeError(f"slice start not found: {start!r}")
    e = js.find(end, s) if end else len(js)
    if end and e < 0:
        raise RuntimeError(f"slice end not found: {end!r}")
    return js[s:e].strip()


def transform(body: str) -> str:
    out = body
    out = re.sub(r"^\s*const socket = io\(\);\s*\n", "", out)
    out = re.sub(r"^\s*let reedsStateCache = \{\};\s*\n", "", out, flags=re.MULTILINE)
    out = re.sub(r"^\s*let screenData = \{\};\s*\n", "", out, flags=re.MULTILINE)
    out = re.sub(r"^\s*let currentSonosSpeakers = \[\];\s*\n", "", out, flags=re.MULTILINE)
    out = re.sub(r"^\s*let currentActiveSpeaker = null;\s*\n", "", out, flags=re.MULTILINE)
    out = re.sub(r"^\s*let sonosStates = \{\};\s*\n", "", out, flags=re.MULTILINE)
    out = re.sub(r"^\s*let lastSystemInfo = \{\};\s*\n", "", out, flags=re.MULTILINE)
    out = re.sub(r"^\s*let lastWifiNetworks = \[\];\s*\n", "", out, flags=re.MULTILINE)
    out = re.sub(
        r"function formatTime\(seconds\) \{[\s\S]*?return `\$\{min\}:\$\{sec\.toString\(\)\.padStart\(2, '0'\)\}`;\s*\}\s*",
        "",
        out,
    )
    out = out.replace("reedsStateCache", "S.reedsCache")
    out = out.replace("screenData", "S.screenData")
    out = out.replace("lastSystemInfo", "S.lastSystemInfo")
    out = out.replace("currentSonosSpeakers", "S.sonosSpeakers")
    out = out.replace("currentActiveSpeaker", "S.activeSonos")
    out = out.replace("sonosStates", "S.sonosStates")
    out = out.replace("lastWifiNetworks", "S.wifiNetworks")
    out = re.sub(r"\bsocket\.", "getSocket().", out)
    out = out.replace("formatTime(", "PCCS.format.time(")
    return out


def wrap_module(doc: str, body: str, assign: str, extra: str = "") -> str:
    indented = "\n".join(("  " + line if line.strip() else "") for line in body.splitlines())
    return f"""/**
 * PCCS Diagnostics — {doc}
 */
(function () {{
  'use strict';
  const PCCS = window.PCCS;
  const D = PCCS.diag;
  const S = D.state;
  function getSocket() {{ return PCCS.getSocket(); }}
{extra}
{indented}

  {assign}
}})();
"""


def slim_html(body_html: str) -> str:
    head = """<!DOCTYPE html>
<html lang="en" data-theme="glassmorphism" data-theme-loaded="true">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PCCS Settings & Diagnostics</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/base.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/diag.css') }}">
    <link rel="stylesheet" href="/static/fontawesome/css/all.min.css">
</head>
"""
    scripts = """
    <script src="/static/socket.io.min.js"></script>
    <script src="{{ url_for('static', filename='js/pccs-namespace.js') }}"></script>
    <script src="{{ url_for('static', filename='js/format-utils.js') }}"></script>
    <script src="{{ url_for('static', filename='js/theme-manager.js') }}"></script>
    <script src="{{ url_for('static', filename='js/dark-mode.js') }}"></script>
    <script src="{{ url_for('static', filename='js/diag/namespace.js') }}"></script>
    <script src="{{ url_for('static', filename='js/diag/utils.js') }}"></script>
    <script src="{{ url_for('static', filename='js/diag/appearance.js') }}"></script>
    <script src="{{ url_for('static', filename='js/diag/gps.js') }}"></script>
    <script src="{{ url_for('static', filename='js/diag/reeds.js') }}"></script>
    <script src="{{ url_for('static', filename='js/diag/screens.js') }}"></script>
    <script src="{{ url_for('static', filename='js/diag/phases.js') }}"></script>
    <script src="{{ url_for('static', filename='js/diag/toasts.js') }}"></script>
    <script src="{{ url_for('static', filename='js/diag/sonos.js') }}"></script>
    <script src="{{ url_for('static', filename='js/diag/system.js') }}"></script>
    <script src="{{ url_for('static', filename='js/diag/app.js') }}"></script>
"""
    return head + "<body>\n" + body_html.strip() + "\n" + scripts + "\n</body>\n</html>\n"


def main():
    html = read_source()
    js = extract_inline_js(html)
    body_html = html.split("<body>")[1].split("<script src=")[0]

    DIAG_JS.mkdir(parents=True, exist_ok=True)
    (ROOT / "static" / "css" / "diag.css").write_text(extract_style(html))

    (DIAG_JS / "namespace.js").write_text("""/**
 * PCCS Diagnostics namespace root.
 */
(function () {
  'use strict';
  window.PCCS = window.PCCS || {};
  window.PCCS.diag = window.PCCS.diag || {};
  window.PCCS.diag.state = {
    reedsCache: {},
    screenData: {},
    lastSystemInfo: {},
    sonosSpeakers: [],
    activeSonos: null,
    sonosStates: {},
    wifiNetworks: [],
  };
})();
""")

    (DIAG_JS / "utils.js").write_text("""/**
 * PCCS Diagnostics — utilities
 */
(function () {
  'use strict';
  const D = window.PCCS.diag;
  function toTitleCase(str) {
    return str.replace(/\\w\\S*/g, txt =>
      txt.charAt(0).toUpperCase() + txt.substr(1).toLowerCase()
    );
  }
  D.utils = { toTitleCase };
})();
""")

    modules = {
        "appearance.js": (
            "Appearance",
            slice_js(js, "function loadThemes()", "function changeTheme"),
            "D.appearance = { loadThemes };",
            "",
        ),
        "gps.js": (
            "GPS",
            slice_js(js, "function updateGPS", "// REED SWITCHES"),
            "D.gps = { updateGPS, forceNoFix };",
            "",
        ),
        "reeds.js": (
            "Reed switches",
            slice_js(js, "// REED SWITCHES", "// TOUCHSCREENS"),
            "D.reeds = { updateReeds, renderReeds };",
            "  const toTitleCase = D.utils.toTitleCase;\n",
        ),
        "screens.js": (
            "Touchscreens",
            slice_js(js, "// TOUCHSCREENS", "// PHASES"),
            "D.screens = { renderScreens, loadScreensWithStatus };",
            "",
        ),
        "phases.js": (
            "Phase management",
            slice_js(js, "// PHASES", "// TOASTS"),
            "D.phases = { updatePhase, updatePhaseForced, forcePhase, clearPhaseForce };",
            "",
        ),
        "toasts.js": (
            "Toast test panel",
            slice_js(js, "// TOASTS", "// Socket listeners"),
            "D.toasts = { sendCustomToast, sendCustomPersistent };",
            "",
        ),
        "sonos.js": (
            "Sonos diagnostics",
            slice_js(js, "// ====================== SONOS DIAGNOSTICS", "// ====================== PCCS CORE INFORMATION"),
            "D.sonos = { renderPlayers, command, setVolume, toggleMute, switchActive };",
            "  const formatTime = PCCS.format.time;\n",
        ),
        "system.js": (
            "System info & WiFi",
            slice_js(js, "// ====================== PCCS CORE INFORMATION", None),
            "D.system = { renderCoreInfo, loadCoreInfo, scanWifi, onWifiChanged, connectWifi };",
            "",
        ),
    }

    for fname, (doc, raw, assign, extra) in modules.items():
        body = transform(raw)
        if fname == "sonos.js":
            body = body.replace("function renderSonosPlayers", "function renderPlayers")
            body = body.replace("renderSonosPlayers(", "renderPlayers(")
            body = body.replace("function sonosDiagCommand", "function command")
            body = body.replace("function setVolumeDiag", "function setVolume")
            body = body.replace("function toggleMuteDiag", "function toggleMute")
            body = body.replace("function switchActiveSonosPlayer", "function switchActive")
            body = re.sub(r"\s*// Socket listeners[\s\S]*$", "", body)
        if fname == "system.js":
            body = body.replace("function scanWifiNetworks", "function scanWifi")
            body = body.replace("function onWifiNetworkChanged", "function onWifiChanged")
            body = body.replace("function connectToSelectedWifi", "function connectWifi")
            body = re.sub(r"\s*// Auto-refresh every 8 seconds[\s\S]*$", "", body)
            body = body.replace("scanWifiNetworks()", "__SCAN_WIFI__()")
            body = body.replace("loadCoreInfo()", "__LOAD_CORE__()")
            body = body.replace("__SCAN_WIFI__()", "D.system.scanWifi()")
            body = body.replace("__LOAD_CORE__()", "D.system.loadCoreInfo()")
        (DIAG_JS / fname).write_text(wrap_module(doc, body, assign, extra))

    boot_end = '.catch(err => console.warn("Could not load screens:", err));'
    boot = transform(slice_js(js, "window.onload = () => {", boot_end))
    boot = boot.replace("window.onload = () => {", "").strip()
    boot = boot.replace("loadThemes()", "D.appearance.loadThemes()")
    boot = boot.replace("loadScreensWithStatus()", "D.screens.loadScreensWithStatus()")
    boot = boot.replace("loadCoreInfo()", "D.system.loadCoreInfo()")
    boot = boot.replace("renderReeds(", "D.reeds.renderReeds(")
    boot = boot.replace("updateReeds(", "D.reeds.updateReeds(")
    boot = boot.replace("updateGPS", "D.gps.updateGPS")
    boot = boot.replace("renderScreens()", "D.screens.renderScreens()")

    register = transform(slice_js(js, "// Socket listeners", "        window.onload"))
    register = register.replace("updateGPS", "D.gps.updateGPS")
    register = register.replace("updateReeds", "D.reeds.updateReeds")
    register = register.replace("updatePhaseForced", "__PHASE_FORCED__")
    register = register.replace("updatePhase", "D.phases.updatePhase")
    register = register.replace("__PHASE_FORCED__", "D.phases.updatePhaseForced")
    register = register.replace("renderScreens", "D.screens.renderScreens")
    register = register.replace("renderCoreInfo", "D.system.renderCoreInfo")

    sonos_reg = transform(slice_js(js, "socket.on('sonos_speakers'", "socket.on('sonos_update'"))
    sonos_reg += "\n" + transform(slice_js(js, "socket.on('sonos_update'", "\t// ====================== PCCS CORE INFORMATION"))
    sonos_reg = sonos_reg.replace("renderSonosPlayers", "D.sonos.renderPlayers")

    app = f"""/**
 * PCCS Diagnostics — boot and socket wiring
 */
(function () {{
  'use strict';
  const PCCS = window.PCCS;
  const D = PCCS.diag;
  const S = D.state;

  function initSocket() {{
    const socket = io();
    window.socket = socket;
    return socket;
  }}

  function registerHandlers() {{
{chr(10).join('    ' + line for line in register.splitlines())}
{chr(10).join('    ' + line for line in sonos_reg.splitlines())}
  }}

  function exposeShims() {{
    window.setDarkMode = (mode) => PCCS.darkMode.setDarkMode(mode);
    window.changeTheme = (theme) => PCCSTheme.change(theme);
    window.forceNoFix = (enabled) => D.gps.forceNoFix(enabled);
    window.forcePhase = (phase) => D.phases.forcePhase(phase);
    window.clearPhaseForce = () => D.phases.clearPhaseForce();
    window.sendCustomToast = (type) => D.toasts.sendCustomToast(type);
    window.sendCustomPersistent = () => D.toasts.sendCustomPersistent();
    window.switchActiveSonosPlayer = (name) => D.sonos.switchActive(name);
    window.sonosDiagCommand = (name, cmd) => D.sonos.command(name, cmd);
    window.setVolumeDiag = (name, vol) => D.sonos.setVolume(name, vol);
    window.toggleMuteDiag = (name) => D.sonos.toggleMute(name);
    window.scanWifiNetworks = () => D.system.scanWifi();
    window.onWifiNetworkChanged = () => D.system.onWifiChanged();
    window.connectToSelectedWifi = () => D.system.connectWifi();
  }}

  function boot() {{
{chr(10).join('    ' + line for line in boot.splitlines())}

    setInterval(() => {{
      const el = document.getElementById('core-info');
      if (el && el.offsetParent !== null) D.system.loadCoreInfo();
    }}, 8000);
  }}

  function init() {{
    initSocket();
    if (typeof registerThemeListener === 'function') registerThemeListener();
    PCCS.darkMode.register(getSocket());
    registerHandlers();
    exposeShims();
    if (document.readyState === 'loading') {{
      document.addEventListener('DOMContentLoaded', boot);
    }} else {{
      boot();
    }}
  }}

  init();
}})();
"""
    (DIAG_JS / "app.js").write_text(app)

    if not DIAG_BACKUP.exists():
        DIAG_BACKUP.write_text(html)
    DIAG_SRC.write_text(slim_html(body_html))
    print("OK: diag extracted")


if __name__ == "__main__":
    main()