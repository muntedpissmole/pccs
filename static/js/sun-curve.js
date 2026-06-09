/**
 * PCCS Sun / Moon Curve Visualization
 *
 * Handles:
 * - Dynamic quadratic bezier curve geometry (responsive to tile width)
 * - Smooth morphing on resize
 * - Sun/moon position calculation based on sunrise/sunset + current time
 * - Animated travel along the actual curve (not straight lines)
 * - Phase boundary labels: always day phase start time (left, day-start-label) + evening phase start time (right, evening-start-label)
 *   for consistent logical display on the date/time tile (day start is always the morning-ish phase start).
 *   Sun/moon position + arcs use raw astro sunrise/sunset.
 *
 * This was extracted from the monolithic index.html script for the release.
 * All original behavior preserved.
 */
import { PCCS } from './namespace.js';

const dom = PCCS.dom || {};
const format = PCCS.format || {};
const animate = PCCS.animate || {};

  // ==================== INTERNAL STATE ====================
  let phaseInfo = { phase: 'Day', day_start: '—', evening_start: '—', sunrise: '—', sunset: '—' };

  let currentCurveParams = null;
  let curveGeometryReady = false;

  let lastSunriseStr = null;
  let lastSunsetStr = null;
  let lastCurrentTimeStr = null;

  let displayT = 0.5;
  let displayIsDay = true;
  let sunAnimFrame = null;
  let hasSunPositioned = false;
  const SUN_ANIM_DURATION = 680;

  let curveAnimFrame = null;

  // ==================== PUBLIC API ====================
  const SunCurve = {};

  SunCurve.updatePhaseInfo = function (data) {
    if (!data) return;
    phaseInfo.phase = data.phase || 'Day';
    if (data.day_start) phaseInfo.day_start = data.day_start;
    if (data.evening_start) phaseInfo.evening_start = data.evening_start;
    if (data.sunrise) phaseInfo.sunrise = data.sunrise;
    if (data.sunset) phaseInfo.sunset = data.sunset;

    updatePhaseCurveLabels();
  };

  SunCurve.updateCurveGeometry = updateCurveGeometry;

  SunCurve.animateSunPosition = function (sunriseStr, sunsetStr, currentTimeStr) {
    animateSunPosition(sunriseStr, sunsetStr, currentTimeStr);
  };

  SunCurve.init = function () {
    // Run geometry calculation as early as possible
    if (typeof requestAnimationFrame === 'function') {
      requestAnimationFrame(() => {
        updateCurveGeometry();
        requestAnimationFrame(() => updateCurveGeometry());
      });
    }

    // Keep the curve looking good when the tile resizes
    let curveResizeTimer;
    window.addEventListener('resize', () => {
      clearTimeout(curveResizeTimer);
      curveResizeTimer = setTimeout(updateCurveGeometry, 140);
    });
  };

  // Expose for debugging if needed
  PCCS.sunCurve = SunCurve;

  // ==================== INTERNAL IMPLEMENTATION ====================

  function updatePhaseCurveLabels() {
    const leftLabel = dom.$ ? dom.$('day-start-label') : document.getElementById('day-start-label');
    const rightLabel = dom.$ ? dom.$('evening-start-label') : document.getElementById('evening-start-label');
    if (!leftLabel || !rightLabel) return;

    const strip = format.stripLeadingZero || (s => s ? s.replace(/^0/, '') : s);
    const dayStart = strip(phaseInfo.day_start) || '—';
    const eveStart = strip(phaseInfo.evening_start) || '—';
    // sunrise/sunset kept for sun/moon positioning and bottom labels (raw astro)
    const sunriseStr = strip(phaseInfo.sunrise || phaseInfo.day_start) || '—';
    const sunsetStr = strip(phaseInfo.sunset || phaseInfo.evening_start) || '—';

    // Always show day phase start time on the left of the curve and evening phase start time on the right.
    // This matches the label element IDs and the expected layout for the date/time tile (day start left, evening right).
    // The previous phase-adaptive swap (eve left / day right for evening/night) was causing the reversal
    // during day phase. The curve geometry + sun/moon animation still use raw sunrise/sunset.
    let leftText = dayStart;
    let rightText = eveStart;
    let leftColor = '#fcd34d';
    let rightColor = '#94a3b8';

    leftLabel.textContent = leftText;
    rightLabel.textContent = rightText;
    leftLabel.style.color = leftColor;
    rightLabel.style.color = rightColor;
  }

  function updateCurveGeometry() {
    const container = dom.$ ? dom.$('sun-curve') : document.getElementById('sun-curve');
    if (!container) return;

    const w = container.clientWidth;
    if (!w || w < 120) return;

    const h = 72;
    const archHeight = Math.min(52, Math.max(36, 28 + w * 0.045));

    let minInset = 38;
    const sunriseGroup = (dom.$ ? dom.$('sunrise') : document.getElementById('sunrise'))?.parentElement;
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

    const dayPath = dom.$ ? dom.$('day-path') : document.getElementById('day-path');
    const nightPath = dom.$ ? dom.$('night-path') : document.getElementById('night-path');
    const svg = container.querySelector('svg');

    if (!curveGeometryReady || !currentCurveParams) {
      if (svg) svg.setAttribute('viewBox', `0 0 ${viewBoxW} ${h}`);
      const d = `M ${x0.toFixed(1)} ${y0} Q ${x1.toFixed(1)} ${y1.toFixed(1)} ${x2.toFixed(1)} ${y2}`;
      if (dayPath) dayPath.setAttribute('d', d);
      if (nightPath) nightPath.setAttribute('d', d);

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
    const sun = dom.$ ? dom.$('sun-position') : document.getElementById('sun-position');
    const glow = dom.$ ? dom.$('sun-glow') : document.getElementById('sun-glow');
    if (!sun || !glow || !currentCurveParams) return;

    const pt = getPointOnCurve(t, currentCurveParams);
    sun.setAttribute('cx', pt.x);
    sun.setAttribute('cy', pt.y);
    glow.setAttribute('cx', pt.x);
    glow.setAttribute('cy', pt.y);

    if (isDay) {
      sun.setAttribute('fill', '#fbbf24');
      glow.setAttribute('fill', '#fbbf24');
      glow.setAttribute('opacity', '0.28');
    } else {
      sun.setAttribute('fill', '#e2e8f0');
      glow.setAttribute('fill', '#e2e8f0');
      glow.setAttribute('opacity', '0.45');
    }

    displayT = t;
    displayIsDay = isDay;
  }

  function startSunAnimation(targetT, targetIsDay) {
    if (sunAnimFrame) {
      cancelAnimationFrame(sunAnimFrame);
      sunAnimFrame = null;
    }

    const sunEl = dom.$ ? dom.$('sun-position') : document.getElementById('sun-position');
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
    const phaseChanged = (targetIsDay !== displayIsDay);
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
      svgEl.setAttribute('viewBox', `0 0 ${p.viewBoxW} ${p.h || 72}`);
    }
    const d = `M ${p.x0.toFixed(1)} ${p.y0} Q ${p.x1.toFixed(1)} ${p.y1.toFixed(1)} ${p.x2.toFixed(1)} ${p.y2}`;
    if (dayEl) dayEl.setAttribute('d', d);
    if (nightEl) nightEl.setAttribute('d', d);
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

    if (!from || typeof from.x0 !== 'number') {
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
    const sun = dom.$ ? dom.$('sun-position') : document.getElementById('sun-position');
    const glow = dom.$ ? dom.$('sun-glow') : document.getElementById('sun-glow');
    const dayPath = dom.$ ? dom.$('day-path') : document.getElementById('day-path');
    const nightPath = dom.$ ? dom.$('night-path') : document.getElementById('night-path');

    if (!sun || !glow || !sunriseStr || !sunsetStr) return;

    lastSunriseStr = sunriseStr;
    lastSunsetStr = sunsetStr;
    lastCurrentTimeStr = currentTimeStr;

    if (!curveGeometryReady || !currentCurveParams) {
      sun.setAttribute('cx', 80);
      sun.setAttribute('cy', 38);
      glow.setAttribute('cx', 80);
      glow.setAttribute('cy', 38);
      displayT = 0.5;
      return;
    }

    const parse = format.parseTimeToMinutes || function (str) {
      if (!str || typeof str !== 'string') return null;
      let s = str.trim().toUpperCase();
      const m = s.match(/^(\d{1,2}):(\d{2})(?::\d{2})?\s*(AM|PM)?$/);
      if (m) {
        let h = parseInt(m[1], 10);
        const min = parseInt(m[2], 10);
        const ap = m[3];
        if (ap === 'PM' && h < 12) h += 12;
        if (ap === 'AM' && h === 12) h = 0;
        if (h > 23 || min > 59 || isNaN(h) || isNaN(min)) return null;
        return h * 60 + min;
      }
      const parts = s.split(':');
      const h = parseInt(parts[0], 10);
      const min = parseInt(parts[1], 10);
      if (isNaN(h) || isNaN(min)) return null;
      return ((h % 24) * 60) + (min % 60);
    };

    const sunriseMin = parse(sunriseStr);
    const sunsetMin = parse(sunsetStr);
    let currentMin = parse(currentTimeStr);

    if (sunriseMin === null || sunsetMin === null) return;
    if (currentMin === null) currentMin = 12 * 60;

    const DAY_MINUTES = 1440;
    currentMin = ((currentMin % DAY_MINUTES) + DAY_MINUTES) % DAY_MINUTES;

    let targetT = 0.5;
    let targetIsDay = true;

    if (currentMin >= sunriseMin && currentMin <= sunsetMin) {
      targetIsDay = true;
      const dayLen = sunsetMin - sunriseMin;
      targetT = (dayLen > 0) ? (currentMin - sunriseMin) / dayLen : 0.5;
    } else {
      targetIsDay = false;
      let nightProgress = 0;
      if (currentMin < sunriseMin) {
        const prevSunset = sunsetMin - DAY_MINUTES;
        const nightLen = sunriseMin - prevSunset;
        nightProgress = (nightLen > 0) ? (currentMin - prevSunset) / nightLen : 0;
      } else {
        const nextSunrise = sunriseMin + DAY_MINUTES;
        const nightLen = nextSunrise - sunsetMin;
        nightProgress = (nightLen > 0) ? (currentMin - sunsetMin) / nightLen : 0;
      }
      targetT = nightProgress;
    }

    targetT = Math.max(0, Math.min(1, targetT));
    startSunAnimation(targetT, targetIsDay);

    if (dayPath && nightPath) {
      dayPath.style.transition = 'stroke-opacity 1000ms ease-in-out';
      nightPath.style.transition = 'stroke-opacity 1000ms ease-in-out';

      if (targetIsDay) {
        dayPath.setAttribute('stroke-opacity', '0.85');
        nightPath.setAttribute('stroke-opacity', '0.1');
      } else {
        dayPath.setAttribute('stroke-opacity', '0.1');
        nightPath.setAttribute('stroke-opacity', '0.6');
      }
    }
  }