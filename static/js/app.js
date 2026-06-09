/**
 * PCCS Application Shell — socket wiring and init.
 */
import { PCCS } from './namespace.js';
import { registerThemeListener, loadCurrentTheme, loadQuickThemes } from './theme-manager.js';

const socket = io();
globalThis.socket = socket;

function onConnect(sock) {
  PCCS.offline.hide();
  registerThemeListener(sock);
  loadCurrentTheme();
  loadQuickThemes();
  PCCS.scenes.loadScenes();
  PCCS.version.loadVersion();
  PCCS.sonos.requestSonosState();
  sock.emit('get_network_status');
  sock.emit('get_victron_state');
  sock.emit('get_reeds');
  PCCS.darkMode.requestInitialDarkMode();
  setTimeout(() => {
    fetch('/api/network_status').then(r => r.json()).then(PCCS.tiles.updateNetworkTile).catch(() => {});
  }, 1200);
  setTimeout(() => {
    if (PCCS.sunCurve) PCCS.sunCurve.updateCurveGeometry();
  }, 50);
}

function registerHandlers(sock) {
  PCCS.offline.register(sock);
  PCCS.darkMode.register(sock);
  PCCS.toasts.register(sock);
  PCCS.sonos.register(sock);

  sock.on('lights_config', c => PCCS.lighting.onLightsConfig(c));
  sock.on('state_update', s => PCCS.lighting.onStateUpdate(s));
  sock.on('reed_update', p => PCCS.lighting.onReedUpdate(p));
  sock.on('sensor_update', d => PCCS.tiles.updateSensors(d));
  sock.on('gps_update', d => PCCS.tiles.updateGPS(d));
  sock.on('phase_update', d => PCCS.tiles.updatePhaseInfo(d));
  sock.on('network_update', d => PCCS.tiles.updateNetworkTile(d));
  sock.on('victron_update', d => PCCS.victron.updatePowerTile(d));

  sock.on('connect', () => onConnect(sock));
}

registerHandlers(socket);

function initDom() {
  if (PCCS.sunCurve && typeof PCCS.sunCurve.init === 'function') {
    PCCS.sunCurve.init();
  }

  PCCS.sonos.bindProgressSeek();
  PCCS.lighting.initResize();

  globalThis.toggleFullscreen = PCCS.fullscreen.toggleFullscreen;
  globalThis.sonosCommand = PCCS.sonos.sonosCommand;
  globalThis.toggleSonosMute = PCCS.sonos.toggleSonosMute;
  globalThis.sonosVolumeChange = PCCS.sonos.sonosVolumeChange;
  globalThis.setDarkMode = PCCS.darkMode.setDarkMode;
  globalThis.setScene = PCCS.scenes.setScene;
  globalThis.toggleGlobalDarkMode = function () {
    const html = document.documentElement;
    const newMode = html.classList.contains('light') ? 'dark' : 'light';
    socket.emit('set_global_dark_mode', { mode: newMode });
  };

  globalThis.onload = function () {
    PCCS.tiles.updateClock();
    setInterval(PCCS.tiles.updateClock, 10000);
    registerThemeListener(socket);
    loadCurrentTheme();
    PCCS.version.loadVersion();
    PCCS.sonos.startProgressUpdater();
  };

}

PCCS.app = { init: initDom, socket };
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initDom);
} else {
  initDom();
}