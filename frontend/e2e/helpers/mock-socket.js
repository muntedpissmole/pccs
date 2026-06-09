/**
 * Injected before page scripts — replaces socket.io with a deterministic fixture.
 */
(() => {
  const FIXTURE = {
    lightsConfig: [
      {
        name: 'accent',
        label: 'Accent',
        type: 'pwm',
        icon: 'fa-lightbulb',
        has_mode: false,
      },
      {
        name: 'pump',
        label: 'Pump',
        type: 'relay',
        icon: 'fa-faucet',
        has_mode: false,
      },
    ],
    state: { accent: 42, pump: 0 },
  };

  function createSocket() {
    const handlers = new Map();

    const socket = {
      connected: true,
      on(event, fn) {
        if (!handlers.has(event)) handlers.set(event, []);
        handlers.get(event).push(fn);
      },
      off(event, fn) {
        if (!handlers.has(event)) return;
        if (fn) {
          handlers.set(
            event,
            handlers.get(event).filter((f) => f !== fn),
          );
        } else {
          handlers.delete(event);
        }
      },
      emit() {},
      _fire(event, ...args) {
        for (const fn of handlers.get(event) || []) fn(...args);
      },
      _disconnect() {
        socket.connected = false;
        socket._fire('disconnect');
      },
      _connect() {
        socket.connected = true;
        socket._fire('connect');
      },
    };

    queueMicrotask(() => {
      socket._fire('connect');
      socket._fire('lights_config', FIXTURE.lightsConfig);
      socket._fire('state_update', { ...FIXTURE.state });
      socket._fire('reed_update', { states: {} });
      socket._fire('global_dark_mode_update', { mode: 'dark', manual: false });
      socket._fire('sonos_update', { enabled: false });
    });

    return socket;
  }

  window.io = () => {
    const socket = createSocket();
    window.__pccsTestSocket = socket;
    return socket;
  };
})();