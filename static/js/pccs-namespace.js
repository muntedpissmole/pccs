/**
 * PCCS global namespace root.
 * All frontend modules attach to window.PCCS.*
 */
(function () {
  'use strict';
  window.PCCS = window.PCCS || {};
  window.PCCS.getSocket = function () {
    return (window.PCCS.app && window.PCCS.app.socket) || window.socket || null;
  };
})();