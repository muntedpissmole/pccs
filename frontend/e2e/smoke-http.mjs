/**
 * Browser-free smoke checks — validates the e2e server and stub APIs.
 * Use when Playwright/Chromium system libs are not installed yet.
 */
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const PORT = 18765;
const BASE = `http://127.0.0.1:${PORT}`;
const FRONTEND_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

async function fetchJson(pathname) {
  const res = await fetch(`${BASE}${pathname}`);
  assert(res.ok, `${pathname} returned ${res.status}`);
  return res.json();
}

async function fetchText(pathname) {
  const res = await fetch(`${BASE}${pathname}`);
  assert(res.ok, `${pathname} returned ${res.status}`);
  return res.text();
}

const server = spawn(process.execPath, ['e2e/server.mjs'], {
  cwd: FRONTEND_DIR,
  env: { ...process.env, PCCS_E2E_PORT: String(PORT) },
  stdio: ['ignore', 'pipe', 'pipe'],
});

function waitForServer(ms = 10_000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const res = await fetch(`${BASE}/api/version`);
        if (res.ok) return resolve();
      } catch {
        // not ready
      }
      if (Date.now() - start > ms) return reject(new Error('e2e server did not start'));
      setTimeout(tick, 100);
    };
    tick();
  });
}

let failed = false;

try {
  await waitForServer();

  const index = await fetchText('/');
  assert(index.includes('lighting-controls'), 'dashboard HTML missing lighting-controls');
  assert(index.includes('bundle/dashboard.js'), 'dashboard HTML missing bundle script');

  const diag = await fetchText('/diag');
  assert(diag.includes('Diagnostics'), 'diag HTML missing title');
  assert(diag.includes('bundle/diag.js'), 'diag HTML missing bundle script');

  const theme = await fetchJson('/api/current-theme');
  assert(theme.theme === 'base', 'unexpected current-theme fixture');

  const scenes = await fetchJson('/api/scenes');
  assert(Array.isArray(scenes.scenes) && scenes.scenes.length > 0, 'scenes fixture empty');

  const bundle = await fetch(`${BASE}/static/js/bundle/dashboard.js`);
  assert(bundle.ok, 'dashboard bundle not served');

  console.log('HTTP smoke checks passed (6 assertions).');
} catch (err) {
  failed = true;
  console.error('HTTP smoke checks failed:', err.message);
} finally {
  server.kill('SIGTERM');
}

process.exit(failed ? 1 : 0);