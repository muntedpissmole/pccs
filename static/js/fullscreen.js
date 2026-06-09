/**
 * PCCS Fullscreen Toggle
 * Extracted from templates/index.html
 */
import { PCCS } from './namespace.js';

function toggleFullscreen() {
  const icon = document.getElementById('fullscreen-icon');

  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen().then(() => {
      icon.classList.remove('fa-expand');
      icon.classList.add('fa-compress');
    }).catch(err => console.warn('Fullscreen failed:', err));
  } else {
    document.exitFullscreen().then(() => {
      icon.classList.remove('fa-compress');
      icon.classList.add('fa-expand');
    });
  }
}

// Optional: Sync icon if user exits fullscreen with ESC key

document.addEventListener('fullscreenchange', () => {
  const icon = document.getElementById('fullscreen-icon');
  if (icon) {
    if (document.fullscreenElement) {
      icon.classList.remove('fa-expand');
      icon.classList.add('fa-compress');
    } else {
      icon.classList.remove('fa-compress');
      icon.classList.add('fa-expand');
    }
  }
});

PCCS.fullscreen = { toggleFullscreen };