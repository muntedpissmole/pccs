/**
 * PCCS Format Utilities
 * Unified time, duration, and display formatting.
 * Replaces scattered formatTime / formatTTG / stripLeadingZero / parseTimeToMinutes.
 *
 * Part of the professional frontend refactor for release.
 */
(function () {
  'use strict';

  /**
   * Format seconds → M:SS (for Sonos progress etc.)
   */
  function formatTime(seconds) {
    if (!seconds || isNaN(seconds)) return '0:00';
    const min = Math.floor(seconds / 60);
    const sec = Math.floor(seconds % 60);
    return `${min}:${sec.toString().padStart(2, '0')}`;
  }

  /**
   * Format Victron minutes → human readable (handles 65535 sentinel).
   */
  function formatTTG(mins) {
    if (mins === null || mins === undefined || mins <= 0) return '—';
    if (mins >= 65000) return '∞'; // Victron "infinite / charging" sentinel
    const h = Math.floor(mins / 60);
    const m = Math.round(mins % 60);
    if (h > 0) return `${h}h ${m.toString().padStart(2, '0')}m`;
    return `${m}m`;
  }

  /**
   * Strip leading zero from time strings like "09:15" → "9:15" (for visual polish).
   */
  function stripLeadingZero(timeStr) {
    if (!timeStr) return timeStr;
    return timeStr.replace(/^0/, '');
  }

  /**
   * Parse time string (supports "H:MM", "HH:MM", "H:MM:SS AM/PM", "HH:MM AM/PM", 24h etc)
   * → minutes since midnight. Returns null on unparsable input.
   */
  function parseTimeToMinutes(str) {
    if (!str || typeof str !== 'string') return null;
    let s = str.trim().toUpperCase();
    // 12h with optional AM/PM, optional seconds: e.g. 06:15 AM, 6:30:00 PM, 13:45
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
    // Fallback for plain 24h or partial (e.g. old paths)
    const parts = s.split(':');
    const h = parseInt(parts[0], 10);
    const min = parseInt(parts[1], 10);
    if (isNaN(h) || isNaN(min)) return null;
    return ((h % 24) * 60) + (min % 60);
  }

  /**
   * Generic duration formatter (minutes) – future extension point.
   */
  function formatDurationMinutes(mins, opts = {}) {
    if (mins == null || isNaN(mins)) return opts.fallback || '—';
    if (mins >= 65000 && opts.infiniteSentinel) return opts.infiniteSentinel;
    // ... can be expanded later without changing call sites
    return formatTTG(mins);
  }

  window.PCCS = window.PCCS || {};
  window.PCCS.format = {
    time: formatTime,
    ttg: formatTTG,
    stripLeadingZero,
    parseTimeToMinutes,
    durationMinutes: formatDurationMinutes
  };

  // Backwards shims (transition period only)
  window.formatTime = formatTime;
  window.formatTTG = formatTTG;
  window.stripLeadingZero = stripLeadingZero;
  window.parseTimeToMinutes = parseTimeToMinutes;
})();