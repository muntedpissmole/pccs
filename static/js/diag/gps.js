/**
 * PCCS Diagnostics — GPS
 */
(function () {
  'use strict';
  const PCCS = window.PCCS;
  const D = PCCS.diag;
  const S = D.state;
  function getSocket() { return PCCS.getSocket(); }

  function updateGPS(data) {
              const container = document.getElementById('gps-data');
              let html = `
                  <div class="status-row"><span>Fix Quality</span><span><strong>${data.fix_quality || 0}</strong></span></div>
                  <div class="status-row"><span>Satellites</span><span>${data.satellites || 0}</span></div>
                  <div class="status-row"><span>Latitude</span><span>${data.latitude?.toFixed(6) || '—'}</span></div>
                  <div class="status-row"><span>Longitude</span><span>${data.longitude?.toFixed(6) || '—'}</span></div>
                  <div class="status-row"><span>Speed</span><span>${data.speed_kmh || 0} km/h</span></div>
                  <div class="status-row"><span>Suburb</span><span>${data.suburb || data.fallback_suburb || '—'}</span></div>
                  <div class="status-row"><span>Local Time</span><span>${data.local_time || '—'}</span></div>
                  <div class="status-row"><span>Sunrise</span><span>${data.sunrise || '—'}</span></div>
                  <div class="status-row"><span>Sunset</span><span>${data.sunset || '—'}</span></div>
              `;
              container.innerHTML = html;
              document.getElementById('gps-raw').textContent = (data.raw_sentences || []).join('\n');
          }

          function forceNoFix(enabled) { 
              getSocket().emit('set_gps_simulation', { no_fix: enabled }); 
          }

  D.gps = { updateGPS, forceNoFix };
})();
