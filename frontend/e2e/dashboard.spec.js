// @ts-check
import { test, expect } from '@playwright/test';
import { setupMockSocketPage } from './helpers/setup-page.js';

test.beforeEach(async ({ page }) => {
  await setupMockSocketPage(page);
});

test('dashboard loads and reveals after theme is ready', async ({ page }) => {
  await page.goto('/');

  await expect(page.locator('html')).toHaveAttribute('data-theme-loaded', 'true', {
    timeout: 10_000,
  });
  await expect(page.locator('#main-content')).toBeVisible();
  await expect(page.locator('.section-title', { hasText: 'Lighting' })).toBeVisible();
});

test('lights_config renders lighting controls', async ({ page }) => {
  await page.goto('/');

  const accent = page.locator('#val-accent');
  const pump = page.locator('#val-pump');

  await expect(accent).toHaveText('42%', { timeout: 10_000 });
  await expect(pump).toHaveText('Off');
  await expect(page.locator('.slider-wrapper[data-name="accent"]')).toBeVisible();
  await expect(page.locator('.relay-toggle[data-name="pump"]')).toBeVisible();
});

test('state_update syncs slider values from socket', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#val-accent')).toHaveText('42%');

  await page.evaluate(() => {
    window.__pccsTestSocket._fire('state_update', { accent: 75, pump: 1 });
  });

  await expect(page.locator('#val-accent')).toHaveText('75%');
  await expect(page.locator('#val-pump')).toHaveText('On');
});

test('scenes grid renders from REST fallback', async ({ page }) => {
  await page.goto('/');

  await expect(page.locator('#scenes-grid .scene-btn')).toHaveCount(1, {
    timeout: 10_000,
  });
  await expect(page.locator('.scene-btn', { hasText: 'Evening' })).toBeVisible();
});

test('offline overlay appears on disconnect and hides on reconnect', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#val-accent')).toHaveText('42%');

  const overlay = page.locator('#offline-overlay');
  await expect(overlay).toHaveClass(/hidden/);

  await page.evaluate(() => window.__pccsTestSocket._disconnect());
  await expect(overlay).not.toHaveClass(/hidden/, { timeout: 2_000 });

  await page.evaluate(() => window.__pccsTestSocket._connect());
  await expect(overlay).toHaveClass(/hidden/, { timeout: 2_000 });
});