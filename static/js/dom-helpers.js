/**
 * PCCS DOM Helpers
 * Safe, cached element access and common update patterns.
 * Reduces repetitive getElementById + null checks across the app.
 *
 * Part of the professional frontend refactor for release.
 */
import { PCCS } from './namespace.js';

const cache = new Map();

/**
 * Get element by ID (with lightweight caching for hot elements).
 * @param {string} id
 * @param {boolean} [useCache=true]
 * @returns {HTMLElement|null}
 */
function $(id, useCache = true) {
  if (!id) return null;
  if (useCache && cache.has(id)) {
    const el = cache.get(id);
    // Invalidate stale cache entries (element removed from DOM)
    if (el && el.isConnected) return el;
    cache.delete(id);
  }
  const el = document.getElementById(id);
  if (useCache && el) cache.set(id, el);
  return el;
}

/** Clear the element cache (call on major DOM rebuilds) */
function clearCache() {
  cache.clear();
}

/**
 * Set textContent safely.
 * @param {string} id
 * @param {string|number} value
 * @param {string} [fallback='—']
 */
function setText(id, value, fallback = '—') {
  const el = $(id, false); // avoid cache churn on frequent updates
  if (el) el.textContent = (value != null && value !== '') ? value : fallback;
}

/**
 * Toggle a class based on condition.
 * @param {string} id
 * @param {string} className
 * @param {boolean} condition
 */
function toggleClass(id, className, condition) {
  const el = $(id, false);
  if (el) el.classList.toggle(className, !!condition);
}

/**
 * Set a style property safely.
 * @param {string} id
 * @param {string} prop
 * @param {string} value
 */
function setStyle(id, prop, value) {
  const el = $(id, false);
  if (el) el.style[prop] = value;
}

/**
 * Get element(s) via querySelector (no caching – for one-off structural queries).
 */
function q(selector, parent = document) {
  return parent.querySelector(selector);
}

function qa(selector, parent = document) {
  return Array.from(parent.querySelectorAll(selector));
}

// Public API
PCCS.dom = {
  $,
  clearCache,
  setText,
  toggleClass,
  setStyle,
  q,
  qa
};

// Backwards-compat shims during transition (will be removed in later phase)
globalThis.PCCS_getEl = $;