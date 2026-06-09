/**
 * PCCS Diagnostics — Phase management
 */
(function () {
  'use strict';
  const PCCS = window.PCCS;
  const D = PCCS.diag;
  const S = D.state;
  function getSocket() { return PCCS.getSocket(); }

  // PHASES
          function updatePhaseForced(data) {
              document.getElementById('phase-forced').innerHTML = data.forced
                  ? `<span style="color:#fbbf24;">🔧 FORCED</span>`
                  : 'Automatic';
          }

          function updatePhase(data) {
              document.getElementById('current-phase').innerHTML = `
                  ${data.phase === 'Day' ? '🌞' : data.phase === 'Evening' ? '🌅' : '🌙'} 
                  ${data.phase || 'Unknown'}
              `;

              let timingsHTML = data.day_start ? `
                  <div class="status-row"><span>Day starts</span><span>${data.day_start}</span></div>
                  <div class="status-row"><span>Evening starts</span><span>${data.evening_start}</span></div>
                  <div class="status-row"><span>Night starts</span><span>${data.night_start}</span></div>
              ` : '';
              document.getElementById('phase-timings').innerHTML = timingsHTML;
          }

          function forcePhase(phase) {
              document.getElementById('current-phase').innerHTML = `
                  ${phase === 'Day' ? '🌞' : phase === 'Evening' ? '🌅' : '🌙'} ${phase}
              `;
              document.getElementById('phase-forced').innerHTML = `<span style="color:#fbbf24;">🔧 FORCED</span>`;
              getSocket().emit('force_phase', { phase });
          }

          function clearPhaseForce() {
              document.getElementById('phase-forced').innerHTML = 'Automatic';
              getSocket().emit('force_phase', { phase: null });
          }

  D.phases = { updatePhase, updatePhaseForced, forcePhase, clearPhaseForce };
})();
