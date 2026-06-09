# PCCS Frontend Architecture

**Status (Jun 2026):** `templates/index.html` (~470 lines) and `templates/diag.html` (~250 lines) are HTML shells. Application logic lives in `static/js/` modules.

## Module layout

```
static/js/
├── pccs-namespace.js      # window.PCCS root
├── state.js               # Shared client state mirror
├── dom-helpers.js         # DOM utilities
├── format-utils.js        # Time/duration formatting
├── animation-utils.js     # rAF animation primitive
├── theme-manager.js       # Theme loading
├── sun-curve.js           # Sun/moon arc visualization
├── offline.js             # Disconnect overlay
├── version.js             # Footer version fetch
├── lighting-controller.js # Sliders, relays, state sync
├── tile-updaters.js       # GPS, sensors, network, weather, clock
├── scenes.js              # Scene buttons
├── dark-mode.js           # Dark/light mode
├── toasts.js              # Toast notifications
├── sonos-controller.js    # Sonos strip
├── victron-tile.js        # Battery/solar tile
├── fullscreen.js          # Fullscreen toggle
├── pccs-app.js            # Socket wiring + init (dashboard)
└── diag/                  # Diagnostics page modules
    ├── namespace.js       # PCCS.diag state root
    ├── utils.js
    ├── appearance.js
    ├── gps.js
    ├── reeds.js
    ├── screens.js
    ├── phases.js
    ├── toasts.js
    ├── sonos.js
    ├── system.js          # Core info + WiFi client
    └── app.js             # Socket wiring + init (diag)
```

## Load order (`index.html`)

1. socket.io
2. pccs-namespace, dom/format/animate helpers, state
3. theme-manager, sun-curve
4. Feature modules (offline → fullscreen)
5. pccs-app.js (boot)

## Design rules

- **Server is truth** — UI mirrors `state_update` / `reed_update`; local `PCCS.state` holds interaction flags (`userJustSet`, `currentlyDragging`).
- **No business rules in JS** — rooftop interlock UI disable is UX only; policy engine decides levels.
- **`window.*` shims** — `setScene`, `sonosCommand`, `toggleFullscreen`, etc. remain for inline `onclick` handlers until templates move to `data-action` delegation.

## Load order (`diag.html`)

1. socket.io, pccs-namespace, format-utils, theme-manager, dark-mode
2. `diag/namespace` → `diag/utils` → feature modules
3. `diag/app.js` (boot)

## Still TODO

- [x] Extract `templates/diag.html` the same way (~1,400 lines)
- [ ] CSS: finish theme token cleanup (4 themes still full-override)
- [ ] Optional: ES modules + build step for Tailwind purge
- [ ] Playwright smoke tests for socket-driven UI

## Manual test checklist (after any frontend change)

iPad landscape + portrait, iPhone, desktop; dark + light; base + one heavy theme; offline banner; lighting drag; scenes; rooftop interlock; Sonos/Victron if enabled; GPS sun curve.

---
*Monolith sources preserved in `templates/index.html.monolith.bak` and `templates/diag.html.monolith.bak`.*