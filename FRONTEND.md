# PCCS Frontend Architecture (Release Build)

**Honest status as of this release:**

The main `templates/index.html` is **still a ~2330 line monolith** (~1870 lines of JavaScript in a single `<script>` tag). The large-scale extraction work described in the original plan has **not yet been completed**.

This document describes the **intended future direction** + the actual safe improvements that were landed for the release.

## What Was Actually Shipped in This Release
- Removed all obvious dev/demo code (`populateVictronDemo`, etc.)
- Deleted the `.bak` file
- Added three small, well-structured shared utilities:
  - `dom-helpers.js`
  - `format-utils.js`
  - `animation-utils.js`
- Improved CSS custom property discipline (base.css as source of truth, with three themes updated as examples)
- Added professional headers and `FRONTEND.md`
- Established the `window.PCCS.*` namespace pattern

The big monolithic script was **not** split. Major domain extractions are planned as follow-on work after the release.

## Intended Future Module Structure

```
static/js/
├── theme-manager.js          # Already extracted (good model)
├── dom-helpers.js            # Safe element access + helpers (shipped)
├── format-utils.js           # Time/duration formatting (shipped)
├── animation-utils.js        # Shared rAF animation primitive (shipped)
├── sun-curve.js              # Bezier + sun/moon + morph animations (shipped in this release)
├── lighting-controller.js    # (Planned)
├── tile-updaters.js          # (Planned) + registry pattern
├── sonos-controller.js       # (Planned)
├── scenes.js                 # (Planned)
├── toasts.js                 # (Planned)
└── pccs-app.js               # (Planned) Thin core + init
```

## Current Load Order (index.html)
1. socket.io
2. theme-manager.js
3. dom-helpers.js, format-utils.js, animation-utils.js, sun-curve.js   ← new/expanded in this release
4. (future domain modules)
5. Large inline script (still the majority of the logic)

## Theme System (Best Practice Partially Applied)
- `base.css` owns the canonical set of CSS custom properties.
- Three themes were updated as examples of the desired minimal-override + `[data-theme]` pattern.
- The other four themes still contain full variable redefinitions (left for post-release cleanup).

## Actual Improvements Landed for This Release
- Removed all dev/demo code (`populateVictronDemo`, `pvd`, `requestVictronUpdate`).
- Deleted `base.css.bak.reorder`.
- Removed many "vibe" comments.
- Added professional release headers + `'use strict'`.
- Introduced three small shared utility modules using the `window.PCCS.*` namespace pattern.
- Improved CSS custom property hygiene (with examples).
- Created this honest `FRONTEND.md`.

**Progress in this release:** The complex sun-curve visualization system (~350 lines of geometry + animation logic) was extracted into `static/js/sun-curve.js`. The main `index.html` dropped from ~2330 → 1955 lines as a result.

Further major extractions (lighting controller, tile updaters, etc.) remain planned for post-release.

## How to Continue the Refactor (Post-Release)
Recommended next step: extract `sun-curve.js` (most self-contained complex subsystem). After that, lighting-controller.js is the highest duplication win.

See the original refactoring plan document in the session notes for the full phased approach.

## Testing Requirements (for future extractions)
- All changes must preserve identical behavior on iPad (landscape + portrait), iPhone, Desktop, Light/Dark + all themes, with/without GPS, offline banner, Sonos, Victron, lighting drag, scenes, and rooftop interlocks.

## Contact / Ownership
Maintained as part of the PCCS project.

---
*Current state: Much cleaner foundation and hygiene, but the monolith is still largely intact.*
