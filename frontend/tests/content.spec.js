import { test, expect } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
const root = path.resolve(import.meta.dirname, '../..');

// Inject a deterministic provider only into the isolated test database.
// No production mock mode exists and these checks never call Gemini.
function processJob(id, fail = false, video = false) {
  const script = `
from app.extraction import run_one, connect, ProviderError
from pathlib import Path
path = Path(${JSON.stringify(path.join(root, 'frontend/.e2e/revero.sqlite3'))})
with connect(path) as db:
    db.execute('UPDATE extraction_jobs SET available_at=99999999999 WHERE id != ?', (${id},))
class FixtureProvider:
    def extract(self, caption, video_path, mime):
        if ${fail ? 'True' : 'False'}: raise ProviderError('Test extraction failed. Retry is available.')
        return {'summary': 'A blue screen.' if ${video ? 'True' : 'False'} else 'Practice joins.', 'topics': ['Practice'], 'suggestions': [], 'date_candidates': [], 'sources': [{'excerpt': 'A blue screen.' if ${video ? 'True' : 'False'} else caption, 'origin': 'video' if ${video ? 'True' : 'False'} else 'caption', 'timestamp_seconds': 0 if ${video ? 'True' : 'False'} else None}]}
assert run_one(path, FixtureProvider())
`;
  const result = spawnSync(path.join(root, 'backend/.venv/bin/python'), ['-c', script], { env: { ...process.env, PYTHONPATH: path.join(root, 'backend') }, encoding: 'utf8' });
  expect(result.status, result.stderr).toBe(0);
}

async function saveAndOpen(page, code) {
  await page.goto('/');
  await page.getByLabel('Instagram Reel link').fill(`https://www.instagram.com/reel/${code}/`);
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.getByText('Saved to your inbox.', { exact: true })).toBeVisible();
  await page.locator('.saved-list li').filter({ hasText: code }).getByRole('button').click();
  await expect(page.getByRole('button', { name: 'Attach & queue' })).toBeVisible();
}

test('caption attachment, failure, retry, sourced result and reload', async ({ page, request }) => {
  const code = `Caption_${Date.now()}`;
  await saveAndOpen(page, code);
  await page.getByLabel('Add or replace content').fill('Practice SQLite joins.');
  await page.getByRole('button', { name: 'Attach & queue' }).click();
  await expect(page.locator('.content-status')).toHaveText('Queued');
  const reels = await (await request.get('/api/reels')).json();
  const reel = reels.find(row => row.shortcode === code);
  let content = await (await request.get(`/api/reels/${reel.id}/content`)).json();
  processJob(content.job.id, true);
  await expect(page.getByRole('button', { name: 'Retry extraction' })).toBeVisible();
  await page.getByRole('button', { name: 'Retry extraction' }).click();
  await expect(page.locator('.content-status')).toHaveText('Queued');
  processJob(content.job.id);
  await expect(page.getByText('Caption-only takeaway')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Practice joins.' })).toBeVisible();
  await expect(page.locator('blockquote')).toContainText('Practice SQLite joins.');
  await page.reload();
  await page.locator('.saved-list li').filter({ hasText: code }).getByRole('button').click();
  await expect(page.getByText('Caption-only takeaway')).toBeVisible();
  await page.screenshot({ path: '/tmp/revero-m2-caption.png', fullPage: true });
});

test('actual MP4 upload and video evidence', async ({ page, request }) => {
  const code = `Video_${Date.now()}`;
  await saveAndOpen(page, code);
  await page.getByLabel('Or attach a clip').setInputFiles(path.join(root, 'backend/tests/fixtures/blue.mp4'));
  await page.getByRole('button', { name: 'Attach & queue' }).click();
  await expect(page.locator('.content-status')).toHaveText('Queued');
  const reels = await (await request.get('/api/reels')).json();
  const reel = reels.find(row => row.shortcode === code);
  const { job } = await (await request.get(`/api/reels/${reel.id}/content`)).json();
  processJob(job.id, false, true);
  await expect(page.getByText('Video takeaway', { exact: true })).toBeVisible();
  await expect(page.locator('blockquote cite')).toContainText('video at 0:00');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/revero-m2-mobile.png', fullPage: true });
});
