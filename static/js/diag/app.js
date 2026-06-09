/**
 * PCCS Diagnostics — boot and socket wiring
 */
import { PCCS, getSocket } from '../namespace.js';
import { registerThemeListener } from '../theme-manager.js';

const D = PCCS.diag;
const S = D.state;

function initSocket() {
  const socket = io();
  globalThis.socket = socket;
  return socket;
}

function registerHandlers() {
  const socket = getSocket();
  socket.on('gps_update', D.gps.updateGPS);
  socket.on('reed_diag_update', D.reeds.updateReeds);
  socket.on('phase_update', D.phases.updatePhase);
  socket.on('phase_diag_update', D.phases.updatePhaseForced);
  socket.on('screen_update', (data) => {
    if (!data.name) return;
    if (!S.screenData[data.name]) S.screenData[data.name] = {};
    S.screenData[data.name] = { ...S.screenData[data.name], ...data };
    D.screens.renderScreens();
  });
  socket.on('dhcp_update', (data) => {
    if (data.dhcp_clients) {
      D.system.renderCoreInfo({ ...S.lastSystemInfo, dhcp_clients: data.dhcp_clients });
    }
  });
  socket.on('sonos_speakers', (data) => {
    if (data.enabled === false) {
      document.getElementById('sonos-section').style.display = 'none';
      return;
    }
    D.sonos.renderPlayers(data.speakers, data.current);
  });
  socket.on('sonos_update', (state) => {
    if (state && state.speaker) {
      S.sonosStates[state.speaker] = state;
      if (S.sonosSpeakers.length > 0) {
        D.sonos.renderPlayers(S.sonosSpeakers, S.activeSonos);
      }
    }
  });
}

function exposeShims() {
  globalThis.setDarkMode = (mode) => PCCS.darkMode.setDarkMode(mode);
  globalThis.changeTheme = (theme) => globalThis.PCCSTheme.change(theme);
  globalThis.forceNoFix = (enabled) => D.gps.forceNoFix(enabled);
  globalThis.forcePhase = (phase) => D.phases.forcePhase(phase);
  globalThis.clearPhaseForce = () => D.phases.clearPhaseForce();
  globalThis.sendCustomToast = (type) => D.toasts.sendCustomToast(type);
  globalThis.sendCustomPersistent = () => D.toasts.sendCustomPersistent();
  globalThis.switchActiveSonosPlayer = (name) => D.sonos.switchActive(name);
  globalThis.sonosDiagCommand = (name, cmd) => D.sonos.command(name, cmd);
  globalThis.setVolumeDiag = (name, vol) => D.sonos.setVolume(name, vol);
  globalThis.toggleMuteDiag = (name) => D.sonos.toggleMute(name);
  globalThis.scanWifiNetworks = () => D.system.scanWifi();
  globalThis.onWifiNetworkChanged = () => D.system.onWifiChanged();
  globalThis.connectToSelectedWifi = () => D.system.connectWifi();
}

function boot() {
  fetch('/api/version')
    .then(r => r.json())
    .then(v => {
      const verEl = document.getElementById('app-version');
      if (verEl && v.version) verEl.textContent = `v${v.version}`;
    })
    .catch(() => {});

  D.appearance.loadThemes();
  D.screens.loadScreensWithStatus();
  D.system.loadCoreInfo();

  fetch('/reed_json')
    .then(r => r.json())
    .then(data => {
      D.reeds.renderReeds(data);
      D.reeds.updateReeds(data);
    })
    .catch(err => console.error('Failed to load reeds:', err));

  fetch('/gps_json').then(r => r.json()).then(D.gps.updateGPS).catch(() => {});

  fetch('/screen_json')
    .then(r => r.json())
    .then(data => {
      const basic = data.screens || {};
      S.screenData = { ...basic, ...S.screenData };
      D.screens.renderScreens();
    })
    .catch(err => console.warn('Could not load screens:', err));
}

function init() {
  initSocket();
  registerThemeListener();
  PCCS.darkMode.register(getSocket());
  registerHandlers();
  exposeShims();

  setInterval(() => {
    const el = document.getElementById('core-info');
    if (el && el.offsetParent !== null) D.system.loadCoreInfo();
  }, 8000);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
}

init();