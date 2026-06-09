import fs from 'node:fs';
import { defineConfig } from '@playwright/test';

const port = process.env.PCCS_E2E_PORT || '8765';
const baseURL = `http://127.0.0.1:${port}`;

const systemChromium = '/usr/bin/chromium';
const launchOptions = fs.existsSync(systemChromium)
  ? { executablePath: systemChromium }
  : undefined;

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.js',
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  use: {
    baseURL,
    trace: 'on-first-retry',
    launchOptions,
  },
  webServer: {
    command: 'node e2e/server.mjs',
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 15_000,
  },
});