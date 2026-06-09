/**
 * PCCS Dark / Light Mode
 */
import { PCCS, getSocket } from './namespace.js';

function updateFooterModeIcon(mode) {
  const icon = document.getElementById('footer-mode-icon');
  if (!icon) return;
  if (mode === 'light') {
    icon.classList.remove('fa-moon');
    icon.classList.add('fa-sun');
  } else {
    icon.classList.remove('fa-sun');
    icon.classList.add('fa-moon');
  }
}

function applyDarkMode(data) {
  const mode = data.mode;
  const isForced = data.forced === true;
  const html = document.documentElement;
  html.classList.remove('dark', 'light');
  html.classList.add(mode);
  updateFooterModeIcon(mode);

  const themeText = document.getElementById('diag-theme-text');
  const icon = document.getElementById('mode-icon');
  if (themeText && icon) {
    if (mode === 'light') {
      themeText.textContent = isForced ? 'Force Dark Mode' : 'Switch to Dark Mode';
      icon.classList.remove('fa-moon');
      icon.classList.add('fa-sun');
    } else {
      themeText.textContent = isForced ? 'Force Light Mode' : 'Switch to Light Mode';
      icon.classList.remove('fa-sun');
      icon.classList.add('fa-moon');
    }
  }
}

function requestInitialDarkMode() {
  const socket = getSocket();
  if (!socket) return;
  if (socket.connected) {
    socket.emit('get_current_dark_mode');
  } else {
    setTimeout(requestInitialDarkMode, 300);
  }
}

function setDarkMode(mode) {
  getSocket().emit('set_global_dark_mode', { mode });
}

function updateActiveModeButton(mode) {
  document.getElementById('btn-dark')?.classList.toggle('active', mode === 'dark');
  document.getElementById('btn-light')?.classList.toggle('active', mode === 'light');
}

PCCS.darkMode = {
  applyDarkMode,
  requestInitialDarkMode,
  setDarkMode,
  updateActiveModeButton,
  register(socket) {
    socket.on('global_dark_mode_update', data => {
      applyDarkMode(data);
      updateActiveModeButton(data.mode);
    });
    socket.on('global_theme_update', data => {
      const select = document.getElementById('quick-theme-select');
      if (select && data.theme) select.value = data.theme;
    });
  },
};