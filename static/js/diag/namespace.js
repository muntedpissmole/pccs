/**
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
