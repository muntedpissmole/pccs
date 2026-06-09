/**
 * PCCS global namespace root.
 * All frontend modules attach to window.PCCS.*
 */
(function () {
  'use strict';
  window.PCCS = window.PCCS || {};
  window.PCCS.getSocket = function () {
    return window.socket || null;
  };
})();