/**
 * PCCS Application Shell — socket wiring and init.
 */
(function () {
  'use strict';
  const PCCS = window.PCCS;

  function initSocket() {
    const socket = io();
    window.socket = socket;
    return socket;
  }

  function onConnect(socket) {
    PCCS.offline.hide();
    if (typeof registerThemeListener === 'function') registerThemeListener(socket);
    if (typeof loadCurrentTheme === 'function') loadCurrentTheme();
    if (typeof loadQuickThemes === 'function') loadQuickThemes();
    PCCS.scenes.loadScenes();
    PCCS.version.loadVersion();
    PCCS.sonos.requestSonosState();
    socket.emit('get_network_status');
    socket.emit('get_victron_state');
    socket.emit('get_reeds');
    PCCS.darkMode.requestInitialDarkMode();
    setTimeout(() => {
      fetch('/api/network_status').then(r => r.json()).then(PCCS.tiles.updateNetworkTile).catch(() => {});
    }, 1200);
    setTimeout(() => {
      if (PCCS.sunCurve) PCCS.sunCurve.updateCurveGeometry();
    }, 50);
  }

  function registerHandlers(socket) {
    PCCS.offline.register(socket);
    PCCS.darkMode.register(socket);
    PCCS.toasts.register(socket);
    PCCS.sonos.register(socket);

    socket.on('lights_config', c => PCCS.lighting.onLightsConfig(c));
    socket.on('state_update', s => PCCS.lighting.onStateUpdate(s));
    socket.on('reed_update', p => PCCS.lighting.onReedUpdate(p));
    socket.on('sensor_update', d => PCCS.tiles.updateSensors(d));
    socket.on('gps_update', d => PCCS.tiles.updateGPS(d));
    socket.on('phase_update', d => PCCS.tiles.updatePhaseInfo(d));
    socket.on('network_update', d => PCCS.tiles.updateNetworkTile(d));
    socket.on('victron_update', d => PCCS.victron.updatePowerTile(d));

    socket.on('connect', () => onConnect(socket));
  }

  function init() {
    const socket = initSocket();
    registerHandlers(socket);

    if (PCCS.sunCurve && typeof PCCS.sunCurve.init === 'function') {
      PCCS.sunCurve.init();
    }

    PCCS.sonos.bindProgressSeek();
    PCCS.lighting.initResize();

    window.toggleFullscreen = PCCS.fullscreen.toggleFullscreen;
    window.sonosCommand = PCCS.sonos.sonosCommand;
    window.toggleSonosMute = PCCS.sonos.toggleSonosMute;
    window.sonosVolumeChange = PCCS.sonos.sonosVolumeChange;
    window.setDarkMode = PCCS.darkMode.setDarkMode;
    window.setScene = PCCS.scenes.setScene;
    window.toggleGlobalDarkMode = function () {
      const html = document.documentElement;
      const newMode = html.classList.contains('light') ? 'dark' : 'light';
      socket.emit('set_global_dark_mode', { mode: newMode });
    };

    window.onload = function () {
      PCCS.tiles.updateClock();
      setInterval(PCCS.tiles.updateClock, 10000);
      if (typeof registerThemeListener === 'function') registerThemeListener(socket);
      if (typeof loadCurrentTheme === 'function') loadCurrentTheme();
      PCCS.version.loadVersion();
      PCCS.sonos.startProgressUpdater();
    };
  }

  PCCS.app = { init };
  document.addEventListener('DOMContentLoaded', init);
})();
