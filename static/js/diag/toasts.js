/**
 * PCCS Diagnostics — Toast test panel
 */
import { PCCS, getSocket } from '../namespace.js';

const D = PCCS.diag;

// TOASTS
function sendCustomToast(type) {
  const title = document.getElementById('toast-title').value.trim() || "Diagnostics Test";
  const message = document.getElementById('toast-message').value.trim() || "Test toast from diagnostics page.";
  getSocket().emit('toast_test', { title, message, type, duration: 5500 });
}

function sendCustomPersistent() {
  const title = document.getElementById('toast-title').value.trim() || "Persistent Toast";
  const message = document.getElementById('toast-message').value.trim() || "This toast stays until dismissed.";
  getSocket().emit('toast_test', { title, message, type: "warning", persistent: true });
}

D.toasts = { sendCustomToast, sendCustomPersistent };