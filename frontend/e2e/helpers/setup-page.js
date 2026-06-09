// @ts-check
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const mockSocketPath = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  'mock-socket.js',
);

/** Block real socket.io — it overwrites our mock and the e2e server has no Socket.IO backend. */
export async function setupMockSocketPage(page) {
  await page.route('**/socket.io.min.js', (route) => route.abort());
  await page.addInitScript({ path: mockSocketPath });
}