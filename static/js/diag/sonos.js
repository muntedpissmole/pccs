/**
 * PCCS Diagnostics — Sonos diagnostics
 */
import { PCCS, getSocket } from '../namespace.js';

const D = PCCS.diag;
const S = D.state;
const formatTime = PCCS.format.time;

  // ====================== SONOS DIAGNOSTICS ======================
      function renderPlayers(speakers, active) {
          S.sonosSpeakers = speakers || [];
          S.activeSonos = active;

          const select = document.getElementById('active-sonos-player');
          select.innerHTML = '<option value="">— No player selected —</option>';

          S.sonosSpeakers.forEach(name => {
              const opt = document.createElement('option');
              opt.value = name;
              opt.textContent = name;
              if (name === active) opt.selected = true;
              select.appendChild(opt);
          });

          const container = document.getElementById('sonos-players-grid');
          container.innerHTML = '';

          if (S.sonosSpeakers.length === 0) {
              container.innerHTML = `
                  <div class="tile" style="grid-column: 1 / -1; text-align:center; padding:40px; opacity:0.7;">
                      <i class="fas fa-music fa-3x mb-4"></i><br>
                      No Sonos players discovered
                  </div>`;
              return;
          }

          S.sonosSpeakers.forEach(name => {
              const state = S.sonosStates[name] || { track: "Nothing playing", artist: "", album_art: "", is_playing: false, volume: 30, mute: false, position: 0, duration: 0 };
              const isActive = name === active;
              const hasArt = !!state.album_art;
              const progress = state.duration > 0 ? Math.min(100, Math.round((state.position / state.duration) * 100)) : 0;

              const card = document.createElement('div');
              card.className = `tile ${isActive ? 'border-2 border-sky-400' : ''}`;
              card.innerHTML = `
                  <div style="height:180px; background-image: url('${hasArt ? state.album_art : 'https://placehold.co/600x600/1f2937/4fc3f7?text=No+Art'}'); 
                              background-size: cover; background-position: center; border-radius: 12px 12px 0 0; position: relative;">
                      <div style="position:absolute; inset:0; background: linear-gradient(to bottom, transparent, rgba(0,0,0,0.85)); border-radius: 12px 12px 0 0;"></div>
                      ${isActive ? `<div style="position:absolute; top:12px; right:12px; background:rgba(16,185,129,0.9); color:white; padding:4px 12px; border-radius:9999px; font-size:0.8rem; font-weight:700;">ACTIVE</div>` : ''}
                  </div>

                  <div style="padding:16px;">
                      <div style="display:flex; justify-content:space-between; align-items:start; margin-bottom:12px;">
                          <strong style="font-size:1.15rem;">${name}</strong>
                          <button onclick="switchActiveSonosPlayer('${name}')" class="btn ${isActive ? 'success' : ''}" style="padding:6px 14px; font-size:0.9rem;">
                              ${isActive ? '✓ Active' : 'Set Active'}
                          </button>
                      </div>

                      <div style="margin-bottom:12px; min-height:50px;">
                          <div style="font-weight:600;">${state.track}</div>
                          <div style="opacity:0.75; font-size:0.95rem;">${state.artist || '—'}</div>
                      </div>

                      <div style="margin:12px 0 16px;">
                          <div style="height:5px; background:rgba(255,255,255,0.2); border-radius:9999px; overflow:hidden;">
                              <div style="width:${progress}%; height:100%; background:#4fc3f7;"></div>
                          </div>
                          <div style="display:flex; justify-content:space-between; font-size:0.8rem; margin-top:4px; opacity:0.75;">
                              <span>${PCCS.format.time(state.position)}</span>
                              <span>${PCCS.format.time(state.duration)}</span>
                          </div>
                      </div>

                      <div style="display:flex; align-items:center; gap:10px;">
                          <i onclick="toggleMuteDiag('${name}')" class="fas fa-volume-${state.mute ? 'mute' : 'high'} cursor-pointer" style="font-size:1.4rem; width:32px;"></i>
                          <input type="range" min="0" max="100" value="${state.volume}" 
                                 oninput="setVolumeDiag('${name}', this.value)" style="flex:1; accent-color:#4fc3f7;">
                          <span style="font-family:monospace; width:42px; text-align:right;">${state.volume}%</span>
                      </div>

                      <div style="margin-top:14px; display:flex; gap:8px; justify-content:center;">
                          <button onclick="sonosDiagCommand('${name}', 'previous')" class="btn">⏮</button>
                          <button onclick="sonosDiagCommand('${name}', 'playpause')" class="btn" style="min-width:52px;">
                              ${state.is_playing ? '⏸' : '▶'}
                          </button>
                          <button onclick="sonosDiagCommand('${name}', 'next')" class="btn">⏭</button>
                      </div>
                  </div>
              `;
              container.appendChild(card);
          });
      }

      function command(name, command) {
          getSocket().emit('sonos_command', { speaker: name, command: command });
      }

      function setVolume(name, volume) {
          getSocket().emit('sonos_command', { speaker: name, command: 'volume', value: parseInt(volume) });
      }

      function toggleMute(name) {
          getSocket().emit('sonos_command', { speaker: name, command: 'mute' });
      }

      function switchActive(name) {
          if (name) getSocket().emit('sonos_switch_speaker', { name });
      }

D.sonos = { renderPlayers, command, setVolume, toggleMute, switchActive };
