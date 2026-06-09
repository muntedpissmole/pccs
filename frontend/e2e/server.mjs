/**
 * Lightweight static server for Playwright smoke tests.
 * Serves real templates/assets with stub REST endpoints — no Python backend required.
 */
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '../..');
const PORT = Number(process.env.PCCS_E2E_PORT || 8765);

const API_FIXTURES = {
  '/api/current-theme': { theme: 'base' },
  '/api/themes': {
    themes: [{ file: 'base', name: 'Base' }],
  },
  '/api/version': { version: 'e2e-test', full: 'e2e-test', built: '2026-01-01' },
  '/api/scenes': {
    scenes: [
      {
        key: 'evening',
        name: 'Evening',
        icon: 'fa-moon',
        description: 'Warm evening lights',
        all_off: false,
      },
    ],
  },
  '/api/network_status': {
    internet: { connected: true },
    wlan: { connected: true, ssid: 'test-wifi' },
  },
  '/api/current-dark-mode': { mode: 'dark' },
  '/api/system_info': {
    hostname: 'pccs-test',
    uptime: '1h',
    dhcp_clients: [],
  },
  '/api/wifi/scan': {
    networks: [],
    current: { connected: false },
  },
  '/reed_json': { states: {}, forced: {} },
  '/gps_json': { fix: false, lat: null, lon: null, phase: 'Day' },
  '/screen_json': { screens: {} },
  '/screen_status_json': { screens: {} },
};

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2',
  '.webmanifest': 'application/manifest+json',
};

function renderTemplate(relPath) {
  const filePath = path.join(ROOT, relPath);
  let html = fs.readFileSync(filePath, 'utf8');
  html = html.replace(
    /\{\{\s*url_for\('static',\s*filename='([^']+)'\)\s*\}\}/g,
    '/static/$1',
  );
  return html;
}

function sendJson(res, payload, status = 200) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(payload));
}

function sendFile(res, filePath) {
  if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    res.writeHead(404);
    res.end('Not found');
    return;
  }
  const ext = path.extname(filePath);
  res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' });
  fs.createReadStream(filePath).pipe(res);
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url || '/', `http://127.0.0.1:${PORT}`);
  const pathname = url.pathname;

  if (req.method === 'GET' && pathname === '/') {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(renderTemplate('templates/index.html'));
    return;
  }

  if (req.method === 'GET' && pathname === '/diag') {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(renderTemplate('templates/diag.html'));
    return;
  }

  if (req.method === 'GET' && API_FIXTURES[pathname]) {
    sendJson(res, API_FIXTURES[pathname]);
    return;
  }

  if (pathname.startsWith('/static/')) {
    const rel = pathname.slice('/static/'.length);
    const filePath = path.join(ROOT, 'static', rel);
    if (!filePath.startsWith(path.join(ROOT, 'static'))) {
      res.writeHead(403);
      res.end('Forbidden');
      return;
    }
    sendFile(res, filePath);
    return;
  }

  res.writeHead(404);
  res.end('Not found');
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`PCCS e2e server listening on http://127.0.0.1:${PORT}`);
});