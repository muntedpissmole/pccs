/**
 * PCCS Version Footer
 * Extracted from templates/index.html
 */
import { PCCS } from './namespace.js';

const S = PCCS.state;

async function loadVersion() {
  try {
    const res = await fetch('/api/version');
    const data = await res.json();
    const versionEl = document.getElementById('footer-version');
    if (versionEl) {
      versionEl.textContent = `v${data.version || '?.?.?'}`;
    }
  } catch (e) {
    console.warn('Could not load version', e);
    document.getElementById('footer-version').textContent = 'v?.?.?';
  }
}

PCCS.version = { loadVersion };