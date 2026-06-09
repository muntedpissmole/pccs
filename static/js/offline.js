/**
 * PCCS offline overlay when Socket.IO disconnects.
 */
import { PCCS } from './namespace.js';

let offlineTimeout = null;

function showOfflineBanner() {
  if (offlineTimeout) clearTimeout(offlineTimeout);
  offlineTimeout = setTimeout(() => {
    const overlay = document.getElementById('offline-overlay');
    if (overlay) {
      overlay.classList.remove('hidden');
      overlay.style.pointerEvents = 'auto';
    }
    const mainContent = document.querySelector('.flex-1');
    if (mainContent) mainContent.style.pointerEvents = 'none';
  }, 800);
}

function hideOfflineBanner() {
  if (offlineTimeout) clearTimeout(offlineTimeout);
  offlineTimeout = null;
  const overlay = document.getElementById('offline-overlay');
  if (overlay) overlay.classList.add('hidden');
  const mainContent = document.querySelector('.flex-1');
  if (mainContent) mainContent.style.pointerEvents = 'auto';
}

function register(socket) {
  socket.on('disconnect', showOfflineBanner);
  socket.on('connect_error', showOfflineBanner);
}

PCCS.offline = { show: showOfflineBanner, hide: hideOfflineBanner, register };