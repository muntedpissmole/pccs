/**
 * PCCS shared client state (mirrors server desired state + UI interaction flags).
 */
(function () {
  'use strict';

  window.PCCS = window.PCCS || {};
  window.PCCS.state = {
    currentState: {},
    currentModes: {},
    currentReeds: {},
    lightsConfig: [],
    lastRenderConfigHash: '',
    currentlyDragging: new Set(),
    userJustSet: new Set(),
    JUST_SET_DURATION: 2800,
    sceneActivating: false,
    SCENE_RAMP_MS: 4000,
    sceneAnimationCancels: {},
    hasValidGPSFix: false,
    gpsStatusReceived: false,
    lastWeatherUpdate: 0,
    WEATHER_INTERVAL_MS: 3600 * 1000,
    currentScenes: [],
  };
})();