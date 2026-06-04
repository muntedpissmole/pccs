/**
 * PCCS Animation Utilities
 * Shared rAF-based animation primitives (cubic ease out by default).
 * Consolidates the duplicated sun-position / curve-morph / toast step functions.
 *
 * Part of the professional frontend refactor for release.
 */
(function () {
  'use strict';

  const DEFAULT_EASE = (p) => 1 - Math.pow(1 - p, 3); // cubicOut – matches existing code

  /**
   * Run a timed animation.
   * @param {Object} options
   * @param {number} options.duration - ms
   * @param {function} [options.ease] - easing fn (0→1)
   * @param {function} options.onStep - called each frame with eased progress (0→1)
   * @param {function} [options.onComplete]
   * @returns {function} cancel() – call to abort
   */
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
        console.error('[PCCS.animate] onStep error', e);
      }
      if (p < 1) {
        raf = requestAnimationFrame(step);
      } else {
        if (onComplete) {
          try { onComplete(); } catch (e) { console.error('[PCCS.animate] onComplete error', e); }
        }
      }
    }

    raf = requestAnimationFrame(step);

    return function cancel() {
      cancelled = true;
      if (raf) cancelAnimationFrame(raf);
    };
  }

  window.PCCS = window.PCCS || {};
  window.PCCS.animate = {
    run: animate,
    cubicOut: DEFAULT_EASE
  };
})();