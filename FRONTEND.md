# PCCS Frontend Architecture

**Status (Jun 2026):** `templates/index.html` (~470 lines) and `templates/diag.html` (~250 lines) are HTML shells. Application logic lives in `static/js/` ES modules, bundled for production.

## Build

```bash
cd frontend
npm install
npm run build          # Tailwind CSS + dashboard + diag bundles
npm run watch          # Rebuild JS bundles on source changes
```

Outputs (committed for Pi deploy without Node):

- `static/css/tailwind.css` — purged Tailwind v4 utilities
- `static/js/bundle/dashboard.js` — main UI
- `static/js/bundle/diag.js` — diagnostics page

Requires Node 20+ (`frontend/package.json`). On a machine without system npm, a user-local install under `~/.local/node` works.

## Module layout (sources)

```
static/js/
├── namespace.js           # PCCS root + getSocket()
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
├── app.js                 # Socket wiring + init (dashboard)
├── entries/
│   ├── dashboard.js       # esbuild entry
│   └── diag.js            # esbuild entry
├── bundle/                # Built IIFE bundles (generated)
└── diag/                  # Diagnostics page modules
    ├── namespace.js
    ├── utils.js
    ├── appearance.js
    ├── gps.js
    ├── reeds.js
    ├── screens.js
    ├── phases.js
    ├── toasts.js
    ├── sonos.js
    ├── system.js
    └── app.js
```

## Load order (`index.html`)

1. `css/tailwind.css`, `css/base.css`
2. socket.io
3. `js/bundle/dashboard.js`

## Load order (`diag.html`)

1. `css/base.css`, `css/diag.css`
2. socket.io
3. `js/bundle/diag.js`

## Design rules

- **Server is truth** — UI mirrors `state_update` / `reed_update`; local `PCCS.state` holds interaction flags (`userJustSet`, `currentlyDragging`).
- **No business rules in JS** — rooftop interlock UI disable is UX only; policy engine decides levels.
- **`window.*` shims** — `setScene`, `sonosCommand`, `toggleFullscreen`, etc. remain for inline `onclick` handlers until templates move to `data-action` delegation.

## Still TODO

- [x] Extract `templates/diag.html` the same way (~1,400 lines)
- [x] CSS: finish theme token cleanup (4 themes still full-override)
- [x] ES modules + build step for Tailwind purge
- [ ] Playwright smoke tests for socket-driven UI

## Manual test checklist (after any frontend change)

iPad landscape + portrait, iPhone, desktop; dark + light; base + one heavy theme; offline banner; lighting drag; scenes; rooftop interlock; Sonos/Victron if enabled; GPS sun curve. After JS changes, run `npm run build` in `frontend/`.

---
*Monolith sources preserved in `templates/index.html.monolith.bak` and `templates/diag.html.monolith.bak`.*