/**
 * PCCS Diagnostics — Appearance
 */
(function () {
  'use strict';
  const PCCS = window.PCCS;
  const D = PCCS.diag;
  const S = D.state;
  function getSocket() { return PCCS.getSocket(); }

  function loadThemes() {
              fetch('/api/themes').then(r => r.json()).then(data => {
                  const select = document.getElementById('theme-select');
                  select.innerHTML = '';
                  data.themes.forEach(t => {
                      const opt = document.createElement('option');
                      opt.value = t.file;
                      opt.textContent = t.name;
                      select.appendChild(opt);
                  });
                  fetch('/api/current-theme').then(r => r.json()).then(cur => {
                      if (cur.theme) select.value = cur.theme;
                  });
              }).catch(() => {});
          }

  D.appearance = { loadThemes };
})();
