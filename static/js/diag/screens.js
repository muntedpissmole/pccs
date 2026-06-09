/**
 * PCCS Diagnostics — Touchscreens
 */
import { PCCS, getSocket } from '../namespace.js';

const D = PCCS.diag;
const S = D.state;

  // TOUCHSCREENS
          function renderScreens() {
              const container = document.getElementById('screens-list');
              container.innerHTML = '';

              Object.keys(S.screenData).forEach(name => {
                  const item = S.screenData[name] || {};
                  const conf = item.config || {};

                  const friendly = conf.friendly || name;
                  const icon = conf.icon || 'fa-display';

                  const connColor = item.online ? '#4ade80' : '#f87171';
                  const connText = item.online 
                      ? `ONLINE${item.latency ? ` (${item.latency}ms)` : ''}` 
                      : 'OFFLINE';

                  const sshStatus = (item.ssh_passwordless !== undefined && item.online)
                      ? (item.ssh_passwordless ? '✅ Passwordless SSH OK' : '❌ Passwordless SSH failed')
                      : '';

                  let wakeHTML = '';
                  if (item.online !== false) {
                      const stateColor = item.on ? '#60a5fa' : '#94a3b8';
                      let stateText = item.on ? '🌞 AWAKE' : '🌙 SLEEP';
                      if (item.brightness !== undefined && item.brightness !== null) {
                          stateText += ` (${item.brightness})`;
                      }
                      wakeHTML = `
                          <div style="font-size:1.05rem; font-weight:700; color:${stateColor}; margin-bottom:4px;">
                              ${stateText}
                          </div>`;
                  }

                  const card = document.createElement('div');
                  card.className = 'tile';
                  card.dataset.name = name;

                  card.innerHTML = `
                      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
                          <strong><i class="fas ${icon}"></i> ${friendly}</strong>
                          <div style="text-align:right; line-height:1.45;">
                              ${wakeHTML}
                              <div id="screen-conn-${name}" style="font-size:0.95rem; font-weight:600; color:${connColor}">
                                  ${connText}
                              </div>
                              ${sshStatus ? `<div style="font-size:0.85rem; opacity:0.8;">${sshStatus}</div>` : ''}
                              ${item.ssh_error ? `<div style="font-size:0.7rem; color:#f87171; opacity:0.85; max-width:220px; word-break:break-all; margin-top:1px;">${item.ssh_error}</div>` : ''}
                          </div>
                      </div>
                      <div class="btn-group">
                          <button class="btn">🌞 Wake</button>
                          <button class="btn">🌙 Sleep</button>
                          <button class="btn test-btn">🔍 Test</button>
                      </div>
                  `;

                  const btns = card.querySelectorAll('button');
                  btns[0].onclick = () => toggleScreen(name, true);
                  btns[1].onclick = () => toggleScreen(name, false);
                  const testBtnEl = card.querySelector('.test-btn');
                  if (testBtnEl) testBtnEl.onclick = () => testSingleScreen(name);

                  container.appendChild(card);
              });
          }

          async function testSingleScreen(name) {
              const card = document.querySelector(`.tile[data-name="${CSS.escape(name)}"]`);
              if (!card) return;

              const testBtn = card.querySelector('.test-btn');
              const statusEl = document.getElementById(`screen-conn-${name}`);

              const originalBtnText = testBtn ? testBtn.textContent : '🔍 Test';

              if (testBtn) {
                  testBtn.textContent = 'Testing...';
                  testBtn.style.opacity = '0.7';
                  testBtn.disabled = true;
              }

              if (statusEl) {
                  statusEl.textContent = 'Testing connection...';
                  statusEl.style.color = '#facc15';
              }

              try {
                  const res = await fetch('/screen_status_json');
                  if (!res.ok) throw new Error('Network error');

                  const data = await res.json();

                  if (data.screens) {
                      Object.assign(S.screenData, data.screens);
                      await new Promise(resolve => setTimeout(resolve, 600));
                      renderScreens();
                  }
              } catch (err) {
                  console.error("Test failed", err);
                  if (statusEl) {
                      statusEl.textContent = 'TEST FAILED';
                      statusEl.style.color = '#f87171';
                  }
              } finally {
                  setTimeout(() => {
                      if (testBtn) {
                          testBtn.textContent = originalBtnText;
                          testBtn.style.opacity = '1';
                          testBtn.disabled = false;
                      }
                  }, 400);
              }
          }

          async function loadScreensWithStatus() {
              try {
                  const response = await fetch('/screen_status_json');
                  if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
                  const data = await response.json();
                  S.screenData = data.screens || {};
                  renderScreens();
              } catch (err) {
                  console.error("Failed to load screen status:", err);
                  const container = document.getElementById('screens-list');
                  if (container) {
                      container.innerHTML = `
                          <div class="tile" style="text-align:center; padding:40px; color:#f87171;">
                              <strong>⚠️ Could not load touchscreen status</strong><br>
                              <small>Check server connection or logs</small>
                          </div>`;
                  }
              }
          }

          function toggleScreen(name, forceOn) {
              getSocket().emit('screen_manual_toggle', { name, on: forceOn });
              setTimeout(() => testSingleScreen(name), 1000);
          }

D.screens = { renderScreens, loadScreensWithStatus };
