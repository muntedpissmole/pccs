(() => {
  // ../static/js/namespace.js
  var PCCS = globalThis.PCCS ?? {};
  globalThis.PCCS = PCCS;
  function getSocket() {
    return PCCS.app?.socket ?? globalThis.socket ?? null;
  }
  PCCS.getSocket = getSocket;

  // ../static/js/state.js
  PCCS.state = {
    currentState: {},
    currentModes: {},
    currentReeds: {},
    lightsConfig: [],
    lastRenderConfigHash: "",
    currentlyDragging: /* @__PURE__ */ new Set(),
    userJustSet: /* @__PURE__ */ new Set(),
    JUST_SET_DURATION: 2800,
    sceneActivating: false,
    SCENE_RAMP_MS: 4e3,
    sceneAnimationCancels: {},
    hasValidGPSFix: false,
    gpsStatusReceived: false,
    lastWeatherUpdate: 0,
    WEATHER_INTERVAL_MS: 3600 * 1e3,
    currentScenes: []
  };

  // ../static/js/dom-helpers.js
  var cache = /* @__PURE__ */ new Map();
  function $(id, useCache = true) {
    if (!id) return null;
    if (useCache && cache.has(id)) {
      const el2 = cache.get(id);
      if (el2 && el2.isConnected) return el2;
      cache.delete(id);
    }
    const el = document.getElementById(id);
    if (useCache && el) cache.set(id, el);
    return el;
  }
  function clearCache() {
    cache.clear();
  }
  function setText(id, value, fallback = "\u2014") {
    const el = $(id, false);
    if (el) el.textContent = value != null && value !== "" ? value : fallback;
  }
  function toggleClass(id, className, condition) {
    const el = $(id, false);
    if (el) el.classList.toggle(className, !!condition);
  }
  function setStyle(id, prop, value) {
    const el = $(id, false);
    if (el) el.style[prop] = value;
  }
  function q(selector, parent = document) {
    return parent.querySelector(selector);
  }
  function qa(selector, parent = document) {
    return Array.from(parent.querySelectorAll(selector));
  }
  PCCS.dom = {
    $,
    clearCache,
    setText,
    toggleClass,
    setStyle,
    q,
    qa
  };
  globalThis.PCCS_getEl = $;

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
  function parseTimeToMinutes2(str) {
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
    parseTimeToMinutes: parseTimeToMinutes2,
    durationMinutes: formatDurationMinutes
  };
  globalThis.formatTime = formatTime;
  globalThis.formatTTG = formatTTG;
  globalThis.stripLeadingZero = stripLeadingZero;
  globalThis.parseTimeToMinutes = parseTimeToMinutes2;

  // ../static/js/animation-utils.js
  var DEFAULT_EASE = (p) => 1 - Math.pow(1 - p, 3);
  function animate(options) {
    const {
      duration,
      ease = DEFAULT_EASE,
      onStep,
      onComplete
    } = options;
    let raf = null;
    let cancelled = false;
    const start = performance.now();
    function step(now) {
      if (cancelled) return;
      const elapsed = now - start;
      const p = Math.min(1, elapsed / duration);
      const eased = ease(p);
      try {
        onStep(eased, p);
      } catch (e) {
        console.error("[PCCS.animate] onStep error", e);
      }
      if (p < 1) {
        raf = requestAnimationFrame(step);
      } else {
        if (onComplete) {
          try {
            onComplete();
          } catch (e) {
            console.error("[PCCS.animate] onComplete error", e);
          }
        }
      }
    }
    raf = requestAnimationFrame(step);
    return function cancel() {
      cancelled = true;
      if (raf) cancelAnimationFrame(raf);
    };
  }
  PCCS.animate = {
    run: animate,
    cubicOut: DEFAULT_EASE
  };

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

  // ../static/js/sun-curve.js
  var dom = PCCS.dom || {};
  var format = PCCS.format || {};
  var animate2 = PCCS.animate || {};
  var phaseInfo = { phase: "Day", day_start: "\u2014", evening_start: "\u2014", sunrise: "\u2014", sunset: "\u2014" };
  var currentCurveParams = null;
  var curveGeometryReady = false;
  var lastSunriseStr = null;
  var lastSunsetStr = null;
  var lastCurrentTimeStr = null;
  var displayT = 0.5;
  var displayIsDay = true;
  var sunAnimFrame = null;
  var hasSunPositioned = false;
  var SUN_ANIM_DURATION = 680;
  var curveAnimFrame = null;
  var SunCurve = {};
  SunCurve.updatePhaseInfo = function(data) {
    if (!data) return;
    phaseInfo.phase = data.phase || "Day";
    if (data.day_start) phaseInfo.day_start = data.day_start;
    if (data.evening_start) phaseInfo.evening_start = data.evening_start;
    if (data.sunrise) phaseInfo.sunrise = data.sunrise;
    if (data.sunset) phaseInfo.sunset = data.sunset;
    updatePhaseCurveLabels();
  };
  SunCurve.updateCurveGeometry = updateCurveGeometry;
  SunCurve.animateSunPosition = function(sunriseStr, sunsetStr, currentTimeStr) {
    animateSunPosition(sunriseStr, sunsetStr, currentTimeStr);
  };
  SunCurve.init = function() {
    if (typeof requestAnimationFrame === "function") {
      requestAnimationFrame(() => {
        updateCurveGeometry();
        requestAnimationFrame(() => updateCurveGeometry());
      });
    }
    let curveResizeTimer;
    window.addEventListener("resize", () => {
      clearTimeout(curveResizeTimer);
      curveResizeTimer = setTimeout(updateCurveGeometry, 140);
    });
  };
  PCCS.sunCurve = SunCurve;
  function updatePhaseCurveLabels() {
    const leftLabel = dom.$ ? dom.$("day-start-label") : document.getElementById("day-start-label");
    const rightLabel = dom.$ ? dom.$("evening-start-label") : document.getElementById("evening-start-label");
    if (!leftLabel || !rightLabel) return;
    const strip = format.stripLeadingZero || ((s) => s ? s.replace(/^0/, "") : s);
    const dayStart = strip(phaseInfo.day_start) || "\u2014";
    const eveStart = strip(phaseInfo.evening_start) || "\u2014";
    const sunriseStr = strip(phaseInfo.sunrise || phaseInfo.day_start) || "\u2014";
    const sunsetStr = strip(phaseInfo.sunset || phaseInfo.evening_start) || "\u2014";
    let leftText = dayStart;
    let rightText = eveStart;
    let leftColor = "#fcd34d";
    let rightColor = "#94a3b8";
    leftLabel.textContent = leftText;
    rightLabel.textContent = rightText;
    leftLabel.style.color = leftColor;
    rightLabel.style.color = rightColor;
  }
  function updateCurveGeometry() {
    const container = dom.$ ? dom.$("sun-curve") : document.getElementById("sun-curve");
    if (!container) return;
    const w = container.clientWidth;
    if (!w || w < 120) return;
    const h = 72;
    const archHeight = Math.min(52, Math.max(36, 28 + w * 0.045));
    let minInset = 38;
    const sunriseGroup = (dom.$ ? dom.$("sunrise") : document.getElementById("sunrise"))?.parentElement;
    if (sunriseGroup) {
      const groupWidth = sunriseGroup.getBoundingClientRect().width;
      minInset = 10 + groupWidth + 14;
    }
    const inset = Math.max(w * 0.085 + 8, minInset);
    const x0 = inset;
    const x1 = w / 2;
    const x2 = w - inset;
    const y0 = 52;
    const y1 = y0 - archHeight;
    const y2 = 52;
    const viewBoxW = Math.round(w);
    const targetParams = { x0, x1, x2, y0, y1, y2, viewBoxW, h };
    const dayPath = dom.$ ? dom.$("day-path") : document.getElementById("day-path");
    const nightPath = dom.$ ? dom.$("night-path") : document.getElementById("night-path");
    const svg = container.querySelector("svg");
    if (!curveGeometryReady || !currentCurveParams) {
      if (svg) svg.setAttribute("viewBox", `0 0 ${viewBoxW} ${h}`);
      const d = `M ${x0.toFixed(1)} ${y0} Q ${x1.toFixed(1)} ${y1.toFixed(1)} ${x2.toFixed(1)} ${y2}`;
      if (dayPath) dayPath.setAttribute("d", d);
      if (nightPath) nightPath.setAttribute("d", d);
      currentCurveParams = { x0, x1, x2, y0, y1, y2, viewBoxW, h };
      curveGeometryReady = true;
      if (lastSunriseStr && lastSunsetStr) {
        applySunPosition(displayT, displayIsDay);
      }
      return;
    }
    startCurveMorph(currentCurveParams, targetParams, svg, dayPath, nightPath);
  }
  function getPointOnCurve(t, params) {
    if (!params) return { x: 80, y: 38 };
    const { x0, y0, x1, y1, x2, y2 } = params;
    const mt = 1 - t;
    const x = mt * mt * x0 + 2 * mt * t * x1 + t * t * x2;
    const y = mt * mt * y0 + 2 * mt * t * y1 + t * t * y2;
    return { x, y };
  }
  function applySunPosition(t, isDay) {
    const sun = dom.$ ? dom.$("sun-position") : document.getElementById("sun-position");
    const glow = dom.$ ? dom.$("sun-glow") : document.getElementById("sun-glow");
    if (!sun || !glow || !currentCurveParams) return;
    const pt = getPointOnCurve(t, currentCurveParams);
    sun.setAttribute("cx", pt.x);
    sun.setAttribute("cy", pt.y);
    glow.setAttribute("cx", pt.x);
    glow.setAttribute("cy", pt.y);
    if (isDay) {
      sun.setAttribute("fill", "#fbbf24");
      glow.setAttribute("fill", "#fbbf24");
      glow.setAttribute("opacity", "0.28");
    } else {
      sun.setAttribute("fill", "#e2e8f0");
      glow.setAttribute("fill", "#e2e8f0");
      glow.setAttribute("opacity", "0.45");
    }
    displayT = t;
    displayIsDay = isDay;
  }
  function startSunAnimation(targetT, targetIsDay) {
    if (sunAnimFrame) {
      cancelAnimationFrame(sunAnimFrame);
      sunAnimFrame = null;
    }
    const sunEl = dom.$ ? dom.$("sun-position") : document.getElementById("sun-position");
    if (!sunEl || !currentCurveParams) {
      applySunPosition(targetT, targetIsDay);
      hasSunPositioned = true;
      return;
    }
    if (!hasSunPositioned) {
      applySunPosition(targetT, targetIsDay);
      hasSunPositioned = true;
      return;
    }
    const delta = Math.abs(targetT - displayT);
    const phaseChanged = targetIsDay !== displayIsDay;
    if (phaseChanged || delta < 0.012) {
      applySunPosition(targetT, targetIsDay);
      return;
    }
    const startT = displayT;
    const startTime = performance.now();
    const duration = SUN_ANIM_DURATION;
    function step(now) {
      const elapsed = now - startTime;
      let p = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      const current = startT + (targetT - startT) * eased;
      applySunPosition(current, targetIsDay);
      if (p < 1) {
        sunAnimFrame = requestAnimationFrame(step);
      } else {
        sunAnimFrame = null;
        applySunPosition(targetT, targetIsDay);
      }
    }
    sunAnimFrame = requestAnimationFrame(step);
  }
  function applyCurveParams(p, svgEl, dayEl, nightEl) {
    if (svgEl) {
      svgEl.setAttribute("viewBox", `0 0 ${p.viewBoxW} ${p.h || 72}`);
    }
    const d = `M ${p.x0.toFixed(1)} ${p.y0} Q ${p.x1.toFixed(1)} ${p.y1.toFixed(1)} ${p.x2.toFixed(1)} ${p.y2}`;
    if (dayEl) dayEl.setAttribute("d", d);
    if (nightEl) nightEl.setAttribute("d", d);
  }
  function startCurveMorph(from, to, svgEl, dayEl, nightEl) {
    if (curveAnimFrame) {
      cancelAnimationFrame(curveAnimFrame);
      curveAnimFrame = null;
    }
    if (sunAnimFrame) {
      cancelAnimationFrame(sunAnimFrame);
      sunAnimFrame = null;
    }
    if (!from || typeof from.x0 !== "number") {
      currentCurveParams = { x0: to.x0, x1: to.x1, x2: to.x2, y0: to.y0, y1: to.y1, y2: to.y2, viewBoxW: to.viewBoxW, h: to.h };
      applyCurveParams(to, svgEl, dayEl, nightEl);
      if (lastSunriseStr && lastSunsetStr) {
        applySunPosition(displayT, displayIsDay);
      }
      return;
    }
    const startTime = performance.now();
    const duration = 310;
    function step(now) {
      const elapsed = now - startTime;
      let pr = Math.min(elapsed / duration, 1);
      const e = 1 - Math.pow(1 - pr, 3);
      const ix0 = from.x0 + (to.x0 - from.x0) * e;
      const ix1 = from.x1 + (to.x1 - from.x1) * e;
      const ix2 = from.x2 + (to.x2 - from.x2) * e;
      const iy0 = from.y0 + (to.y0 - from.y0) * e;
      const iy1 = from.y1 + (to.y1 - from.y1) * e;
      const iy2 = from.y2 + (to.y2 - from.y2) * e;
      const ivw = Math.round(from.viewBoxW != null ? from.viewBoxW + (to.viewBoxW - from.viewBoxW) * e : to.viewBoxW);
      const liveParams = { x0: ix0, x1: ix1, x2: ix2, y0: iy0, y1: iy1, y2: iy2, viewBoxW: ivw, h: 72 };
      applyCurveParams(liveParams, svgEl, dayEl, nightEl);
      currentCurveParams = liveParams;
      if (lastSunriseStr && lastSunsetStr) {
        applySunPosition(displayT, displayIsDay);
      }
      if (pr < 1) {
        curveAnimFrame = requestAnimationFrame(step);
      } else {
        curveAnimFrame = null;
        currentCurveParams = { x0: to.x0, x1: to.x1, x2: to.x2, y0: to.y0, y1: to.y1, y2: to.y2, viewBoxW: to.viewBoxW, h: to.h };
        applyCurveParams(to, svgEl, dayEl, nightEl);
        if (lastSunriseStr && lastSunsetStr) {
          applySunPosition(displayT, displayIsDay);
        }
      }
    }
    curveAnimFrame = requestAnimationFrame(step);
  }
  function animateSunPosition(sunriseStr, sunsetStr, currentTimeStr) {
    const sun = dom.$ ? dom.$("sun-position") : document.getElementById("sun-position");
    const glow = dom.$ ? dom.$("sun-glow") : document.getElementById("sun-glow");
    const dayPath = dom.$ ? dom.$("day-path") : document.getElementById("day-path");
    const nightPath = dom.$ ? dom.$("night-path") : document.getElementById("night-path");
    if (!sun || !glow || !sunriseStr || !sunsetStr) return;
    lastSunriseStr = sunriseStr;
    lastSunsetStr = sunsetStr;
    lastCurrentTimeStr = currentTimeStr;
    if (!curveGeometryReady || !currentCurveParams) {
      sun.setAttribute("cx", 80);
      sun.setAttribute("cy", 38);
      glow.setAttribute("cx", 80);
      glow.setAttribute("cy", 38);
      displayT = 0.5;
      return;
    }
    const parse = format.parseTimeToMinutes || function(str) {
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
    };
    const sunriseMin = parse(sunriseStr);
    const sunsetMin = parse(sunsetStr);
    let currentMin = parse(currentTimeStr);
    if (sunriseMin === null || sunsetMin === null) return;
    if (currentMin === null) currentMin = 12 * 60;
    const DAY_MINUTES = 1440;
    currentMin = (currentMin % DAY_MINUTES + DAY_MINUTES) % DAY_MINUTES;
    let targetT = 0.5;
    let targetIsDay = true;
    if (currentMin >= sunriseMin && currentMin <= sunsetMin) {
      targetIsDay = true;
      const dayLen = sunsetMin - sunriseMin;
      targetT = dayLen > 0 ? (currentMin - sunriseMin) / dayLen : 0.5;
    } else {
      targetIsDay = false;
      let nightProgress = 0;
      if (currentMin < sunriseMin) {
        const prevSunset = sunsetMin - DAY_MINUTES;
        const nightLen = sunriseMin - prevSunset;
        nightProgress = nightLen > 0 ? (currentMin - prevSunset) / nightLen : 0;
      } else {
        const nextSunrise = sunriseMin + DAY_MINUTES;
        const nightLen = nextSunrise - sunsetMin;
        nightProgress = nightLen > 0 ? (currentMin - sunsetMin) / nightLen : 0;
      }
      targetT = nightProgress;
    }
    targetT = Math.max(0, Math.min(1, targetT));
    startSunAnimation(targetT, targetIsDay);
    if (dayPath && nightPath) {
      dayPath.style.transition = "stroke-opacity 1000ms ease-in-out";
      nightPath.style.transition = "stroke-opacity 1000ms ease-in-out";
      if (targetIsDay) {
        dayPath.setAttribute("stroke-opacity", "0.85");
        nightPath.setAttribute("stroke-opacity", "0.1");
      } else {
        dayPath.setAttribute("stroke-opacity", "0.1");
        nightPath.setAttribute("stroke-opacity", "0.6");
      }
    }
  }

  // ../static/js/offline.js
  var offlineTimeout = null;
  function showOfflineBanner() {
    if (offlineTimeout) clearTimeout(offlineTimeout);
    offlineTimeout = setTimeout(() => {
      const overlay = document.getElementById("offline-overlay");
      if (overlay) {
        overlay.classList.remove("hidden");
        overlay.style.pointerEvents = "auto";
      }
      const mainContent = document.querySelector(".flex-1");
      if (mainContent) mainContent.style.pointerEvents = "none";
    }, 800);
  }
  function hideOfflineBanner() {
    if (offlineTimeout) clearTimeout(offlineTimeout);
    offlineTimeout = null;
    const overlay = document.getElementById("offline-overlay");
    if (overlay) overlay.classList.add("hidden");
    const mainContent = document.querySelector(".flex-1");
    if (mainContent) mainContent.style.pointerEvents = "auto";
  }
  function register(socket2) {
    socket2.on("disconnect", showOfflineBanner);
    socket2.on("connect_error", showOfflineBanner);
  }
  PCCS.offline = { show: showOfflineBanner, hide: hideOfflineBanner, register };

  // ../static/js/version.js
  var S = PCCS.state;
  async function loadVersion() {
    try {
      const res = await fetch("/api/version");
      const data = await res.json();
      const versionEl = document.getElementById("footer-version");
      if (versionEl) {
        versionEl.textContent = `v${data.version || "?.?.?"}`;
      }
    } catch (e) {
      console.warn("Could not load version", e);
      document.getElementById("footer-version").textContent = "v?.?.?";
    }
  }
  PCCS.version = { loadVersion };

  // ../static/js/lighting-controller.js
  var S2 = PCCS.state;
  function emitLightChange(payload) {
    const socket2 = getSocket();
    if (socket2?.connected) {
      socket2.emit("light_change", payload);
    } else {
      console.warn("[PCCS] light_change socket unavailable \u2014 using HTTP fallback", payload);
    }
    fetch("/api/light", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      keepalive: true
    }).then((r) => r.ok ? r.json() : null).then((data) => {
      if (data?.state) PCCS.lighting.onStateUpdate(data.state);
    }).catch((err) => console.warn("[PCCS] light_change HTTP failed", err));
    return true;
  }
  function emitRelayChange(name, on) {
    const socket2 = getSocket();
    if (!socket2?.connected) {
      console.warn("[PCCS] relay_change skipped \u2014 socket unavailable", name);
      return false;
    }
    socket2.emit("relay_change", { name, on });
    return true;
  }
  function getCurrentColumns() {
    const container = document.getElementById("lighting-controls");
    if (!container) return 1;
    const style = window.getComputedStyle(container);
    const gridTemplate = style.gridTemplateColumns || style.getPropertyValue("grid-template-columns");
    if (gridTemplate.includes("repeat(1") || gridTemplate.split(" ").length === 1) return 1;
    if (gridTemplate.includes("repeat(2") || gridTemplate.split(" ").length === 2) return 2;
    if (gridTemplate.includes("repeat(3") || gridTemplate.split(" ").length === 3) return 3;
    const children = container.children.length;
    if (children > 0) {
      const firstChild = container.children[0];
      const containerRect = container.getBoundingClientRect();
      const childRect = firstChild.getBoundingClientRect();
      if (containerRect.width > 0) {
        const approxCols = Math.round(containerRect.width / (childRect.width + 16));
        return Math.max(1, Math.min(3, approxCols));
      }
    }
    return 1;
  }
  function renderLightingControls() {
    const container = document.getElementById("lighting-controls");
    if (!container) {
      return false;
    }
    const currentHash = JSON.stringify(S2.lightsConfig.map((l) => l.name + l.type));
    if (currentHash === S2.lastRenderConfigHash && S2.lightsConfig.length > 0) {
      updateUIFromState();
      return true;
    }
    S2.lastRenderConfigHash = currentHash;
    container.innerHTML = "";
    const columns = getCurrentColumns();
    let i = 0;
    while (i < S2.lightsConfig.length) {
      const light = S2.lightsConfig[i];
      const canPair = light.type === "relay" && i + 1 < S2.lightsConfig.length && S2.lightsConfig[i + 1].type === "relay";
      let shouldPair = canPair;
      if (canPair) {
        if (columns === 1) {
          shouldPair = false;
        } else if (columns === 2) {
          const isLastPair = i + 2 === S2.lightsConfig.length;
          shouldPair = !isLastPair;
        }
      }
      if (shouldPair) {
        const relay1 = light;
        const relay2 = S2.lightsConfig[i + 1];
        const html2 = `
					<div class="slider-card glass paired-relay-card">
						<div class="paired-relay-inner">
							<!-- First relay -->
							<div class="paired-relay-row">
								<div class="slider-card-left">
									<div class="slider-card-title">
										<i class="fa-solid ${relay1.icon}"></i>
										<span class="slider-label">${relay1.label}</span>
									</div>
								</div>
								<div class="slider-card-right">
									<div class="value-display" id="val-${relay1.name}">${S2.currentState[relay1.name] ? "On" : "Off"}</div>
									<div class="relay-toggle ${S2.currentState[relay1.name] ? "on" : ""}" 
										 data-name="${relay1.name}" 
										 data-state="${S2.currentState[relay1.name] ? "on" : "off"}">
										<div class="relay-knob"></div>
									</div>
								</div>
							</div>

							<div class="paired-relay-divider"></div>

							<!-- Second relay -->
							<div class="paired-relay-row">
								<div class="slider-card-left">
									<div class="slider-card-title">
										<i class="fa-solid ${relay2.icon}"></i>
										<span class="slider-label">${relay2.label}</span>
									</div>
								</div>
								<div class="slider-card-right">
									<div class="value-display" id="val-${relay2.name}">${S2.currentState[relay2.name] ? "On" : "Off"}</div>
									<div class="relay-toggle ${S2.currentState[relay2.name] ? "on" : ""}" 
										 data-name="${relay2.name}" 
										 data-state="${S2.currentState[relay2.name] ? "on" : "off"}">
										<div class="relay-knob"></div>
									</div>
								</div>
							</div>
						</div>
					</div>`;
        container.innerHTML += html2;
        i += 2;
        continue;
      }
      const isRelay = light.type === "relay";
      const currentVal = S2.currentState[light.name] || 0;
      const isOn = isRelay ? !!currentVal : false;
      let html = `
				<div class="slider-card glass">
					<div class="slider-card-header">
						<div class="slider-card-left">
							<div class="slider-card-title">
								<i class="fa-solid ${light.icon}"></i>
								<span class="slider-label">${light.label}</span>
							</div>
						</div>
						<div class="slider-card-right">
							<div class="value-display" id="val-${light.name}">
								${isRelay ? isOn ? "On" : "Off" : "0%"}
							</div>`;
      if (isRelay) {
        html += `
							<div class="relay-toggle ${isOn ? "on" : ""}" 
								 data-name="${light.name}" 
								 data-state="${isOn ? "on" : "off"}">
								<div class="relay-knob"></div>
							</div>`;
      } else {
        const extraClass = light.has_mode ? "colour-toggle" : "";
        html += `
							<div class="toggle-pill ${extraClass}" data-name="${light.name}" data-state="off">
								<div class="toggle-knob"></div>
							</div>`;
      }
      html += `</div></div>`;
      if (!isRelay) {
        html += `
					<div class="slider-wrapper" data-name="${light.name}" data-value="0" data-last-brightness="100">
						<div class="slider-inner">
							<div class="slider-track"></div>
							<div class="slider-fill" style="width: 0%"></div>
							<div class="slider-thumb" style="left: 0%"></div>
						</div>
					</div>`;
      }
      html += `</div>`;
      container.innerHTML += html;
      i++;
    }
    initUnifiedToggleListeners();
    initSliders();
    setTimeout(updateUIFromState, 100);
    return true;
  }
  function toggleControl(el) {
    const name = el.dataset.name;
    const light = S2.lightsConfig.find((l) => l.name === name);
    if (!light) return;
    if (name === "rooftop_tent" && isRooftopTentPhysicallyClosed()) {
      return;
    }
    S2.userJustSet.add(name);
    setTimeout(() => S2.userJustSet.delete(name), S2.JUST_SET_DURATION);
    if (light.type === "relay") {
      const isCurrentlyOn = el.dataset.state === "on";
      const newState = !isCurrentlyOn;
      updateLightUI(name, newState ? 1 : 0);
      emitRelayChange(name, newState);
      setTimeout(() => updateLightUI(name, newState ? 1 : 0), 50);
      return;
    }
    if (light.has_mode) {
      const currentMode = S2.currentModes[name] || "white";
      const newMode = currentMode === "white" ? "red" : "white";
      S2.currentModes[name] = newMode;
      const currentBrightness2 = S2.currentState[name] || 0;
      updateLightUI(name, currentBrightness2);
      emitLightChange({
        name,
        brightness: currentBrightness2,
        mode: newMode
      });
      return;
    }
    const wrapper = document.querySelector(`.slider-wrapper[data-name="${name}"]`);
    const currentBrightness = wrapper ? parseInt(wrapper.dataset.value) || 0 : 0;
    const isOn = el.dataset.state === "on";
    const newBrightness = isOn ? 0 : parseInt(wrapper?.dataset.lastBrightness) || 100;
    updateLightUI(name, newBrightness);
    S2.currentState[name] = newBrightness;
    emitLightChange({ name, brightness: newBrightness });
  }
  function initUnifiedToggleListeners() {
    const container = document.getElementById("lighting-controls");
    container.removeEventListener("click", handleLightingClick);
    function handleLightingClick(e) {
      const toggle = e.target.closest(".relay-toggle, .toggle-pill");
      if (!toggle) return;
      if (toggle.dataset.justClicked === "true") return;
      toggle.dataset.justClicked = "true";
      setTimeout(() => delete toggle.dataset.justClicked, 350);
      toggleControl(toggle);
    }
    container.addEventListener("click", handleLightingClick);
  }
  function updateLightUI(name, value) {
    const light = S2.lightsConfig.find((l) => l.name === name);
    if (!light) return;
    const valueEl = document.getElementById(`val-${name}`);
    const pills = document.querySelectorAll(
      `.toggle-pill[data-name="${name}"], .relay-toggle[data-name="${name}"]`
    );
    if (light.type === "relay") {
      const isOn = !!value;
      pills.forEach((toggle) => {
        toggle.classList.toggle("on", isOn);
        toggle.dataset.state = isOn ? "on" : "off";
      });
      if (valueEl) {
        valueEl.textContent = isOn ? "On" : "Off";
      }
      return;
    }
    const wrapper = document.querySelector(`.slider-wrapper[data-name="${name}"]`);
    const fill = wrapper ? wrapper.querySelector(".slider-fill") : null;
    const thumb = wrapper ? wrapper.querySelector(".slider-thumb") : null;
    const brightness = Math.max(0, Math.min(100, value || 0));
    const card = wrapper ? wrapper.closest(".slider-card") : null;
    if (wrapper) {
      wrapper.dataset.value = brightness;
      if (brightness > 0) wrapper.dataset.lastBrightness = brightness;
      if (fill) fill.style.width = `${brightness}%`;
      if (thumb) thumb.style.left = `${brightness}%`;
      if (valueEl) valueEl.textContent = `${brightness}%`;
    }
    const isBugMode = light.has_mode && (S2.currentModes[name] || "white") === "red";
    const pillOn = light.has_mode ? isBugMode : brightness > 0;
    pills.forEach((pill) => {
      pill.classList.toggle("on", pillOn);
      pill.classList.toggle("bug-mode", isBugMode);
      pill.dataset.state = pillOn ? "on" : "off";
    });
    if (card) card.classList.toggle("bug-mode", isBugMode);
    if (wrapper) {
      wrapper.classList.toggle("bug-mode", isBugMode);
      if (fill) fill.classList.toggle("bug-mode", isBugMode);
      if (thumb) thumb.classList.toggle("bug-mode", isBugMode);
    }
  }
  function cancelSceneAnimations() {
    Object.values(S2.sceneAnimationCancels).forEach((cancel) => {
      if (typeof cancel === "function") cancel();
    });
    S2.sceneAnimationCancels = {};
  }
  function setSliderMotion(wrapper, enabled) {
    if (!wrapper) return;
    const fill = wrapper.querySelector(".slider-fill");
    const thumb = wrapper.querySelector(".slider-thumb");
    const transition = enabled ? "" : "none";
    if (fill) fill.style.transition = transition;
    if (thumb) thumb.style.transition = transition;
  }
  function applyStateToUI(newState, { animate: animate3 = false, rampMs = S2.SCENE_RAMP_MS } = {}) {
    const protectedLights = /* @__PURE__ */ new Set([...S2.currentlyDragging]);
    if (!animate3) {
      S2.userJustSet.forEach((name) => protectedLights.add(name));
    }
    S2.lightsConfig.forEach((light) => {
      const modeKey = `${light.name}_mode`;
      if (light.has_mode && newState[modeKey] && !protectedLights.has(light.name)) {
        S2.currentModes[light.name] = newState[modeKey];
      }
    });
    if (!animate3) {
      Object.keys(newState).forEach((k) => {
        if (k.endsWith("_mode")) return;
        if (!protectedLights.has(k)) S2.currentState[k] = newState[k];
      });
      updateUIFromState();
      return;
    }
    cancelSceneAnimations();
    S2.lightsConfig.forEach((light) => {
      if (protectedLights.has(light.name)) return;
      const target = newState[light.name];
      if (target === void 0) return;
      if (light.type === "relay") {
        S2.currentState[light.name] = !!target;
        updateLightUI(light.name, !!target);
        return;
      }
      const wrapper = document.querySelector(`.slider-wrapper[data-name="${light.name}"]`);
      const start = parseInt(wrapper?.dataset.value, 10);
      const from = Number.isFinite(start) ? start : S2.currentState[light.name] || 0;
      const end = Math.max(0, Math.min(100, target || 0));
      S2.currentState[light.name] = end;
      if (from === end) {
        updateLightUI(light.name, end);
        return;
      }
      setSliderMotion(wrapper, false);
      S2.sceneAnimationCancels[light.name] = PCCS.animate.run({
        duration: rampMs,
        onStep: (t) => {
          const v = Math.round(from + (end - from) * t);
          updateLightUI(light.name, v);
        },
        onComplete: () => {
          updateLightUI(light.name, end);
          setSliderMotion(wrapper, true);
          delete S2.sceneAnimationCancels[light.name];
        }
      });
    });
    updateRooftopTentControls();
  }
  function updateUIFromState() {
    S2.lightsConfig.forEach((light) => {
      if (S2.currentlyDragging.has(light.name) || S2.userJustSet.has(light.name)) {
        return;
      }
      const val = S2.currentState[light.name];
      if (val === void 0) return;
      updateLightUI(light.name, light.type === "relay" ? !!val : val || 0);
    });
    updateRooftopTentControls();
  }
  var lastTouchPointerUp = 0;
  function makeDraggable(wrapper) {
    if (wrapper.dataset.pccsSliderBound === "1") return;
    wrapper.dataset.pccsSliderBound = "1";
    const inner = wrapper.querySelector(".slider-inner");
    const fill = wrapper.querySelector(".slider-fill");
    const thumb = wrapper.querySelector(".slider-thumb");
    const name = wrapper.dataset.name;
    const valueEl = document.getElementById(`val-${name}`);
    let isDragging = false;
    let activePointerId = null;
    let startX = 0;
    let startY = 0;
    let valueAtPointerStart = 0;
    function updatePosition(clientX) {
      const rect = inner.getBoundingClientRect();
      const percent = Math.max(0, Math.min(
        100,
        Math.round((clientX - rect.left) / rect.width * 100)
      ));
      wrapper.dataset.value = percent;
      if (fill) fill.style.width = `${percent}%`;
      if (thumb) thumb.style.left = `${percent}%`;
      if (valueEl) valueEl.textContent = `${percent}%`;
    }
    function startDrag() {
      if (isDragging) return;
      isDragging = true;
      wrapper.classList.add("dragging");
      S2.currentlyDragging.add(name);
      S2.userJustSet.delete(name);
      if (fill) fill.style.transition = "none";
      if (thumb) thumb.style.transition = "none";
    }
    function commitDrag(force) {
      if (!force && !isDragging) return;
      const final = parseInt(wrapper.dataset.value) || 0;
      isDragging = false;
      activePointerId = null;
      wrapper.classList.remove("dragging");
      S2.currentlyDragging.delete(name);
      S2.userJustSet.add(name);
      setTimeout(() => S2.userJustSet.delete(name), S2.JUST_SET_DURATION);
      S2.currentState[name] = final;
      updateLightUI(name, final);
      const light = S2.lightsConfig.find((l) => l.name === name);
      const payload = { name, brightness: final };
      if (light?.has_mode && S2.currentModes[name]) {
        payload.mode = S2.currentModes[name];
      }
      emitLightChange(payload);
    }
    wrapper.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      if (name === "rooftop_tent" && isRooftopTentPhysicallyClosed()) return;
      if (e.pointerType === "mouse" && Date.now() - lastTouchPointerUp < 600) return;
      activePointerId = e.pointerId;
      startX = e.clientX;
      startY = e.clientY;
      valueAtPointerStart = parseInt(wrapper.dataset.value) || 0;
      isDragging = false;
      if (e.pointerType === "mouse") {
        e.preventDefault();
        wrapper.setPointerCapture(e.pointerId);
        startDrag();
        updatePosition(e.clientX);
      }
    });
    wrapper.addEventListener("pointermove", (e) => {
      if (e.pointerId !== activePointerId) return;
      if (name === "rooftop_tent" && isRooftopTentPhysicallyClosed()) return;
      const deltaX = Math.abs(e.clientX - startX);
      const deltaY = Math.abs(e.clientY - startY);
      if (!isDragging) {
        if (e.pointerType === "mouse") {
          startDrag();
        } else if (deltaX > 10 && deltaX > deltaY * 1.5) {
          e.preventDefault();
          wrapper.setPointerCapture(e.pointerId);
          startDrag();
        } else {
          return;
        }
      }
      e.preventDefault();
      updatePosition(e.clientX);
    });
    wrapper.addEventListener("pointerup", (e) => {
      if (e.pointerId !== activePointerId) return;
      if (e.pointerType === "touch") lastTouchPointerUp = Date.now();
      try {
        wrapper.releasePointerCapture(e.pointerId);
      } catch (_) {
      }
      const final = parseInt(wrapper.dataset.value) || 0;
      const changed = isDragging || final !== valueAtPointerStart;
      if (changed) commitDrag(true);
      else {
        isDragging = false;
        activePointerId = null;
      }
    });
    wrapper.addEventListener("pointercancel", (e) => {
      if (e.pointerId !== activePointerId) return;
      if (isDragging) commitDrag(true);
      else {
        isDragging = false;
        activePointerId = null;
      }
    });
  }
  function initSliders() {
    document.querySelectorAll('.slider-wrapper:not([data-pccs-slider-bound="1"])').forEach(makeDraggable);
  }
  function updateRooftopTentControls() {
    const tentCard = document.querySelector('.slider-wrapper[data-name="rooftop_tent"]')?.closest(".slider-card");
    if (!tentCard) return;
    const isClosed = S2.currentReeds.rooftop_tent !== false;
    if (isClosed) {
      tentCard.classList.add("rooftop-disabled");
      updateLightUI("rooftop_tent", 0);
    } else {
      tentCard.classList.remove("rooftop-disabled");
    }
  }
  function isRooftopTentPhysicallyClosed() {
    return S2.currentReeds.rooftop_tent !== false;
  }
  PCCS.lighting = {
    getCurrentColumns,
    renderLightingControls,
    updateUIFromState,
    updateRooftopTentControls,
    isRooftopTentPhysicallyClosed,
    onLightsConfig(config) {
      S2.lightsConfig = config || [];
      S2.lightsConfig.forEach((light) => {
        const mode = S2.currentState[`${light.name}_mode`];
        if (light.has_mode && mode) S2.currentModes[light.name] = mode;
      });
      if (!renderLightingControls()) {
        const renderWhenReady = () => {
          if (renderLightingControls()) {
            document.removeEventListener("DOMContentLoaded", renderWhenReady);
          }
        };
        if (document.readyState === "loading") {
          document.addEventListener("DOMContentLoaded", renderWhenReady);
        } else {
          requestAnimationFrame(renderWhenReady);
        }
      }
      const socket2 = getSocket();
      if (socket2?.connected) socket2.emit("get_reeds");
      if (Object.keys(S2.currentState).length > 0) updateUIFromState();
    },
    onStateUpdate(newState) {
      const animate3 = S2.sceneActivating;
      S2.sceneActivating = false;
      applyStateToUI(newState, { animate: animate3, rampMs: S2.SCENE_RAMP_MS });
    },
    onReedUpdate(payload) {
      S2.currentReeds = payload.states || {};
      updateRooftopTentControls();
    },
    initResize() {
      let lastColumnCount = getCurrentColumns();
      function handleResizeForLighting() {
        const newCols = getCurrentColumns();
        if (newCols !== lastColumnCount && S2.lightsConfig.length > 0) {
          lastColumnCount = newCols;
          renderLightingControls();
        }
      }
      window.addEventListener("resize", handleResizeForLighting);
      setTimeout(() => {
        lastColumnCount = getCurrentColumns();
      }, 300);
    }
  };

  // ../static/js/tile-updaters.js
  var S3 = PCCS.state;
  function updateGPS(data) {
    if (!data) return;
    S3.gpsStatusReceived = true;
    const fixQuality = parseInt(data.fix_quality || 0);
    S3.hasValidGPSFix = fixQuality >= 1;
    if (data.satellites !== void 0) {
      document.getElementById("satellites").textContent = `${data.satellites || 0} / ${fixQuality}`;
    }
    const locationEl = document.getElementById("location");
    if (locationEl) {
      const suburb = (data.suburb || "").trim();
      locationEl.textContent = suburb || (S3.hasValidGPSFix ? "Acquiring position..." : "No GPS Fix");
    }
    updateTimeAndSun(data);
    if (window.PCCS && window.PCCS.sunCurve) {
      window.PCCS.sunCurve.updateCurveGeometry();
    }
    if (S3.hasValidGPSFix && data.latitude && data.longitude) {
      const now = Date.now();
      if (now - S3.lastWeatherUpdate > S3.WEATHER_INTERVAL_MS) {
        S3.lastWeatherUpdate = now;
        fetchWeatherForecast(data.latitude, data.longitude);
      }
    }
    document.getElementById("tile-date").classList.toggle("text-amber-400", !S3.hasValidGPSFix);
    document.getElementById("tile-time").classList.toggle("text-amber-400", !S3.hasValidGPSFix);
  }
  function stripLeadingZero2(timeStr) {
    return timeStr ? timeStr.replace(/^0(\d):/, "$1:") : "";
  }
  function updateClock() {
    if (S3.gpsStatusReceived && S3.hasValidGPSFix) return;
    const now = /* @__PURE__ */ new Date();
    const dayName = now.toLocaleDateString("en-AU", { weekday: "short" });
    const day = now.getDate();
    const month = now.toLocaleDateString("en-AU", { month: "short" });
    const showWarning = S3.gpsStatusReceived && !S3.hasValidGPSFix;
    const dateSuffix = showWarning ? " *" : "";
    const timeSuffix = showWarning ? " *" : "";
    document.getElementById("tile-date").textContent = `${dayName} ${day} ${month}${dateSuffix}`;
    let hours = now.getHours();
    let minutes = now.getMinutes().toString().padStart(2, "0");
    const ampm = hours >= 12 ? "PM" : "AM";
    hours = hours % 12 || 12;
    document.getElementById("tile-time").textContent = `${hours}:${minutes} ${ampm}${timeSuffix}`;
  }
  function updateSensors(data) {
    if (!data) return;
    if (data.water_percent !== void 0) {
      const percent = Math.max(0, Math.min(100, Math.round(data.water_percent)));
      const levelEl = document.getElementById("water-level");
      if (levelEl) levelEl.textContent = `${percent}%`;
      const fill = document.getElementById("water-fill");
      if (fill) {
        const currentWidth = parseFloat(fill.style.width) || 0;
        if (Math.abs(currentWidth - percent) > 1) {
          fill.style.transition = "none";
          fill.style.width = `${currentWidth}%`;
          void fill.offsetWidth;
          fill.style.transition = "width 700ms cubic-bezier(0.34, 1.56, 0.64, 1)";
        } else {
          fill.style.transition = "width 400ms ease-out";
        }
        fill.style.width = `${percent}%`;
        if (percent < 25) {
          fill.classList.add("low");
        } else {
          fill.classList.remove("low");
        }
      }
      const extraEl = document.getElementById("water-extra");
      if (extraEl && data.water_litres !== void 0) {
        extraEl.textContent = `Fresh: ${Math.round(data.water_litres)} L`;
      }
    }
    if (data.temp_c !== void 0 && data.temp_c !== null) {
      const tempEl = document.getElementById("outside-temp");
      if (tempEl) {
        tempEl.textContent = `${Math.round(data.temp_c)}\xB0C`;
      }
    }
    if (data.fridge_temp_c !== void 0 && data.fridge_temp_c !== null) {
      const fridgeEl = document.getElementById("fridge-temp");
      if (fridgeEl) {
        fridgeEl.textContent = `${Math.round(data.fridge_temp_c)}\xB0C`;
      }
    } else {
      const fridgeEl = document.getElementById("fridge-temp");
      if (fridgeEl) {
        fridgeEl.textContent = "\u2014\xB0C";
      }
    }
  }
  function updateTimeAndSun(data) {
    if (!data) return;
    if (data.date) {
      let dayName = "", day = "", month = "";
      const dateStr = data.date.trim();
      let m = dateStr.match(/^([A-Za-z]+),\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$/);
      if (m) {
        dayName = m[1].slice(0, 3);
        day = m[2];
        month = m[3].slice(0, 3);
      } else {
        const dateObj = new Date(dateStr);
        if (!isNaN(dateObj.getTime())) {
          dayName = dateObj.toLocaleDateString("en-AU", { weekday: "short" });
          day = dateObj.getDate();
          month = dateObj.toLocaleDateString("en-AU", { month: "short" });
        }
      }
      if (dayName && day && month) {
        document.getElementById("tile-date").textContent = `${dayName} ${day} ${month}`;
      }
    }
    if (data.local_time) {
      const mins = parseTimeToMinutes(data.local_time);
      if (mins != null) {
        let hours = Math.floor(mins / 60);
        const minutes = (mins % 60).toString().padStart(2, "0");
        const ampm = hours >= 12 ? "PM" : "AM";
        hours = hours % 12 || 12;
        document.getElementById("tile-time").textContent = `${hours}:${minutes} ${ampm}`;
      }
    }
    if (data.sunrise) {
      const sunriseTime = stripLeadingZero2(data.sunrise);
      const sunriseEl = document.getElementById("sunrise");
      if (sunriseEl) sunriseEl.textContent = sunriseTime;
    }
    if (data.sunset) {
      const sunsetTime = stripLeadingZero2(data.sunset);
      const sunsetEl = document.getElementById("sunset");
      if (sunsetEl) sunsetEl.textContent = sunsetTime;
    }
    if (window.PCCS && window.PCCS.sunCurve) {
      window.PCCS.sunCurve.updateCurveGeometry();
      window.PCCS.sunCurve.animateSunPosition(data.sunrise, data.sunset, data.local_time);
    }
  }
  function updatePhaseInfo(data) {
    if (window.PCCS && window.PCCS.sunCurve) {
      window.PCCS.sunCurve.updatePhaseInfo(data);
    }
  }
  async function fetchWeatherForecast(lat, lon) {
    try {
      const url = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&daily=temperature_2m_max,temperature_2m_min,weathercode&current_weather=true&timezone=auto`;
      const res = await fetch(url, { cache: "no-store" });
      const data = await res.json();
      if (data.daily) {
        const max = Math.round(data.daily.temperature_2m_max[0]);
        const min = Math.round(data.daily.temperature_2m_min[0]);
        document.getElementById("temp-range").textContent = `${min}\xB0 / ${max}\xB0`;
      }
      const weatherIcon = document.getElementById("weather-icon");
      if (data.current_weather && weatherIcon) {
        const code = data.current_weather.weathercode;
        const isDay = data.current_weather.is_day === 1;
        weatherIcon.className = `fa-solid ${getWeatherIcon(code, isDay)} text-2xl accent-sky`;
      }
    } catch (e) {
      console.warn("Weather fetch failed:", e);
    }
  }
  function getWeatherIcon(code, isDay) {
    const icons = {
      0: isDay ? "fa-sun" : "fa-moon",
      1: isDay ? "fa-sun" : "fa-moon",
      2: "fa-cloud",
      3: "fa-cloud",
      45: "fa-smog",
      48: "fa-smog",
      51: "fa-cloud-rain",
      53: "fa-cloud-rain",
      55: "fa-cloud-rain",
      61: "fa-cloud-showers-heavy",
      63: "fa-cloud-showers-heavy",
      65: "fa-cloud-showers-heavy",
      71: "fa-snowflake",
      73: "fa-snowflake",
      75: "fa-snowflake",
      80: "fa-cloud-showers-heavy",
      81: "fa-cloud-showers-heavy",
      82: "fa-cloud-showers-heavy",
      95: "fa-bolt",
      96: "fa-bolt",
      99: "fa-bolt"
    };
    return icons[code] || "fa-cloud";
  }
  function updateNetworkTile(data) {
    if (!data) return;
    const inet = data.internet || {};
    const right = data.right || {};
    const statusEl = document.getElementById("net-inet-status");
    const iconEl = document.getElementById("net-inet-icon");
    const ifaceEl = document.getElementById("net-iface");
    const rxEl = document.getElementById("net-rx");
    const txEl = document.getElementById("net-tx");
    const linkEl = document.getElementById("net-link-speed");
    const pingEl = document.getElementById("net-ping");
    const signalEl = document.getElementById("net-signal");
    const connected = !!inet.connected;
    const statusText = connected ? "Online" : "Offline";
    const statusColor = connected ? "text-emerald-400" : "text-red-400";
    const icon = connected ? "fa-globe" : "fa-exclamation-triangle";
    if (statusEl) {
      statusEl.textContent = statusText;
      statusEl.className = `tile-value font-medium leading-none ${statusColor}`;
    }
    if (iconEl) {
      iconEl.className = `fa-solid ${icon} fa-fw w-4 ${statusColor}`;
    }
    if (ifaceEl) {
      ifaceEl.textContent = inet.friendly_name || "\u2014";
    }
    if (signalEl) {
      signalEl.textContent = inet.signal_quality || "\u2014";
    }
    if (rxEl) rxEl.textContent = inet.rx_kbps != null ? `${inet.rx_kbps}` : "\u2014";
    if (txEl) txEl.textContent = inet.tx_kbps != null ? `${inet.tx_kbps}` : "\u2014";
    if (linkEl) {
      linkEl.textContent = inet.link_speed_mbps ? `${inet.link_speed_mbps}M` : "";
    }
    if (pingEl) {
      const ms = inet.ping_ms;
      const pstatus = inet.ping_status || "unknown";
      let colorClass = "opacity-60";
      if (pstatus === "good") colorClass = "text-emerald-400";
      else if (pstatus === "slow") colorClass = "text-amber-400";
      else if (pstatus === "fail") colorClass = "text-red-400";
      if (ms != null && ms !== void 0) {
        pingEl.innerHTML = `<span class="${colorClass}">${ms}ms</span>`;
      } else {
        pingEl.innerHTML = `<span class="opacity-50">\u2014</span>`;
      }
    }
    const tempEl = document.getElementById("net-core-temp");
    const uptimeEl = document.getElementById("net-uptime");
    const clientsEl = document.getElementById("net-dhcp-clients");
    if (tempEl) {
      const t = right.core_temp_c;
      tempEl.textContent = t != null ? `${t}\xB0C` : "\u2014\xB0C";
    }
    if (uptimeEl) {
      uptimeEl.textContent = right.uptime || "\u2014";
    }
    if (clientsEl) {
      const c = right.dhcp_clients;
      clientsEl.textContent = c != null ? c : "\u2014";
    }
  }
  PCCS.tiles = {
    updateGPS,
    updateSensors,
    updateNetworkTile,
    updatePhaseInfo,
    updateClock,
    updateTimeAndSun,
    fetchWeatherForecast,
    getWeatherIcon
  };

  // ../static/js/scenes.js
  var S4 = PCCS.state;
  function setScene(sceneKey) {
    document.querySelectorAll(".scene-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.scene === sceneKey);
    });
    setTimeout(() => {
      document.querySelectorAll(".scene-btn").forEach((btn) => btn.classList.remove("active"));
    }, 750);
    S4.userJustSet.clear();
    S4.sceneActivating = true;
    const socket2 = getSocket();
    if (socket2?.connected) {
      socket2.emit("set_scene", { scene: sceneKey });
      return;
    }
    fetch("/api/scene", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scene: sceneKey })
    }).then((r) => r.ok ? r.json() : null).then((data) => {
      if (!data?.state) {
        S4.sceneActivating = false;
        return;
      }
      if (data.ramp_ms) S4.SCENE_RAMP_MS = data.ramp_ms;
      PCCS.lighting.onStateUpdate(data.state);
    }).catch((err) => {
      S4.sceneActivating = false;
      console.warn("[PCCS] set_scene HTTP failed", err);
    });
  }
  async function loadScenes() {
    try {
      const res = await fetch("/api/scenes");
      const data = await res.json();
      S4.currentScenes = data.scenes || [];
      renderScenes();
    } catch (e) {
      console.error("Failed to load scenes", e);
    }
  }
  function renderScenes() {
    const container = document.getElementById("scenes-grid");
    if (!container) return;
    container.innerHTML = "";
    S4.currentScenes.forEach((scene) => {
      const btn = document.createElement("button");
      btn.className = `scene-btn flex flex-col items-center justify-center py-6 rounded-2xl transition-all active:scale-95 ${scene.all_off ? "all-off-btn" : ""}`;
      btn.dataset.scene = scene.key;
      if (scene.description) {
        btn.title = scene.description;
      }
      btn.innerHTML = `
				<i class="fa-solid ${scene.icon} text-2xl mb-3"></i>
				<span class="font-medium text-sm tracking-wide">${scene.name}</span>
			`;
      btn.addEventListener("click", () => setScene(scene.key));
      container.appendChild(btn);
    });
    fixLastRowStretching(container);
  }
  function fixLastRowStretching(container) {
    const total = S4.currentScenes.length;
    if (total <= 3) return;
    const remainder = total % 3;
    if (remainder === 0) return;
    const buttons = Array.from(container.children);
    const lastRowStart = total - remainder;
    container.querySelectorAll(".last-row").forEach((el) => {
      const kids = Array.from(el.children);
      kids.forEach((kid) => container.appendChild(kid));
      el.remove();
    });
    if (remainder === 1) {
      buttons[lastRowStart].style.gridColumn = "1 / -1";
    } else if (remainder === 2) {
      const btn1 = buttons[lastRowStart];
      const btn2 = buttons[lastRowStart + 1];
      const wrapper = document.createElement("div");
      wrapper.className = "last-row";
      wrapper.style.gridColumn = "1 / -1";
      wrapper.appendChild(btn1);
      wrapper.appendChild(btn2);
      container.appendChild(wrapper);
    }
  }
  PCCS.scenes = {
    loadScenes,
    renderScenes,
    fixLastRowStretching,
    setScene
  };

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
    const socket2 = getSocket();
    if (!socket2) return;
    if (socket2.connected) {
      socket2.emit("get_current_dark_mode");
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
    register(socket2) {
      socket2.on("global_dark_mode_update", (data) => {
        applyDarkMode(data);
        updateActiveModeButton(data.mode);
      });
      socket2.on("global_theme_update", (data) => {
        const select = document.getElementById("quick-theme-select");
        if (select && data.theme) select.value = data.theme;
      });
    }
  };

  // ../static/js/toasts.js
  function createToast(data) {
    const { id, message, type = "info", duration = 5e3, title, persistent = false } = data || {};
    const container = document.getElementById("toast-container");
    if (!container) return;
    let icon = "fa-info-circle";
    if (type === "success") icon = "fa-check-circle";
    else if (type === "warning") icon = "fa-exclamation-triangle";
    else if (type === "error") icon = "fa-circle-xmark";
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.id = id || "toast-" + Date.now();
    toast.innerHTML = `
    <i class="fa-solid ${icon} text-2xl flex-shrink-0 mt-0.5"></i>
    <div class="toast-content flex-1 min-w-0">
      ${title ? `<div class="toast-title">${title}</div>` : ""}
      <div class="toast-message">${message}</div>
    </div>
    <button class="text-xl leading-none self-start mt-0.5" aria-label="Close">
      <i class="fa-solid fa-xmark"></i>
    </button>
  `;
    container.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add("show"));
    const closeBtn = toast.querySelector("button");
    closeBtn.addEventListener("click", () => dismissToast(toast));
    toast.addEventListener("click", (e) => {
      if (e.target.tagName !== "BUTTON" && !e.target.closest("button")) dismissToast(toast);
    });
    if (!persistent && duration > 0) {
      setTimeout(() => dismissToast(toast), duration);
    }
  }
  function dismissToast(toast) {
    if (!toast || !toast.parentNode) return;
    toast.style.transition = "opacity 0.95s cubic-bezier(0.25, 0.1, 0.25, 1), transform 0.95s cubic-bezier(0.25, 0.1, 0.25, 1)";
    toast.style.opacity = "0";
    toast.style.transform = "translateY(12px)";
    toast.addEventListener("transitionend", () => {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, { once: true });
  }
  PCCS.toasts = {
    createToast,
    dismissToast,
    register(socket2) {
      socket2.on("toast", (data) => createToast(data));
    }
  };

  // ../static/js/sonos-controller.js
  var currentActiveSonosSpeaker = null;
  var currentSonosState = {};
  var progressInterval = null;
  function formatTime2(seconds) {
    if (!seconds || isNaN(seconds)) return "0:00";
    const min = Math.floor(seconds / 60);
    const sec = Math.floor(seconds % 60);
    return `${min}:${sec.toString().padStart(2, "0")}`;
  }
  function updateSonosUI(state) {
    currentSonosState = state || {};
    const hasSpeaker = !!(state && state.speaker);
    const isEnabled = !!(state && state.enabled !== false);
    if (!hasSpeaker || !isEnabled) {
      const volSlider2 = document.getElementById("sonos-volume-slider");
      const volValue2 = document.getElementById("sonos-volume-value");
      if (volSlider2) {
        volSlider2.disabled = true;
        volSlider2.value = 0;
      }
      if (volValue2) volValue2.textContent = "\u2014";
      return;
    }
    const hasAlbumArt = !!(state && state.album_art && state.album_art.trim() !== "");
    const artEl = document.getElementById("sonos-album-art");
    const overlayEl = document.getElementById("sonos-overlay");
    if (artEl) {
      artEl.style.backgroundImage = hasAlbumArt ? `url('${state.album_art}')` : "none";
      artEl.style.backgroundColor = hasAlbumArt ? "" : "#1f2937";
    }
    if (overlayEl) {
      overlayEl.style.opacity = hasAlbumArt ? "1" : "0";
    }
    document.getElementById("sonos-speaker-name").textContent = state.speaker || "\u2014";
    document.getElementById("sonos-track").textContent = state.track || "Nothing playing";
    document.getElementById("sonos-artist").textContent = state.artist || (state.album || "\xA0");
    const playIcon = document.getElementById("sonos-play-icon");
    if (playIcon) {
      playIcon.classList.toggle("fa-play", !state.is_playing);
      playIcon.classList.toggle("fa-pause", !!state.is_playing);
    }
    const volSlider = document.getElementById("sonos-volume-slider");
    const volValue = document.getElementById("sonos-volume-value");
    if (volSlider) {
      if (state.volume !== void 0 && state.volume !== null) {
        volSlider.disabled = false;
        volSlider.value = state.volume;
        if (volValue) volValue.textContent = `${state.volume}%`;
      } else {
        volSlider.disabled = true;
        volSlider.value = 0;
        if (volValue) volValue.textContent = "\u2014";
      }
    }
    const muteIcon = document.getElementById("sonos-mute-icon");
    if (muteIcon) {
      muteIcon.classList.toggle("fa-volume-mute", !!state.mute);
      muteIcon.classList.toggle("fa-volume-high", !state.mute);
    }
    updateProgressBar(state);
  }
  function updateProgressBar(state) {
    const progressBar = document.getElementById("sonos-progress-bar");
    const elapsedEl = document.getElementById("sonos-time-elapsed");
    const remainingEl = document.getElementById("sonos-time-remaining");
    if (!progressBar) return;
    const position = state.position || 0;
    const duration = state.duration || 0;
    if (duration <= 0) {
      progressBar.style.width = "0%";
      elapsedEl.textContent = "0:00";
      remainingEl.textContent = "-0:00";
      return;
    }
    const percent = Math.min(100, Math.max(0, position / duration * 100));
    progressBar.style.width = `${percent}%`;
    elapsedEl.textContent = formatTime2(position);
    remainingEl.textContent = `-${formatTime2(duration - position)}`;
  }
  function startProgressUpdater() {
    if (progressInterval) clearInterval(progressInterval);
    progressInterval = setInterval(() => {
      if (currentSonosState.is_playing && currentSonosState.duration) {
        currentSonosState.position = (currentSonosState.position || 0) + 1;
        if (currentSonosState.position > currentSonosState.duration) {
          currentSonosState.position = currentSonosState.duration;
        }
        updateProgressBar(currentSonosState);
      }
    }, 1e3);
  }
  function sonosVolumeChange(volume) {
    const volValue = document.getElementById("sonos-volume-value");
    if (volValue) volValue.textContent = `${volume}%`;
    getSocket().emit("sonos_command", {
      command: "volume",
      value: parseInt(volume)
    });
  }
  function requestSonosState() {
    if (getSocket().connected) {
      getSocket().emit("sonos_request_state");
    } else {
      setTimeout(requestSonosState, 300);
    }
  }
  function sonosCommand(command) {
    if (!getSocket().connected) {
      console.warn("Socket not connected");
      return;
    }
    getSocket().emit("sonos_command", { command });
    if (command === "playpause") {
      const playIcon = document.getElementById("sonos-play-icon");
      if (playIcon) {
        const isPlaying = playIcon.classList.contains("fa-pause");
        playIcon.classList.toggle("fa-play", isPlaying);
        playIcon.classList.toggle("fa-pause", !isPlaying);
      }
    }
  }
  function toggleSonosMute() {
    const muteBtn = document.getElementById("sonos-mute-btn");
    if (!muteBtn) return;
    getSocket().emit("sonos_command", { command: "mute" });
    const icon = document.getElementById("sonos-mute-icon");
    if (icon) {
      const isMuted = icon.classList.contains("fa-volume-mute");
      icon.classList.toggle("fa-volume-mute", !isMuted);
      icon.classList.toggle("fa-volume-high", isMuted);
    }
  }
  PCCS.sonos = {
    updateSonosUI,
    startProgressUpdater,
    requestSonosState,
    sonosVolumeChange,
    sonosCommand,
    toggleSonosMute,
    register(socket2) {
      socket2.on("sonos_speakers", (data) => {
        if (data.current) currentActiveSonosSpeaker = data.current;
      });
      socket2.on("sonos_update", (state) => {
        if (!state) return;
        if (currentActiveSonosSpeaker && state.speaker && state.speaker !== currentActiveSonosSpeaker) return;
        updateSonosUI(state);
      });
    },
    bindProgressSeek() {
      const el = document.getElementById("sonos-progress-container");
      if (!el) return;
      el.addEventListener("click", function(e) {
        const rect = this.getBoundingClientRect();
        const percent = (e.clientX - rect.left) / rect.width;
        getSocket().emit("sonos_command", { command: "seek", value: percent });
      });
    }
  };

  // ../static/js/victron-tile.js
  function formatTTG2(mins) {
    if (mins === null || mins === void 0 || mins <= 0) return "\u2014";
    if (mins >= 65e3) return "\u221E";
    const h = Math.floor(mins / 60);
    const m = Math.round(mins % 60);
    if (h > 0) return `${h}h ${m.toString().padStart(2, "0")}m`;
    return `${m}m`;
  }
  function updatePowerTile(data) {
    if (!data) return;
    const tile = document.getElementById("power-tile");
    if (!tile) return;
    const soc = data.soc != null ? Math.max(0, Math.min(100, Math.round(data.soc))) : null;
    const socEl = document.getElementById("soc-percent");
    const progress = document.getElementById("soc-progress");
    if (socEl) socEl.textContent = soc != null ? soc + "%" : "\u2014";
    if (progress) {
      const circ = 245;
      const offset = soc != null ? circ * (1 - soc / 100) : circ;
      progress.setAttribute("stroke-dashoffset", offset.toFixed(1));
      progress.setAttribute("stroke", "var(--accent-color)");
    }
    const vEl = document.getElementById("bat-voltage");
    if (vEl) {
      if (data.voltage != null) {
        vEl.textContent = `${parseFloat(data.voltage).toFixed(1)}V`;
      } else {
        vEl.textContent = "\u2014";
      }
    }
    const ttgEl = document.getElementById("bat-ttg");
    if (ttgEl) ttgEl.textContent = formatTTG2(data.time_to_go_mins);
    const consEl = document.getElementById("bat-consumed");
    if (consEl) {
      if (data.consumed_ah != null) {
        const sign = data.consumed_ah > 0 ? "+" : "";
        consEl.textContent = `${sign}${parseFloat(data.consumed_ah).toFixed(1)}Ah`;
      } else {
        consEl.textContent = "\u2014";
      }
    }
    const solEl = document.getElementById("sol-current");
    if (solEl) {
      const a = data.solar_current_a != null ? data.solar_current_a : data.current_a;
      if (a != null) {
        solEl.textContent = `${parseFloat(a).toFixed(1)}A`;
      } else {
        solEl.textContent = "\u2014";
      }
    }
    const todayEl = document.getElementById("sol-today");
    if (todayEl) {
      if (data.yield_today_kwh != null) {
        todayEl.textContent = `${parseFloat(data.yield_today_kwh).toFixed(2)} kWh`;
      } else {
        todayEl.textContent = "\u2014";
      }
    }
    const csEl = document.getElementById("charge-state");
    if (csEl) {
      csEl.textContent = data.charge_state || "";
    }
  }
  PCCS.victron = { updatePowerTile };

  // ../static/js/fullscreen.js
  function toggleFullscreen() {
    const icon = document.getElementById("fullscreen-icon");
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().then(() => {
        icon.classList.remove("fa-expand");
        icon.classList.add("fa-compress");
      }).catch((err) => console.warn("Fullscreen failed:", err));
    } else {
      document.exitFullscreen().then(() => {
        icon.classList.remove("fa-compress");
        icon.classList.add("fa-expand");
      });
    }
  }
  document.addEventListener("fullscreenchange", () => {
    const icon = document.getElementById("fullscreen-icon");
    if (icon) {
      if (document.fullscreenElement) {
        icon.classList.remove("fa-expand");
        icon.classList.add("fa-compress");
      } else {
        icon.classList.remove("fa-compress");
        icon.classList.add("fa-expand");
      }
    }
  });
  PCCS.fullscreen = { toggleFullscreen };

  // ../static/js/app.js
  var socket = io();
  globalThis.socket = socket;
  function onConnect(sock) {
    PCCS.offline.hide();
    registerThemeListener(sock);
    loadCurrentTheme();
    loadQuickThemes();
    PCCS.scenes.loadScenes();
    PCCS.version.loadVersion();
    PCCS.sonos.requestSonosState();
    sock.emit("get_network_status");
    sock.emit("get_victron_state");
    sock.emit("get_reeds");
    PCCS.darkMode.requestInitialDarkMode();
    setTimeout(() => {
      fetch("/api/network_status").then((r) => r.json()).then(PCCS.tiles.updateNetworkTile).catch(() => {
      });
    }, 1200);
    setTimeout(() => {
      if (PCCS.sunCurve) PCCS.sunCurve.updateCurveGeometry();
    }, 50);
  }
  function registerHandlers(sock) {
    PCCS.offline.register(sock);
    PCCS.darkMode.register(sock);
    PCCS.toasts.register(sock);
    PCCS.sonos.register(sock);
    sock.on("lights_config", (c) => PCCS.lighting.onLightsConfig(c));
    sock.on("state_update", (s) => PCCS.lighting.onStateUpdate(s));
    sock.on("reed_update", (p) => PCCS.lighting.onReedUpdate(p));
    sock.on("sensor_update", (d) => PCCS.tiles.updateSensors(d));
    sock.on("gps_update", (d) => PCCS.tiles.updateGPS(d));
    sock.on("phase_update", (d) => PCCS.tiles.updatePhaseInfo(d));
    sock.on("network_update", (d) => PCCS.tiles.updateNetworkTile(d));
    sock.on("victron_update", (d) => PCCS.victron.updatePowerTile(d));
    sock.on("connect", () => onConnect(sock));
  }
  registerHandlers(socket);
  function initDom() {
    if (PCCS.sunCurve && typeof PCCS.sunCurve.init === "function") {
      PCCS.sunCurve.init();
    }
    PCCS.sonos.bindProgressSeek();
    PCCS.lighting.initResize();
    globalThis.toggleFullscreen = PCCS.fullscreen.toggleFullscreen;
    globalThis.sonosCommand = PCCS.sonos.sonosCommand;
    globalThis.toggleSonosMute = PCCS.sonos.toggleSonosMute;
    globalThis.sonosVolumeChange = PCCS.sonos.sonosVolumeChange;
    globalThis.setDarkMode = PCCS.darkMode.setDarkMode;
    globalThis.setScene = PCCS.scenes.setScene;
    globalThis.toggleGlobalDarkMode = function() {
      const html = document.documentElement;
      const newMode = html.classList.contains("light") ? "dark" : "light";
      socket.emit("set_global_dark_mode", { mode: newMode });
    };
    globalThis.onload = function() {
      PCCS.tiles.updateClock();
      setInterval(PCCS.tiles.updateClock, 1e4);
      registerThemeListener(socket);
      loadCurrentTheme();
      PCCS.version.loadVersion();
      PCCS.sonos.startProgressUpdater();
    };
  }
  PCCS.app = { init: initDom, socket };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initDom);
  } else {
    initDom();
  }
})();
//# sourceMappingURL=dashboard.js.map
