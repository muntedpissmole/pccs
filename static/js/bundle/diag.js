(() => {
  // ../static/js/namespace.js
  var PCCS = globalThis.PCCS ?? {};
  globalThis.PCCS = PCCS;
  function getSocket() {
    return PCCS.app?.socket ?? globalThis.socket ?? null;
  }
  PCCS.getSocket = getSocket;

  // ../static/js/format-utils.js
  function formatTime(seconds) {
    if (!seconds || isNaN(seconds)) return "0:00";
    const min = Math.floor(seconds / 60);
    const sec = Math.floor(seconds % 60);
    return `${min}:${sec.toString().padStart(2, "0")}`;
  }
  function formatTTG(mins) {
    if (mins === null || mins === void 0 || mins <= 0) return "\u2014";
    if (mins >= 65e3) return "\u221E";
    const h = Math.floor(mins / 60);
    const m = Math.round(mins % 60);
    if (h > 0) return `${h}h ${m.toString().padStart(2, "0")}m`;
    return `${m}m`;
  }
  function stripLeadingZero(timeStr) {
    if (!timeStr) return timeStr;
    return timeStr.replace(/^0/, "");
  }
  function parseTimeToMinutes(str) {
    if (!str || typeof str !== "string") return null;
    let s = str.trim().toUpperCase();
    const m = s.match(/^(\d{1,2}):(\d{2})(?::\d{2})?\s*(AM|PM)?$/);
    if (m) {
      let h2 = parseInt(m[1], 10);
      const min2 = parseInt(m[2], 10);
      const ap = m[3];
      if (ap === "PM" && h2 < 12) h2 += 12;
      if (ap === "AM" && h2 === 12) h2 = 0;
      if (h2 > 23 || min2 > 59 || isNaN(h2) || isNaN(min2)) return null;
      return h2 * 60 + min2;
    }
    const parts = s.split(":");
    const h = parseInt(parts[0], 10);
    const min = parseInt(parts[1], 10);
    if (isNaN(h) || isNaN(min)) return null;
    return h % 24 * 60 + min % 60;
  }
  function formatDurationMinutes(mins, opts = {}) {
    if (mins == null || isNaN(mins)) return opts.fallback || "\u2014";
    if (mins >= 65e3 && opts.infiniteSentinel) return opts.infiniteSentinel;
    return formatTTG(mins);
  }
  PCCS.format = {
    time: formatTime,
    ttg: formatTTG,
    stripLeadingZero,
    parseTimeToMinutes,
    durationMinutes: formatDurationMinutes
  };
  globalThis.formatTime = formatTime;
  globalThis.formatTTG = formatTTG;
  globalThis.stripLeadingZero = stripLeadingZero;
  globalThis.parseTimeToMinutes = parseTimeToMinutes;

  // ../static/js/theme-manager.js
  var currentThemeFile = null;
  function applyTheme(themeFile) {
    if (!themeFile) themeFile = "base";
    currentThemeFile = themeFile;
    document.documentElement.setAttribute("data-theme", themeFile);
    document.querySelectorAll("link[data-theme-link]").forEach((link2) => link2.remove());
    if (themeFile === "base") {
      document.documentElement.setAttribute("data-theme-loaded", "true");
      return;
    }
    const cssPath = `/static/css/themes/${themeFile}.css?v=${Date.now()}`;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = cssPath;
    link.dataset.themeLink = "true";
    link.onload = () => document.documentElement.setAttribute("data-theme-loaded", "true");
    link.onerror = () => document.documentElement.setAttribute("data-theme-loaded", "true");
    document.head.appendChild(link);
  }
  function registerThemeListener(socketArg) {
    const sock = socketArg || globalThis.socket;
    if (!sock) {
      console.debug("[ThemeManager] registerThemeListener called before socket available");
      return;
    }
    sock.off("global_theme_update");
    sock.on("global_theme_update", function(data) {
      if (data && data.theme) applyTheme(data.theme);
    });
  }
  async function loadCurrentTheme() {
    try {
      const res = await fetch("/api/current-theme");
      const data = await res.json();
      applyTheme(data.theme || "base");
    } catch (e) {
      console.error("Failed to load current theme", e);
      applyTheme("base");
    }
  }
  async function loadQuickThemes() {
    try {
      const res = await fetch("/api/themes");
      const data = await res.json();
      const select = document.getElementById("quick-theme-select");
      if (!select) return;
      select.innerHTML = "";
      data.themes.forEach((t) => {
        const opt = document.createElement("option");
        opt.value = t.file;
        opt.textContent = t.name;
        select.appendChild(opt);
      });
      const cur = await (await fetch("/api/current-theme")).json();
      if (cur.theme) select.value = cur.theme;
    } catch (e) {
      console.warn("Failed to load quick themes", e);
    }
  }
  function changeTheme(theme) {
    const sock = globalThis.socket;
    if (sock) {
      sock.emit("set_global_theme", { theme });
    } else {
      console.warn("[ThemeManager] changeTheme called but no socket available yet");
    }
  }
  globalThis.PCCSTheme = {
    apply: applyTheme,
    loadCurrent: loadCurrentTheme,
    loadQuick: loadQuickThemes,
    change: changeTheme,
    registerListener: registerThemeListener,
    getCurrent: () => currentThemeFile
  };
  globalThis.applyTheme = applyTheme;
  globalThis.registerThemeListener = registerThemeListener;
  globalThis.loadCurrentTheme = loadCurrentTheme;
  globalThis.loadQuickThemes = loadQuickThemes;
  globalThis.changeTheme = changeTheme;
  function tryRegisterListener() {
    if (globalThis.socket) {
      registerThemeListener(globalThis.socket);
      return true;
    }
    return false;
  }
  if (!tryRegisterListener()) {
    let attempts = 0;
    const iv = setInterval(() => {
      attempts++;
      if (tryRegisterListener() || attempts > 20) {
        clearInterval(iv);
      }
    }, 50);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      if (!document.documentElement.hasAttribute("data-theme-loaded")) {
        loadCurrentTheme();
      }
    });
  } else {
    if (!document.documentElement.hasAttribute("data-theme-loaded")) {
      loadCurrentTheme();
    }
  }

  // ../static/js/dark-mode.js
  function updateFooterModeIcon(mode) {
    const icon = document.getElementById("footer-mode-icon");
    if (!icon) return;
    if (mode === "light") {
      icon.classList.remove("fa-moon");
      icon.classList.add("fa-sun");
    } else {
      icon.classList.remove("fa-sun");
      icon.classList.add("fa-moon");
    }
  }
  function applyDarkMode(data) {
    const mode = data.mode;
    const isForced = data.forced === true;
    const html = document.documentElement;
    html.classList.remove("dark", "light");
    html.classList.add(mode);
    updateFooterModeIcon(mode);
    const themeText = document.getElementById("diag-theme-text");
    const icon = document.getElementById("mode-icon");
    if (themeText && icon) {
      if (mode === "light") {
        themeText.textContent = isForced ? "Force Dark Mode" : "Switch to Dark Mode";
        icon.classList.remove("fa-moon");
        icon.classList.add("fa-sun");
      } else {
        themeText.textContent = isForced ? "Force Light Mode" : "Switch to Light Mode";
        icon.classList.remove("fa-sun");
        icon.classList.add("fa-moon");
      }
    }
  }
  function requestInitialDarkMode() {
    const socket = getSocket();
    if (!socket) return;
    if (socket.connected) {
      socket.emit("get_current_dark_mode");
    } else {
      setTimeout(requestInitialDarkMode, 300);
    }
  }
  function setDarkMode(mode) {
    getSocket().emit("set_global_dark_mode", { mode });
  }
  function updateActiveModeButton(mode) {
    document.getElementById("btn-dark")?.classList.toggle("active", mode === "dark");
    document.getElementById("btn-light")?.classList.toggle("active", mode === "light");
  }
  PCCS.darkMode = {
    applyDarkMode,
    requestInitialDarkMode,
    setDarkMode,
    updateActiveModeButton,
    register(socket) {
      socket.on("global_dark_mode_update", (data) => {
        applyDarkMode(data);
        updateActiveModeButton(data.mode);
      });
      socket.on("global_theme_update", (data) => {
        const select = document.getElementById("quick-theme-select");
        if (select && data.theme) select.value = data.theme;
      });
    }
  };

  // ../static/js/diag/namespace.js
  PCCS.diag = PCCS.diag || {};
  PCCS.diag.state = {
    reedsCache: {},
    screenData: {},
    lastSystemInfo: {},
    sonosSpeakers: [],
    activeSonos: null,
    sonosStates: {},
    wifiNetworks: []
  };

  // ../static/js/diag/utils.js
  var D = PCCS.diag;
  function toTitleCase(str) {
    return str.replace(
      /\w\S*/g,
      (txt) => txt.charAt(0).toUpperCase() + txt.substr(1).toLowerCase()
    );
  }
  D.utils = { toTitleCase };

  // ../static/js/diag/appearance.js
  var D2 = PCCS.diag;
  function loadThemes() {
    fetch("/api/themes").then((r) => r.json()).then((data) => {
      const select = document.getElementById("theme-select");
      select.innerHTML = "";
      data.themes.forEach((t) => {
        const opt = document.createElement("option");
        opt.value = t.file;
        opt.textContent = t.name;
        select.appendChild(opt);
      });
      fetch("/api/current-theme").then((r) => r.json()).then((cur) => {
        if (cur.theme) select.value = cur.theme;
      });
    }).catch(() => {
    });
  }
  D2.appearance = { loadThemes };

  // ../static/js/diag/gps.js
  var D3 = PCCS.diag;
  function updateGPS(data) {
    const container = document.getElementById("gps-data");
    let html = `
    <div class="status-row"><span>Fix Quality</span><span><strong>${data.fix_quality || 0}</strong></span></div>
    <div class="status-row"><span>Satellites</span><span>${data.satellites || 0}</span></div>
    <div class="status-row"><span>Latitude</span><span>${data.latitude?.toFixed(6) || "\u2014"}</span></div>
    <div class="status-row"><span>Longitude</span><span>${data.longitude?.toFixed(6) || "\u2014"}</span></div>
    <div class="status-row"><span>Speed</span><span>${data.speed_kmh || 0} km/h</span></div>
    <div class="status-row"><span>Suburb</span><span>${data.suburb || data.fallback_suburb || "\u2014"}</span></div>
    <div class="status-row"><span>Local Time</span><span>${data.local_time || "\u2014"}</span></div>
    <div class="status-row"><span>Sunrise</span><span>${data.sunrise || "\u2014"}</span></div>
    <div class="status-row"><span>Sunset</span><span>${data.sunset || "\u2014"}</span></div>
  `;
    container.innerHTML = html;
    document.getElementById("gps-raw").textContent = (data.raw_sentences || []).join("\n");
  }
  function forceNoFix(enabled) {
    getSocket().emit("set_gps_simulation", { no_fix: enabled });
  }
  D3.gps = { updateGPS, forceNoFix };

  // ../static/js/diag/reeds.js
  var D4 = PCCS.diag;
  var S = D4.state;
  var toTitleCase2 = D4.utils.toTitleCase;
  function updateReeds(data) {
    S.reedsCache = data;
    const states = data.states || {};
    const forced = data.forced || {};
    Object.keys(states).forEach((name) => {
      const card = document.querySelector(`.tile[data-name="${CSS.escape(name)}"]`);
      if (!card) return;
      const isForced = name in forced;
      const forcedClosed = isForced ? forced[name] : null;
      const realClosed = states[name];
      const displayState = isForced ? forcedClosed ? "FORCED CLOSED" : "FORCED OPEN" : realClosed ? "CLOSED" : "OPEN";
      const color = (isForced ? forcedClosed : realClosed) ? "#4ade80" : "#f87171";
      const stateEl = card.querySelector(`#state-${CSS.escape(name)}`);
      if (stateEl) {
        stateEl.textContent = displayState;
        stateEl.style.color = color;
      }
      const btns = card.querySelectorAll("button");
      if (btns.length >= 2) {
        btns[0].classList.toggle("active-force", isForced && forcedClosed);
        btns[1].classList.toggle("active-force", isForced && !forcedClosed);
      }
    });
  }
  function renderReeds(data) {
    const container = document.getElementById("reeds-list");
    container.innerHTML = "";
    const states = data.states || {};
    const forced = data.forced || {};
    const sortedNames = Object.keys(states).sort((a, b) => a.localeCompare(b));
    sortedNames.forEach((name) => {
      const isForced = name in forced;
      const forcedClosed = isForced ? forced[name] : null;
      const realClosed = states[name];
      let displayState = isForced ? forcedClosed ? "FORCED CLOSED" : "FORCED OPEN" : realClosed ? "CLOSED" : "OPEN";
      let color = (isForced ? forcedClosed : realClosed) ? "#4ade80" : "#f87171";
      const card = document.createElement("div");
      card.className = "tile";
      card.dataset.name = name;
      card.innerHTML = `
                      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
                          <strong>${toTitleCase2(name.replace(/_/g, " "))}</strong>
                          <div id="state-${name}" style="font-size:1.4rem; font-weight:700; color:${color};">${displayState}</div>
                      </div>
                      <div class="btn-group">
                          <button class="btn">\u{1F512} Force Closed</button>
                          <button class="btn">\u{1F513} Force Open</button>
                          <button class="btn danger">\u274C Clear Force</button>
                      </div>
                  `;
      const buttons = card.querySelectorAll("button");
      buttons[0].addEventListener("click", () => forceReedOptimistic(name, true));
      buttons[1].addEventListener("click", () => forceReedOptimistic(name, false));
      buttons[2].addEventListener("click", () => clearReedForceOptimistic(name));
      container.appendChild(card);
    });
  }
  function forceReedOptimistic(name, closed) {
    const card = document.querySelector(`.tile[data-name="${CSS.escape(name)}"]`);
    if (!card) return;
    const stateEl = card.querySelector(`#state-${CSS.escape(name)}`);
    if (stateEl) {
      stateEl.textContent = closed ? "FORCED CLOSED" : "FORCED OPEN";
      stateEl.style.color = "#4ade80";
    }
    const btns = card.querySelectorAll("button");
    if (btns.length >= 2) {
      btns[0].classList.toggle("active-force", closed);
      btns[1].classList.toggle("active-force", !closed);
    }
    getSocket().emit("force_reed", { name, closed });
  }
  function clearReedForceOptimistic(name) {
    const card = document.querySelector(`.tile[data-name="${CSS.escape(name)}"]`);
    if (!card) return;
    const stateEl = card.querySelector(`#state-${CSS.escape(name)}`);
    if (stateEl && S.reedsCache.states && S.reedsCache.states[name] !== void 0) {
      const real = S.reedsCache.states[name];
      stateEl.textContent = real ? "CLOSED" : "OPEN";
      stateEl.style.color = real ? "#4ade80" : "#f87171";
    }
    const btns = card.querySelectorAll("button");
    btns.forEach((b) => b.classList.remove("active-force"));
    getSocket().emit("force_reed", { name, closed: null });
  }
  D4.reeds = { updateReeds, renderReeds };

  // ../static/js/diag/screens.js
  var D5 = PCCS.diag;
  var S2 = D5.state;
  function renderScreens() {
    const container = document.getElementById("screens-list");
    container.innerHTML = "";
    Object.keys(S2.screenData).forEach((name) => {
      const item = S2.screenData[name] || {};
      const conf = item.config || {};
      const friendly = conf.friendly || name;
      const icon = conf.icon || "fa-display";
      const connColor = item.online ? "#4ade80" : "#f87171";
      const connText = item.online ? `ONLINE${item.latency ? ` (${item.latency}ms)` : ""}` : "OFFLINE";
      const sshStatus = item.ssh_passwordless !== void 0 && item.online ? item.ssh_passwordless ? "\u2705 Passwordless SSH OK" : "\u274C Passwordless SSH failed" : "";
      let wakeHTML = "";
      if (item.online !== false) {
        const stateColor = item.on ? "#60a5fa" : "#94a3b8";
        let stateText = item.on ? "\u{1F31E} AWAKE" : "\u{1F319} SLEEP";
        if (item.brightness !== void 0 && item.brightness !== null) {
          stateText += ` (${item.brightness})`;
        }
        wakeHTML = `
                          <div style="font-size:1.05rem; font-weight:700; color:${stateColor}; margin-bottom:4px;">
                              ${stateText}
                          </div>`;
      }
      const card = document.createElement("div");
      card.className = "tile";
      card.dataset.name = name;
      card.innerHTML = `
                      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
                          <strong><i class="fas ${icon}"></i> ${friendly}</strong>
                          <div style="text-align:right; line-height:1.45;">
                              ${wakeHTML}
                              <div id="screen-conn-${name}" style="font-size:0.95rem; font-weight:600; color:${connColor}">
                                  ${connText}
                              </div>
                              ${sshStatus ? `<div style="font-size:0.85rem; opacity:0.8;">${sshStatus}</div>` : ""}
                              ${item.ssh_error ? `<div style="font-size:0.7rem; color:#f87171; opacity:0.85; max-width:220px; word-break:break-all; margin-top:1px;">${item.ssh_error}</div>` : ""}
                          </div>
                      </div>
                      <div class="btn-group">
                          <button class="btn">\u{1F31E} Wake</button>
                          <button class="btn">\u{1F319} Sleep</button>
                          <button class="btn test-btn">\u{1F50D} Test</button>
                      </div>
                  `;
      const btns = card.querySelectorAll("button");
      btns[0].onclick = () => toggleScreen(name, true);
      btns[1].onclick = () => toggleScreen(name, false);
      const testBtnEl = card.querySelector(".test-btn");
      if (testBtnEl) testBtnEl.onclick = () => testSingleScreen(name);
      container.appendChild(card);
    });
  }
  async function testSingleScreen(name) {
    const card = document.querySelector(`.tile[data-name="${CSS.escape(name)}"]`);
    if (!card) return;
    const testBtn = card.querySelector(".test-btn");
    const statusEl = document.getElementById(`screen-conn-${name}`);
    const originalBtnText = testBtn ? testBtn.textContent : "\u{1F50D} Test";
    if (testBtn) {
      testBtn.textContent = "Testing...";
      testBtn.style.opacity = "0.7";
      testBtn.disabled = true;
    }
    if (statusEl) {
      statusEl.textContent = "Testing connection...";
      statusEl.style.color = "#facc15";
    }
    try {
      const res = await fetch("/screen_status_json");
      if (!res.ok) throw new Error("Network error");
      const data = await res.json();
      if (data.screens) {
        Object.assign(S2.screenData, data.screens);
        await new Promise((resolve) => setTimeout(resolve, 600));
        renderScreens();
      }
    } catch (err) {
      console.error("Test failed", err);
      if (statusEl) {
        statusEl.textContent = "TEST FAILED";
        statusEl.style.color = "#f87171";
      }
    } finally {
      setTimeout(() => {
        if (testBtn) {
          testBtn.textContent = originalBtnText;
          testBtn.style.opacity = "1";
          testBtn.disabled = false;
        }
      }, 400);
    }
  }
  async function loadScreensWithStatus() {
    try {
      const response = await fetch("/screen_status_json");
      if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
      const data = await response.json();
      S2.screenData = data.screens || {};
      renderScreens();
    } catch (err) {
      console.error("Failed to load screen status:", err);
      const container = document.getElementById("screens-list");
      if (container) {
        container.innerHTML = `
                          <div class="tile" style="text-align:center; padding:40px; color:#f87171;">
                              <strong>\u26A0\uFE0F Could not load touchscreen status</strong><br>
                              <small>Check server connection or logs</small>
                          </div>`;
      }
    }
  }
  function toggleScreen(name, forceOn) {
    getSocket().emit("screen_manual_toggle", { name, on: forceOn });
    setTimeout(() => testSingleScreen(name), 1e3);
  }
  D5.screens = { renderScreens, loadScreensWithStatus };

  // ../static/js/diag/phases.js
  var D6 = PCCS.diag;
  function updatePhaseForced(data) {
    document.getElementById("phase-forced").innerHTML = data.forced ? `<span style="color:#fbbf24;">\u{1F527} FORCED</span>` : "Automatic";
  }
  function updatePhase(data) {
    document.getElementById("current-phase").innerHTML = `
    ${data.phase === "Day" ? "\u{1F31E}" : data.phase === "Evening" ? "\u{1F305}" : "\u{1F319}"} 
    ${data.phase || "Unknown"}
  `;
    let timingsHTML = data.day_start ? `
    <div class="status-row"><span>Day starts</span><span>${data.day_start}</span></div>
    <div class="status-row"><span>Evening starts</span><span>${data.evening_start}</span></div>
    <div class="status-row"><span>Night starts</span><span>${data.night_start}</span></div>
  ` : "";
    document.getElementById("phase-timings").innerHTML = timingsHTML;
  }
  function forcePhase(phase) {
    document.getElementById("current-phase").innerHTML = `
    ${phase === "Day" ? "\u{1F31E}" : phase === "Evening" ? "\u{1F305}" : "\u{1F319}"} ${phase}
  `;
    document.getElementById("phase-forced").innerHTML = `<span style="color:#fbbf24;">\u{1F527} FORCED</span>`;
    getSocket().emit("force_phase", { phase });
  }
  function clearPhaseForce() {
    document.getElementById("phase-forced").innerHTML = "Automatic";
    getSocket().emit("force_phase", { phase: null });
  }
  D6.phases = { updatePhase, updatePhaseForced, forcePhase, clearPhaseForce };

  // ../static/js/diag/toasts.js
  var D7 = PCCS.diag;
  function sendCustomToast(type) {
    const title = document.getElementById("toast-title").value.trim() || "Diagnostics Test";
    const message = document.getElementById("toast-message").value.trim() || "Test toast from diagnostics page.";
    getSocket().emit("toast_test", { title, message, type, duration: 5500 });
  }
  function sendCustomPersistent() {
    const title = document.getElementById("toast-title").value.trim() || "Persistent Toast";
    const message = document.getElementById("toast-message").value.trim() || "This toast stays until dismissed.";
    getSocket().emit("toast_test", { title, message, type: "warning", persistent: true });
  }
  D7.toasts = { sendCustomToast, sendCustomPersistent };

  // ../static/js/diag/sonos.js
  var D8 = PCCS.diag;
  var S3 = D8.state;
  var formatTime2 = PCCS.format.time;
  function renderPlayers(speakers, active) {
    S3.sonosSpeakers = speakers || [];
    S3.activeSonos = active;
    const select = document.getElementById("active-sonos-player");
    select.innerHTML = '<option value="">\u2014 No player selected \u2014</option>';
    S3.sonosSpeakers.forEach((name) => {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      if (name === active) opt.selected = true;
      select.appendChild(opt);
    });
    const container = document.getElementById("sonos-players-grid");
    container.innerHTML = "";
    if (S3.sonosSpeakers.length === 0) {
      container.innerHTML = `
                  <div class="tile" style="grid-column: 1 / -1; text-align:center; padding:40px; opacity:0.7;">
                      <i class="fas fa-music fa-3x mb-4"></i><br>
                      No Sonos players discovered
                  </div>`;
      return;
    }
    S3.sonosSpeakers.forEach((name) => {
      const state = S3.sonosStates[name] || { track: "Nothing playing", artist: "", album_art: "", is_playing: false, volume: 30, mute: false, position: 0, duration: 0 };
      const isActive = name === active;
      const hasArt = !!state.album_art;
      const progress = state.duration > 0 ? Math.min(100, Math.round(state.position / state.duration * 100)) : 0;
      const card = document.createElement("div");
      card.className = `tile ${isActive ? "border-2 border-sky-400" : ""}`;
      card.innerHTML = `
                  <div style="height:180px; background-image: url('${hasArt ? state.album_art : "https://placehold.co/600x600/1f2937/4fc3f7?text=No+Art"}'); 
                              background-size: cover; background-position: center; border-radius: 12px 12px 0 0; position: relative;">
                      <div style="position:absolute; inset:0; background: linear-gradient(to bottom, transparent, rgba(0,0,0,0.85)); border-radius: 12px 12px 0 0;"></div>
                      ${isActive ? `<div style="position:absolute; top:12px; right:12px; background:rgba(16,185,129,0.9); color:white; padding:4px 12px; border-radius:9999px; font-size:0.8rem; font-weight:700;">ACTIVE</div>` : ""}
                  </div>

                  <div style="padding:16px;">
                      <div style="display:flex; justify-content:space-between; align-items:start; margin-bottom:12px;">
                          <strong style="font-size:1.15rem;">${name}</strong>
                          <button onclick="switchActiveSonosPlayer('${name}')" class="btn ${isActive ? "success" : ""}" style="padding:6px 14px; font-size:0.9rem;">
                              ${isActive ? "\u2713 Active" : "Set Active"}
                          </button>
                      </div>

                      <div style="margin-bottom:12px; min-height:50px;">
                          <div style="font-weight:600;">${state.track}</div>
                          <div style="opacity:0.75; font-size:0.95rem;">${state.artist || "\u2014"}</div>
                      </div>

                      <div style="margin:12px 0 16px;">
                          <div style="height:5px; background:rgba(255,255,255,0.2); border-radius:9999px; overflow:hidden;">
                              <div style="width:${progress}%; height:100%; background:#4fc3f7;"></div>
                          </div>
                          <div style="display:flex; justify-content:space-between; font-size:0.8rem; margin-top:4px; opacity:0.75;">
                              <span>${PCCS.format.time(state.position)}</span>
                              <span>${PCCS.format.time(state.duration)}</span>
                          </div>
                      </div>

                      <div style="display:flex; align-items:center; gap:10px;">
                          <i onclick="toggleMuteDiag('${name}')" class="fas fa-volume-${state.mute ? "mute" : "high"} cursor-pointer" style="font-size:1.4rem; width:32px;"></i>
                          <input type="range" min="0" max="100" value="${state.volume}" 
                                 oninput="setVolumeDiag('${name}', this.value)" style="flex:1; accent-color:#4fc3f7;">
                          <span style="font-family:monospace; width:42px; text-align:right;">${state.volume}%</span>
                      </div>

                      <div style="margin-top:14px; display:flex; gap:8px; justify-content:center;">
                          <button onclick="sonosDiagCommand('${name}', 'previous')" class="btn">\u23EE</button>
                          <button onclick="sonosDiagCommand('${name}', 'playpause')" class="btn" style="min-width:52px;">
                              ${state.is_playing ? "\u23F8" : "\u25B6"}
                          </button>
                          <button onclick="sonosDiagCommand('${name}', 'next')" class="btn">\u23ED</button>
                      </div>
                  </div>
              `;
      container.appendChild(card);
    });
  }
  function command(name, command2) {
    getSocket().emit("sonos_command", { speaker: name, command: command2 });
  }
  function setVolume(name, volume) {
    getSocket().emit("sonos_command", { speaker: name, command: "volume", value: parseInt(volume) });
  }
  function toggleMute(name) {
    getSocket().emit("sonos_command", { speaker: name, command: "mute" });
  }
  function switchActive(name) {
    if (name) getSocket().emit("sonos_switch_speaker", { name });
  }
  D8.sonos = { renderPlayers, command, setVolume, toggleMute, switchActive };

  // ../static/js/diag/system.js
  var D9 = PCCS.diag;
  var S4 = D9.state;
  function renderCoreInfo(data) {
    S4.lastSystemInfo = data;
    document.getElementById("system-overview").innerHTML = `
  			<div class="status-row"><span>Hostname</span><span>${data.hostname || "\u2014"}</span></div>
  			<div class="status-row"><span>Model</span><span>${data.model || "\u2014"}</span></div>
  			<div class="status-row"><span>OS</span><span>${data.os || "\u2014"}</span></div>
  			<div class="status-row"><span>Kernel</span><span>${data.kernel || "\u2014"}</span></div>
  			<div class="status-row"><span>Uptime</span><span>${data.uptime || "\u2014"}</span></div>
  		`;
    document.getElementById("hardware-info").innerHTML = `
  			<div class="status-row"><span>CPU Model</span><span>${data.cpu_model || "\u2014"}</span></div>
  			<div class="status-row"><span>Cores / Threads</span><span>${data.cpu_cores} / ${data.cpu_threads}</span></div>
  			<div class="status-row"><span>CPU Temp</span><span>${data.cpu_temp ? data.cpu_temp + "\xB0C" : "\u2014"}</span></div>
  		`;
    document.getElementById("cpu-info").innerHTML = `
  			<div class="status-row"><span>CPU Usage</span><span>${data.cpu_percent || 0}%</span></div>
  			<div class="status-row"><span>Load Average</span><span>${data.load_avg || "\u2014"}</span></div>
  			<div class="status-row"><span>Processes</span><span>${data.process_count || "\u2014"}</span></div>
  		`;
    document.getElementById("throttling-info").innerHTML = `
  			<div class="status-row"><span>Status</span><span style="color:${data.throttling_color || "#94a3b8"}">
  				${data.throttling_status || "Unknown"}
  			</span></div>
  			<div class="status-row"><span>Raw Value</span><span style="font-family:monospace; opacity:0.85;">
  				${data.throttling_raw || "N/A"}
  			</span></div>
  		`;
    document.getElementById("pccs-info").innerHTML = `
  			<div class="status-row"><span>Version</span><span>v${data.app_version || "\u2014"}</span></div>
  			<div class="status-row"><span>Python</span><span>${data.python_version || "\u2014"}</span></div>
  			<div class="status-row"><span>Flask</span><span>${data.flask_version || "\u2014"}</span></div>
  			<div class="status-row"><span>Running Since</span><span>${data.running_since || "\u2014"}</span></div>
  			<div class="status-row"><span>Clients</span><span>${data.connected_clients || "\u2014"}</span></div>
  		`;
    document.getElementById("resource-usage").innerHTML = `
  			<div class="status-row"><span>Memory</span><span>${data.memory_used} / ${data.memory_total} MB (${data.memory_percent}%)</span></div>
  			<div class="status-row"><span>Disk</span><span>${data.disk_used} / ${data.disk_total} GB (${data.disk_percent}%)</span></div>
  		`;
    let netDetailHTML = "";
    if (data.network_details && data.network_details.length) {
      data.network_details.forEach((item) => {
        const colonIndex = item.indexOf(":");
        if (colonIndex > 0) {
          const label = item.substring(0, colonIndex);
          const value = item.substring(colonIndex + 1).trim();
          netDetailHTML += `
  						<div class="status-row">
  							<span>${label}</span>
  							<span>${value}</span>
  						</div>`;
        } else {
          netDetailHTML += `<div class="status-row"><span>${item}</span><span></span></div>`;
        }
      });
    } else {
      netDetailHTML = '<div class="status-row"><span>No network data</span><span>\u2014</span></div>';
    }
    document.getElementById("network-details").innerHTML = netDetailHTML;
    try {
      const cur = data.current_wifi || {};
      const el = document.getElementById("wifi-current");
      if (el) {
        if (cur && cur.connected && cur.ssid) {
          let txt = cur.ssid;
          if (cur.iface) txt += ` (${cur.iface})`;
          if (cur.ip) txt += ` \u2014 ${cur.ip}`;
          el.textContent = txt;
        } else {
          el.textContent = "Not connected";
        }
      }
    } catch (e) {
    }
    let dhcpHTML = `
  		<div style="margin-bottom:12px; opacity:0.85; font-size:0.95rem;">
  			Range: <strong>${data.dhcp_range || "Unknown"}</strong>
  		</div>`;
    if (data.dhcp_clients && data.dhcp_clients.length) {
      data.dhcp_clients.forEach((client) => {
        let expiryText = "";
        if (client.lease_expiry) {
          const now = /* @__PURE__ */ new Date();
          const [hours, minutes] = client.lease_expiry.split(":").map(Number);
          let expiryDate = new Date(now);
          expiryDate.setHours(hours, minutes, 0, 0);
          if (expiryDate < now) {
            expiryDate.setDate(expiryDate.getDate() + 1);
          }
          const diffMs = expiryDate - now;
          const diffHours = Math.floor(diffMs / (1e3 * 60 * 60));
          const diffMinutes = Math.floor(diffMs % (1e3 * 60 * 60) / (1e3 * 60));
          if (diffHours > 0) {
            expiryText = ` <span style="opacity:0.7">(${diffHours}h ${diffMinutes}m left)</span>`;
          } else if (diffMinutes > 0) {
            expiryText = ` <span style="opacity:0.7">(${diffMinutes}m left)</span>`;
          } else {
            expiryText = ` <span style="opacity:0.7">(expiring soon)</span>`;
          }
        }
        dhcpHTML += `
  				<div class="status-row">
  					<span>${client.name}</span>
  					<span style="text-align:right;">
  						${client.ip}${expiryText}<br>
  						<small style="opacity:0.5">${client.mac}</small>
  					</span>
  				</div>`;
      });
    } else {
      dhcpHTML += '<div class="status-row"><span>No clients connected</span><span>\u2014</span></div>';
    }
    document.getElementById("dhcp-clients").innerHTML = dhcpHTML;
    let procHTML = "";
    if (data.top_processes && data.top_processes.length) {
      data.top_processes.forEach((p) => {
        procHTML += `
  					<div class="status-row">
  						<span>${p.name}</span>
  						<span>${p.cpu}% CPU \u2022 ${p.mem}% MEM</span>
  					</div>`;
      });
    } else {
      procHTML = '<div class="status-row"><span>No data</span></div>';
    }
    document.getElementById("top-processes").innerHTML = procHTML;
  }
  async function scanWifi() {
    const select = document.getElementById("wifi-network-select");
    const statusEl = document.getElementById("wifi-status");
    if (statusEl) {
      statusEl.textContent = "Scanning\u2026";
      statusEl.style.color = "#facc15";
    }
    if (select) select.disabled = true;
    try {
      const res = await fetch("/api/wifi/scan");
      if (!res.ok) throw new Error("Scan request failed");
      const data = await res.json();
      S4.wifiNetworks = data.networks || [];
      if (select) {
        select.innerHTML = "";
        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = S4.wifiNetworks.length ? "\u2014 Select a network \u2014" : "No networks found";
        select.appendChild(placeholder);
        S4.wifiNetworks.forEach((n) => {
          const opt = document.createElement("option");
          opt.value = n.ssid;
          const sig = typeof n.signal === "number" ? ` ${n.signal}%` : "";
          const sec = n.security ? ` [${n.security}]` : "";
          const inUse = n.in_use ? " \u2713" : "";
          opt.textContent = `${n.ssid}${sig}${sec}${inUse}`;
          opt.dataset.security = n.security || "open";
          opt.dataset.signal = n.signal != null ? String(n.signal) : "";
          if (n.in_use) opt.dataset.inUse = "true";
          select.appendChild(opt);
        });
      }
      const curEl = document.getElementById("wifi-current");
      if (curEl && data.current) {
        const c = data.current;
        if (c.connected && c.ssid) {
          let t = c.ssid;
          if (c.iface) t += ` (${c.iface})`;
          if (c.ip) t += ` \u2014 ${c.ip}`;
          curEl.textContent = t;
        } else {
          curEl.textContent = "Not connected";
        }
      }
      if (statusEl) {
        statusEl.textContent = S4.wifiNetworks.length ? `${S4.wifiNetworks.length} network(s) found` : "No networks found";
        statusEl.style.color = "";
      }
    } catch (err) {
      console.error("WiFi scan failed", err);
      if (statusEl) {
        statusEl.textContent = "Scan failed (see console/logs)";
        statusEl.style.color = "#f87171";
      }
    } finally {
      if (select) select.disabled = false;
    }
  }
  function onWifiChanged() {
    const select = document.getElementById("wifi-network-select");
    const pwContainer = document.getElementById("wifi-password-container");
    const pwInput = document.getElementById("wifi-password");
    if (!select || !pwContainer) return;
    const opt = select.options[select.selectedIndex];
    const sec = opt && opt.dataset.security ? opt.dataset.security.toLowerCase() : "";
    const needsPw = sec && !["open", "--", ""].includes(sec) && !sec.includes("open");
    if (needsPw) {
      pwContainer.style.display = "";
      if (pwInput) pwInput.placeholder = "Password required";
    } else {
      pwContainer.style.display = "none";
      if (pwInput) pwInput.value = "";
    }
  }
  async function connectWifi() {
    const select = document.getElementById("wifi-network-select");
    const pwInput = document.getElementById("wifi-password");
    const statusEl = document.getElementById("wifi-status");
    const btns = document.querySelectorAll("#wifi-tile button");
    if (!select || !select.value) {
      if (statusEl) {
        statusEl.textContent = "Please scan and select a network first";
        statusEl.style.color = "#f87171";
      }
      return;
    }
    const ssid = select.value;
    const password = pwInput && pwInput.offsetParent !== null ? pwInput.value || null : null;
    btns.forEach((b) => {
      b.disabled = true;
      b.style.opacity = "0.6";
    });
    if (statusEl) {
      statusEl.textContent = `Connecting to ${ssid}\u2026`;
      statusEl.style.color = "#facc15";
    }
    try {
      const res = await fetch("/api/wifi/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ssid, password })
      });
      const data = await res.json();
      if (data && data.success) {
        if (statusEl) {
          statusEl.textContent = data.message || `Connected to ${ssid}`;
          statusEl.style.color = "#4ade80";
        }
        setTimeout(() => {
          try {
            D9.system.loadCoreInfo();
          } catch (_) {
          }
        }, 1200);
        setTimeout(() => {
          try {
            D9.system.scanWifi();
          } catch (_) {
          }
        }, 2500);
      } else {
        if (statusEl) {
          statusEl.textContent = data && data.message ? data.message : "Connection failed";
          statusEl.style.color = "#f87171";
        }
      }
    } catch (err) {
      console.error("WiFi connect failed", err);
      if (statusEl) {
        statusEl.textContent = "Connect request failed";
        statusEl.style.color = "#f87171";
      }
    } finally {
      setTimeout(() => {
        btns.forEach((b) => {
          b.disabled = false;
          b.style.opacity = "";
        });
      }, 600);
    }
  }
  async function loadCoreInfo() {
    try {
      const res = await fetch("/api/system_info");
      if (!res.ok) throw new Error("Failed to fetch");
      const data = await res.json();
      renderCoreInfo(data);
    } catch (err) {
      console.error("Failed to load core info:", err);
      document.getElementById("raw-system-info").innerHTML = `<span style="color:#f87171;">\u26A0\uFE0F Could not load system information</span>`;
    }
  }
  D9.system = { renderCoreInfo, loadCoreInfo, scanWifi, onWifiChanged, connectWifi };

  // ../static/js/diag/app.js
  var D10 = PCCS.diag;
  var S5 = D10.state;
  function initSocket() {
    const socket = io();
    globalThis.socket = socket;
    return socket;
  }
  function registerHandlers() {
    const socket = getSocket();
    socket.on("gps_update", D10.gps.updateGPS);
    socket.on("reed_diag_update", D10.reeds.updateReeds);
    socket.on("phase_update", D10.phases.updatePhase);
    socket.on("phase_diag_update", D10.phases.updatePhaseForced);
    socket.on("screen_update", (data) => {
      if (!data.name) return;
      if (!S5.screenData[data.name]) S5.screenData[data.name] = {};
      S5.screenData[data.name] = { ...S5.screenData[data.name], ...data };
      D10.screens.renderScreens();
    });
    socket.on("dhcp_update", (data) => {
      if (data.dhcp_clients) {
        D10.system.renderCoreInfo({ ...S5.lastSystemInfo, dhcp_clients: data.dhcp_clients });
      }
    });
    socket.on("sonos_speakers", (data) => {
      if (data.enabled === false) {
        document.getElementById("sonos-section").style.display = "none";
        return;
      }
      D10.sonos.renderPlayers(data.speakers, data.current);
    });
    socket.on("sonos_update", (state) => {
      if (state && state.speaker) {
        S5.sonosStates[state.speaker] = state;
        if (S5.sonosSpeakers.length > 0) {
          D10.sonos.renderPlayers(S5.sonosSpeakers, S5.activeSonos);
        }
      }
    });
  }
  function exposeShims() {
    globalThis.setDarkMode = (mode) => PCCS.darkMode.setDarkMode(mode);
    globalThis.changeTheme = (theme) => globalThis.PCCSTheme.change(theme);
    globalThis.forceNoFix = (enabled) => D10.gps.forceNoFix(enabled);
    globalThis.forcePhase = (phase) => D10.phases.forcePhase(phase);
    globalThis.clearPhaseForce = () => D10.phases.clearPhaseForce();
    globalThis.sendCustomToast = (type) => D10.toasts.sendCustomToast(type);
    globalThis.sendCustomPersistent = () => D10.toasts.sendCustomPersistent();
    globalThis.switchActiveSonosPlayer = (name) => D10.sonos.switchActive(name);
    globalThis.sonosDiagCommand = (name, cmd) => D10.sonos.command(name, cmd);
    globalThis.setVolumeDiag = (name, vol) => D10.sonos.setVolume(name, vol);
    globalThis.toggleMuteDiag = (name) => D10.sonos.toggleMute(name);
    globalThis.scanWifiNetworks = () => D10.system.scanWifi();
    globalThis.onWifiNetworkChanged = () => D10.system.onWifiChanged();
    globalThis.connectToSelectedWifi = () => D10.system.connectWifi();
  }
  function boot() {
    fetch("/api/version").then((r) => r.json()).then((v) => {
      const verEl = document.getElementById("app-version");
      if (verEl && v.version) verEl.textContent = `v${v.version}`;
    }).catch(() => {
    });
    D10.appearance.loadThemes();
    D10.screens.loadScreensWithStatus();
    D10.system.loadCoreInfo();
    fetch("/reed_json").then((r) => r.json()).then((data) => {
      D10.reeds.renderReeds(data);
      D10.reeds.updateReeds(data);
    }).catch((err) => console.error("Failed to load reeds:", err));
    fetch("/gps_json").then((r) => r.json()).then(D10.gps.updateGPS).catch(() => {
    });
    fetch("/screen_json").then((r) => r.json()).then((data) => {
      const basic = data.screens || {};
      S5.screenData = { ...basic, ...S5.screenData };
      D10.screens.renderScreens();
    }).catch((err) => console.warn("Could not load screens:", err));
  }
  function init() {
    initSocket();
    registerThemeListener();
    PCCS.darkMode.register(getSocket());
    registerHandlers();
    exposeShims();
    setInterval(() => {
      const el = document.getElementById("core-info");
      if (el && el.offsetParent !== null) D10.system.loadCoreInfo();
    }, 8e3);
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", boot);
    } else {
      boot();
    }
  }
  init();
})();
//# sourceMappingURL=diag.js.map
