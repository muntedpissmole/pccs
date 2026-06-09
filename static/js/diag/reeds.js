/**
 * PCCS Diagnostics — Reed switches
 */
(function () {
  'use strict';
  const PCCS = window.PCCS;
  const D = PCCS.diag;
  const S = D.state;
  function getSocket() { return PCCS.getSocket(); }
  const toTitleCase = D.utils.toTitleCase;

  // REED SWITCHES
          function updateReeds(data) {
              S.reedsCache = data;
              const states = data.states || {};
              const forced = data.forced || {};

              Object.keys(states).forEach(name => {
                  const card = document.querySelector(`.tile[data-name="${CSS.escape(name)}"]`);
                  if (!card) return;

                  const isForced = name in forced;
                  const forcedClosed = isForced ? forced[name] : null;
                  const realClosed = states[name];

                  const displayState = isForced 
                      ? (forcedClosed ? 'FORCED CLOSED' : 'FORCED OPEN')
                      : (realClosed ? 'CLOSED' : 'OPEN');

                  const color = (isForced ? forcedClosed : realClosed) ? '#4ade80' : '#f87171';

                  const stateEl = card.querySelector(`#state-${CSS.escape(name)}`);
                  if (stateEl) {
                      stateEl.textContent = displayState;
                      stateEl.style.color = color;
                  }

                  const btns = card.querySelectorAll('button');
                  if (btns.length >= 2) {
                      btns[0].classList.toggle('active-force', isForced && forcedClosed);
                      btns[1].classList.toggle('active-force', isForced && !forcedClosed);
                  }
              });
          }

          function renderReeds(data) {
              const container = document.getElementById('reeds-list');
              container.innerHTML = '';

              const states = data.states || {};
              const forced = data.forced || {};
              const sortedNames = Object.keys(states).sort((a, b) => a.localeCompare(b));

              sortedNames.forEach(name => {
                  const isForced = name in forced;
                  const forcedClosed = isForced ? forced[name] : null;
                  const realClosed = states[name];

                  let displayState = isForced 
                      ? (forcedClosed ? 'FORCED CLOSED' : 'FORCED OPEN')
                      : (realClosed ? 'CLOSED' : 'OPEN');

                  let color = (isForced ? forcedClosed : realClosed) ? '#4ade80' : '#f87171';

                  const card = document.createElement('div');
                  card.className = 'tile';
                  card.dataset.name = name;

                  card.innerHTML = `
                      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
                          <strong>${toTitleCase(name.replace(/_/g, ' '))}</strong>
                          <div id="state-${name}" style="font-size:1.4rem; font-weight:700; color:${color};">${displayState}</div>
                      </div>
                      <div class="btn-group">
                          <button class="btn">🔒 Force Closed</button>
                          <button class="btn">🔓 Force Open</button>
                          <button class="btn danger">❌ Clear Force</button>
                      </div>
                  `;

                  const buttons = card.querySelectorAll('button');
                  buttons[0].addEventListener('click', () => forceReedOptimistic(name, true));
                  buttons[1].addEventListener('click', () => forceReedOptimistic(name, false));
                  buttons[2].addEventListener('click', () => clearReedForceOptimistic(name));

                  container.appendChild(card);
              });
          }

          function forceReedOptimistic(name, closed) {
              const card = document.querySelector(`.tile[data-name="${CSS.escape(name)}"]`);
              if (!card) return;

              const stateEl = card.querySelector(`#state-${CSS.escape(name)}`);
              if (stateEl) {
                  stateEl.textContent = closed ? 'FORCED CLOSED' : 'FORCED OPEN';
                  stateEl.style.color = '#4ade80';
              }

              const btns = card.querySelectorAll('button');
              if (btns.length >= 2) {
                  btns[0].classList.toggle('active-force', closed);
                  btns[1].classList.toggle('active-force', !closed);
              }

              getSocket().emit('force_reed', { name, closed });
          }

          function clearReedForceOptimistic(name) {
              const card = document.querySelector(`.tile[data-name="${CSS.escape(name)}"]`);
              if (!card) return;

              const stateEl = card.querySelector(`#state-${CSS.escape(name)}`);
              if (stateEl && S.reedsCache.states && S.reedsCache.states[name] !== undefined) {
                  const real = S.reedsCache.states[name];
                  stateEl.textContent = real ? 'CLOSED' : 'OPEN';
                  stateEl.style.color = real ? '#4ade80' : '#f87171';
              }
              const btns = card.querySelectorAll('button');
              btns.forEach(b => b.classList.remove('active-force'));

              getSocket().emit('force_reed', { name, closed: null });
          }

  D.reeds = { updateReeds, renderReeds };
})();
