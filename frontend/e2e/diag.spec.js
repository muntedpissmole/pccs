// @ts-check
import { test, expect } from '@playwright/test';
import { setupMockSocketPage } from './helpers/setup-page.js';

test.beforeEach(async ({ page }) => {
  await setupMockSocketPage(page);
});

test('diag page loads and shows core sections', async ({ page }) => {
  await page.goto('/diag');

  await expect(page.locator('h1', { hasText: 'Diagnostics' })).toBeVisible();
  await expect(page.locator('#appearance')).toBeVisible();
  await expect(page.locator('#app-version')).toContainText('e2e-test', {
    timeout: 10_000,
  });
});