/**
 * PCCS Diagnostics — utilities
 */
(function () {
  'use strict';
  const D = window.PCCS.diag;
  function toTitleCase(str) {
    return str.replace(/\w\S*/g, txt =>
      txt.charAt(0).toUpperCase() + txt.substr(1).toLowerCase()
    );
  }
  D.utils = { toTitleCase };
})();
