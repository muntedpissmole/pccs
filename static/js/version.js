/**
 * PCCS Version Footer
 * Extracted from templates/index.html
 */
(function () {
  'use strict';
  const PCCS = window.PCCS;
  const S = PCCS.state;
  function getSocket() { return PCCS.getSocket(); }

async function loadVersion() {
        try {
            const res = await fetch('/api/version');
            const data = await res.json();
            const versionEl = document.getElementById('footer-version');
            if (versionEl) {
                versionEl.textContent = `v${data.version || '?.?.?'}`;
            }
        } catch (e) {
            console.warn('Could not load version', e);
            document.getElementById('footer-version').textContent = 'v?.?.?';
        }
    }

  PCCS.version = { loadVersion };
})();
