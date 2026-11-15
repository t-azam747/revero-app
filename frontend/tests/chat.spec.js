import { test, expect } from '@playwright/test';

test('save, duplicate, invalid input, reload, and mobile layout', async ({ page }) => {
  const code = `Browser_${Date.now()}`;
  await page.goto('/');
  const input = page.getByLabel('Instagram Reel link');
  await input.fill(`https://www.instagram.com/reel/${code}/?igsh=first`);
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.getByText('Saved to your inbox.', { exact: true })).toBeVisible();
  await expect(input).toHaveValue('');
  await input.fill(`https://www.instagram.com/reel/${code}/?igsh=second`);
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.getByText('Already saved. This Reel is in your inbox.')).toBeVisible();
  await expect(page.locator('.saved-list li').filter({ hasText: code })).toHaveCount(1);
  await input.fill('https://example.com/not-a-reel');
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.locator('.message.error')).toContainText('Enter an HTTPS Instagram Reel link');
  await expect(input).toHaveValue('https://example.com/not-a-reel');
  await page.reload();
  await expect(page.locator('.saved-list li').filter({ hasText: code })).toHaveCount(1);
  await page.screenshot({ path: '/tmp/revero-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(input).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/revero-mobile.png', fullPage: true });
});

test('load failure offers retry and submission failure retains input', async ({ page }) => {
  await page.route('**/api/reels', route => route.abort());
  await page.goto('/');
  await expect(page.getByRole('alert')).toContainText('Couldn’t load your Reels');
  await page.unroute('**/api/reels');
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await page.route('**/api/reels', route => route.abort());
  await page.getByLabel('Instagram Reel link').fill('https://www.instagram.com/reel/Offline/');
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.locator('.message.error')).toContainText('Couldn’t reach Revero');
  await expect(page.getByLabel('Instagram Reel link')).toHaveValue('https://www.instagram.com/reel/Offline/');
});
