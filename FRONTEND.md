# PCCS Frontend Architecture

**Status (Jun 2026):** `templates/index.html` (~470 lines) and `templates/diag.html` (~250 lines) are HTML shells. Application logic lives in `static/js/` ES modules, bundled for production.

## Build

```bash
cd frontend
./run install
./run run build          # Tailwind CSS + dashboard + diag bundles
./run run watch          # Rebuild JS bundles on source changes
```

Outputs (committed for Pi deploy without Node):

- `static/css/tailwind.css` — purged Tailwind v4 utilities
- `static/js/bundle/dashboard.js` — main UI
- `static/js/bundle/diag.js` — diagnostics page

Requires Node 20+ (`frontend/package.json`). On the Pi, Node lives at `~/.local/node/bin` — use the `frontend/run` helper (or add that directory to your `PATH`).

```bash
# Optional one-time shell fix (then npm/npx work everywhere):
echo 'export PATH="$HOME/.local/node/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

## E2E smoke tests (Playwright)

**One-time system setup** (Playwright cannot launch Chromium without these libs):

```bash
cd frontend
sudo ./scripts/install-playwright-deps.sh
```

Then:

```bash
cd frontend
./run install
./run exec playwright install chromium   # once per machine
./run run test:e2e                       # 6 browser tests
```

**No browser / libs not installed yet?** Run the HTTP-only smoke check:

```bash
./run run test:smoke
```

Without `./run`, prefix commands manually: `PATH="$HOME/.local/node/bin:$PATH" npm …`

Tests use a lightweight Node server (`frontend/e2e/server.mjs`) with stub REST APIs and an injected mock Socket.IO client — no Python backend or hardware required. `test:e2e` covers dashboard theme reveal, lighting render/`state_update`, scenes grid, offline overlay, and diag page boot.

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
- [x] Playwright smoke tests for socket-driven UI

## Manual test checklist (after any frontend change)

iPad landscape + portrait, iPhone, desktop; dark + light; base + one heavy theme; offline banner; lighting drag; scenes; rooftop interlock; Sonos/Victron if enabled; GPS sun curve. After JS changes, run `npm run build` in `frontend/`.

---
*Monolith sources preserved in `templates/index.html.monolith.bak` and `templates/diag.html.monolith.bak`.*