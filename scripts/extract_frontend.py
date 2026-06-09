#!/usr/bin/env python3
"""Extract index.html inline JS into static/js modules."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_SRC = ROOT / "templates" / "index.html"

STATE_MAP = [
    ("lightsConfig", "S.lightsConfig"),
    ("currentState", "S.currentState"),
    ("currentModes", "S.currentModes"),
    ("currentReeds", "S.currentReeds"),
    ("lastRenderConfigHash", "S.lastRenderConfigHash"),
    ("currentlyDragging", "S.currentlyDragging"),
    ("userJustSet", "S.userJustSet"),
    ("JUST_SET_DURATION", "S.JUST_SET_DURATION"),
    ("hasValidGPSFix", "S.hasValidGPSFix"),
    ("gpsStatusReceived", "S.gpsStatusReceived"),
    ("lastWeatherUpdate", "S.lastWeatherUpdate"),
    ("WEATHER_INTERVAL_MS", "S.WEATHER_INTERVAL_MS"),
    ("currentScenes", "S.currentScenes"),
]


def extract_inline_js(html: str) -> str:
    m = re.search(r"<script>\s*\n\s*'use strict';(.*)</script>\s*</body>", html, re.DOTALL)
    if not m:
        raise RuntimeError("inline script block not found in source html")
    return m.group(1)


def slice_js(js: str, start: str, end: str | None = None) -> str:
    s = js.find(start)
    if s < 0:
        raise RuntimeError(f"slice start not found: {start!r}")
    e = js.find(end, s) if end else len(js)
    if end and e < 0:
        raise RuntimeError(f"slice end not found: {end!r}")
    return js[s:e].strip()


def xform(body: str) -> str:
    out = body
    for old, new in sorted(STATE_MAP, key=lambda x: -len(x[0])):
        out = re.sub(r"\b" + re.escape(old) + r"\b", new, out)
    out = re.sub(r"\bsocket\.", "getSocket().", out)
    out = out.replace("<!-- ==================== SONOS SOCKET LISTENERS ==================== -->", "")
    # Remove invalid re-declarations on S.*
    out = re.sub(r"^\s*(?:let|const)\s+S\.\w+.*$\n?", "", out, flags=re.MULTILINE)
    return out


def module(name: str, doc: str, body: str, exports: str) -> str:
    return f"""/**
 * PCCS {doc}
 * Extracted from templates/index.html
 */
(function () {{
  'use strict';
  const PCCS = window.PCCS;
  const S = PCCS.state;
  function getSocket() {{ return PCCS.getSocket(); }}

{body}

  PCCS.{name} = {exports};
}})();
"""


def main():
    # Use monolithic backup if current index is already slim
    html = INDEX_SRC.read_text()
    if "pccs-app.js" in html and "<script>\n    'use strict';" not in html:
        backup = ROOT / "templates" / "index.html.monolith.bak"
        if not backup.exists():
            import subprocess
            subprocess.run(
                ["git", "show", "HEAD:templates/index.html"],
                cwd=ROOT,
                stdout=open(backup, "w"),
                check=True,
            )
        html = backup.read_text()

    js = extract_inline_js(html)

    layout = xform(slice_js(js, "function getCurrentColumns()", "// ==================== LIGHTING RENDERING"))
    lighting_body = xform(slice_js(js, "// ==================== LIGHTING RENDERING", "// ==================== GPS, SENSORS"))
    lighting = layout + "\n\n" + lighting_body

    tiles = xform(slice_js(js, "// ==================== GPS, SENSORS", "// ==================== NETWORK TILE"))
    tiles += "\n\n" + xform(slice_js(js, "async function fetchWeatherForecast", "// ==================== SCENES ===================="))
    tiles += "\n\n" + xform(slice_js(js, "// ==================== NETWORK TILE", "async function fetchWeatherForecast"))

    scenes = xform(slice_js(js, "// ==================== DYNAMIC SCENES", "// ==================== INIT ===================="))
    scenes = re.sub(r"window\.setScene\s*=\s*function[\s\S]*?getSocket\(\)\.emit\('set_scene'[^;]*;\s*\};", "", scenes)

    dark = xform(slice_js(js, "// ====================== LIVE DARK/LIGHT MODE", "// ====================== VERSION FETCH"))
    dark += "\n\n" + xform(
        "function setDarkMode(mode) {\n" + slice_js(js, "function setDarkMode(mode)", "function updateActiveModeButton")
    )
    dark += "\n\n" + xform(slice_js(js, "function updateActiveModeButton", "// ====================== TOAST SYSTEM"))
    dark = re.sub(r"window\.toggleGlobalDarkMode\s*=[\s\S]*?};", "", dark)
    dark = re.sub(r"getSocket\(\)\.on\([^)]+\)[^;]*;", "", dark)

    version = xform(slice_js(js, "async function loadVersion()", "// Detects the current number"))

    toasts = xform(slice_js(js, "// ====================== TOAST SYSTEM", "<!-- ==================== SONOS"))
    toasts = re.sub(r"getSocket\(\)\.on\('toast'[^;]*;", "", toasts)

    sonos = xform(slice_js(js, "let currentActiveSonosSpeaker = null", "// ====================== FULLSCREEN TOGGLE"))
    sonos = re.sub(
        r"document\.getElementById\('sonos-progress-container'\)\.addEventListener[\s\S]*?\}\);\s*",
        "",
        sonos,
    )

    victron = xform(slice_js(js, "// ==================== VICTRON / POWER TILE", "function toggleFullscreen"))

    fullscreen = slice_js(js, "function toggleFullscreen()", "document.addEventListener('fullscreenchange'")
    fullscreen += "\n\n" + slice_js(js, "document.addEventListener('fullscreenchange'", "")

    (ROOT / "static/js/lighting-controller.js").write_text(
        module(
            "lighting",
            "Lighting Controller",
            lighting,
            """{
    getCurrentColumns,
    renderLightingControls,
    updateUIFromState,
    updateRooftopTentControls,
    isRooftopTentPhysicallyClosed,
    onLightsConfig(config) {
      S.lightsConfig = config || [];
      renderLightingControls();
      getSocket().emit('get_reeds');
      if (Object.keys(S.currentState).length > 0) updateUIFromState();
    },
    onStateUpdate(newState) {
      const protectedLights = new Set([...S.currentlyDragging, ...S.userJustSet]);
      Object.keys(newState).forEach(k => {
        if (!protectedLights.has(k)) S.currentState[k] = newState[k];
      });
      S.lightsConfig.forEach(light => {
        if (light.has_mode && newState[`${light.name}_mode`]) {
          S.currentModes[light.name] = newState[`${light.name}_mode`];
        }
      });
      updateUIFromState();
    },
    onReedUpdate(payload) {
      S.currentReeds = payload.states || {};
      updateRooftopTentControls();
    },
    initResize() {
      let lastColumnCount = getCurrentColumns();
      function handleResizeForLighting() {
        const newCols = getCurrentColumns();
        if (newCols !== lastColumnCount && S.lightsConfig.length > 0) {
          lastColumnCount = newCols;
          renderLightingControls();
        }
      }
      window.addEventListener('resize', handleResizeForLighting);
      setTimeout(() => { lastColumnCount = getCurrentColumns(); }, 300);
    },
  }""",
        )
    )

    (ROOT / "static/js/tile-updaters.js").write_text(
        module(
            "tiles",
            "Environmental Tile Updaters",
            tiles,
            """{
    updateGPS,
    updateSensors,
    updateNetworkTile,
    updatePhaseInfo,
    updateClock,
    updateTimeAndSun,
    fetchWeatherForecast,
    getWeatherIcon,
  }""",
        )
    )

    (ROOT / "static/js/scenes.js").write_text(
        module(
            "scenes",
            "Scene Buttons",
            scenes,
            """{
    loadScenes,
    renderScenes,
    fixLastRowStretching,
    setScene(sceneKey) {
      document.querySelectorAll('.scene-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.scene === sceneKey);
      });
      setTimeout(() => {
        document.querySelectorAll('.scene-btn').forEach(btn => btn.classList.remove('active'));
      }, 750);
      getSocket().emit('set_scene', { scene: sceneKey });
    },
  }""",
        )
    )

    (ROOT / "static/js/dark-mode.js").write_text(
        module(
            "darkMode",
            "Dark / Light Mode",
            dark,
            """{
    applyDarkMode,
    requestInitialDarkMode,
    setDarkMode,
    updateActiveModeButton,
    register(socket) {
      socket.on('global_dark_mode_update', data => {
        applyDarkMode(data);
        updateActiveModeButton(data.mode);
      });
      socket.on('global_theme_update', data => {
        const select = document.getElementById('quick-theme-select');
        if (select && data.theme) select.value = data.theme;
      });
    },
  }""",
        )
    )

    (ROOT / "static/js/version.js").write_text(
        module("version", "Version Footer", version, "{ loadVersion }")
    )

    (ROOT / "static/js/toasts.js").write_text(
        module(
            "toasts",
            "Toast Notifications",
            toasts,
            """{
    createToast,
    dismissToast,
    register(socket) {
      socket.on('toast', data => createToast(data));
    },
  }""",
        )
    )

    (ROOT / "static/js/sonos-controller.js").write_text(
        module(
            "sonos",
            "Sonos Controller",
            sonos,
            """{
    updateSonosUI,
    startProgressUpdater,
    requestSonosState,
    sonosVolumeChange,
    sonosCommand,
    toggleSonosMute,
    register(socket) {
      socket.on('sonos_speakers', data => {
        if (data.current) currentActiveSonosSpeaker = data.current;
      });
      socket.on('sonos_update', state => {
        if (!state) return;
        if (currentActiveSonosSpeaker && state.speaker && state.speaker !== currentActiveSonosSpeaker) return;
        updateSonosUI(state);
      });
    },
    bindProgressSeek() {
      const el = document.getElementById('sonos-progress-container');
      if (!el) return;
      el.addEventListener('click', function (e) {
        const rect = this.getBoundingClientRect();
        const percent = (e.clientX - rect.left) / rect.width;
        getSocket().emit('sonos_command', { command: 'seek', value: percent });
      });
    },
  }""",
        )
    )

    (ROOT / "static/js/victron-tile.js").write_text(
        module("victron", "Victron Power Tile", victron, "{ updatePowerTile }")
    )

    (ROOT / "static/js/fullscreen.js").write_text(
        module("fullscreen", "Fullscreen Toggle", fullscreen, "{ toggleFullscreen }")
    )

    print("Regenerated JS modules from monolith source.")


if __name__ == "__main__":
    main()