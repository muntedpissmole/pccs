/**
 * PCCS Application Shell — socket wiring and init.
 */
(function () {
  'use strict';
  const PCCS = window.PCCS;

  const socket = io();
  window.socket = socket;

  function onConnect(sock) {
    PCCS.offline.hide();
    if (typeof registerThemeListener === 'function') registerThemeListener(sock);
    if (typeof loadCurrentTheme === 'function') loadCurrentTheme();
    if (typeof loadQuickThemes === 'function') loadQuickThemes();
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

  PCCS.app = { init: initDom, socket };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDom);
  } else {
    initDom();
  }
})();
