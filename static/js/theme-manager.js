/**
 * PCCS Theme Manager
 * Handles dynamic loading of visual themes and current theme sync.
 * Extracted from the monolithic inline script in index.html for better
 * maintainability, caching, and separation of concerns.
 */
let currentThemeFile = null;

export function applyTheme(themeFile) {
  if (!themeFile) themeFile = 'base';
  currentThemeFile = themeFile;
  document.documentElement.setAttribute('data-theme', themeFile);

  // Remove any previously injected theme stylesheets
  document.querySelectorAll('link[data-theme-link]').forEach(link => link.remove());

  if (themeFile === 'base') {
    document.documentElement.setAttribute('data-theme-loaded', 'true');
    return;
  }

  const cssPath = `/static/css/themes/${themeFile}.css?v=${Date.now()}`;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = cssPath;
  link.dataset.themeLink = 'true';

  link.onload = () => document.documentElement.setAttribute('data-theme-loaded', 'true');
  link.onerror = () => document.documentElement.setAttribute('data-theme-loaded', 'true');

  document.head.appendChild(link);
}

export function registerThemeListener(socketArg) {
  const sock = socketArg || globalThis.socket;
  if (!sock) {
    // Socket not ready yet — will be retried when called again after window.socket is set
    console.debug('[ThemeManager] registerThemeListener called before socket available');
    return;
  }
  sock.off('global_theme_update');
  sock.on('global_theme_update', function(data) {
    if (data && data.theme) applyTheme(data.theme);
  });
}

export async function loadCurrentTheme() {
  try {
    const res = await fetch('/api/current-theme');
    const data = await res.json();
    applyTheme(data.theme || 'base');
  } catch (e) {
    console.error('Failed to load current theme', e);
    applyTheme('base');
  }
}

export async function loadQuickThemes() {
  try {
    const res = await fetch('/api/themes');
    const data = await res.json();
    const select = document.getElementById('quick-theme-select');
    if (!select) return;

    select.innerHTML = '';
    data.themes.forEach(t => {
      const opt = document.createElement('option');
      opt.value = t.file;
      opt.textContent = t.name;
      select.appendChild(opt);
    });

    const cur = await (await fetch('/api/current-theme')).json();
    if (cur.theme) select.value = cur.theme;
  } catch (e) {
    console.warn('Failed to load quick themes', e);
  }
}

export function changeTheme(theme) {
  const sock = globalThis.socket;
  if (sock) {
    sock.emit('set_global_theme', { theme });
  } else {
    console.warn('[ThemeManager] changeTheme called but no socket available yet');
  }
}

// Expose a small public API
globalThis.PCCSTheme = {
  apply: applyTheme,
  loadCurrent: loadCurrentTheme,
  loadQuick: loadQuickThemes,
  change: changeTheme,
  registerListener: registerThemeListener,
  getCurrent: () => currentThemeFile
};

// Backwards compatibility for existing inline code during transition
globalThis.applyTheme = applyTheme;
globalThis.registerThemeListener = registerThemeListener;
globalThis.loadCurrentTheme = loadCurrentTheme;
globalThis.loadQuickThemes = loadQuickThemes;
globalThis.changeTheme = changeTheme;

// Auto-register listener if socket is already on window (defensive for load order)
function tryRegisterListener() {
  if (globalThis.socket) {
    registerThemeListener(globalThis.socket);
    return true;
  }
  return false;
}

if (!tryRegisterListener()) {
  // Poll briefly in case the inline script sets window.socket right after this script runs
  let attempts = 0;
  const iv = setInterval(() => {
    attempts++;
    if (tryRegisterListener() || attempts > 20) {
      clearInterval(iv);
    }
  }, 50);
}

// Optional: auto-load current theme on DOM ready if not already handled elsewhere
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    if (!document.documentElement.hasAttribute('data-theme-loaded')) {
      loadCurrentTheme();
    }
  });
} else {
  if (!document.documentElement.hasAttribute('data-theme-loaded')) {
    loadCurrentTheme();
  }
}