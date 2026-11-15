import { test, expect } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
const root = path.resolve(import.meta.dirname, '../..');

async function prepare(request) {
  const code = `Actions_${Date.now()}`;
  const reel = await (await request.post('/api/reels', { data: { url: `https://www.instagram.com/reel/${code}/` } })).json();
  const job = await (await request.post(`/api/reels/${reel.id}/content`, { multipart: { caption: 'Practice joins tomorrow. Review indexes next week.' } })).json();
  const script = `
from pathlib import Path
from app.extraction import connect, run_one
path = Path(${JSON.stringify(path.join(root, 'frontend/.e2e/revero.sqlite3'))})
with connect(path) as db:
    db.execute('UPDATE extraction_jobs SET available_at=99999999999 WHERE id != ?', (${job.id},))
class FixtureProvider:
    def extract(self, *args):
        return {'summary': 'Prepare for database interviews.', 'topics': ['SQLite'],
          'suggestions': [{'text': 'Practice joins', 'source_index': 0}, {'text': 'Review indexes', 'source_index': 1}],
          'date_candidates': [{'original_text': 'tomorrow', 'source_index': 0}, {'original_text': 'next week', 'source_index': 1}],
          'sources': [{'excerpt': 'Practice joins tomorrow.', 'origin': 'caption', 'timestamp_seconds': None}, {'excerpt': 'Review indexes next week.', 'origin': 'caption', 'timestamp_seconds': None}]}
assert run_one(path, FixtureProvider())
`;
  const result = spawnSync(path.join(root, 'backend/.venv/bin/python'), ['-c', script], { env: { ...process.env, PYTHONPATH: path.join(root, 'backend') }, encoding: 'utf8' });
  expect(result.status, result.stderr).toBe(0);
  return { code, reel, job };
}

test('track, confirm and correct dates, reload, complete and dismiss', async ({ page, request }) => {
  const { code, reel, job } = await prepare(request);
  await page.goto('/');
  await page.locator('.saved-list li').filter({ hasText: code }).getByRole('button').click();
  await expect(page.getByRole('button', { name: 'Track this' })).toHaveCount(2);
  await page.getByRole('button', { name: 'Track this' }).first().click();
  await expect(page.getByRole('button', { name: 'Tracked', exact: true })).toHaveCount(1);
  const repeated = await (await request.post('/api/actions', { data: { job_id: job.id, suggestion_index: 0 } })).json();
  expect(repeated.created).toBe(false);
  await page.getByRole('button', { name: 'Track this' }).click();
  await page.getByRole('navigation', { name: 'Workspace' }).getByRole('button', { name: 'Actions', exact: true }).click();
  const first = page.getByRole('article', { name: 'Practice joins', exact: true }).filter({ hasText: code });
  const second = page.getByRole('article', { name: 'Review indexes', exact: true }).filter({ hasText: code });
  await expect(first).toContainText('No confirmed due date');
  await expect(first).toContainText('“tomorrow”');
  await expect(first).not.toContainText('next week');
  await first.getByLabel('Due date (optional)').fill('2027-01-20');
  await first.getByRole('button', { name: 'Confirm date' }).click();
  await expect(first).toContainText('Confirmed due date: 2027-01-20');
  await first.getByLabel('Due date (optional)').fill('2027-01-22');
  await first.getByRole('button', { name: 'Confirm date' }).click();
  await expect(first).toContainText('Confirmed due date: 2027-01-22');
  await page.reload();
  await page.getByRole('navigation', { name: 'Workspace' }).getByRole('button', { name: 'Actions', exact: true }).click();
  await expect(first).toContainText('Confirmed due date: 2027-01-22');
  await expect(second).toContainText('No confirmed due date');
  await page.screenshot({ path: '/tmp/revero-m3-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/revero-m3-mobile.png', fullPage: true });
  await first.getByRole('button', { name: 'Done', exact: true }).click();
  await expect(first).toHaveCount(0);
  await second.getByRole('button', { name: 'Dismiss', exact: true }).click();
  await expect(second).toHaveCount(0);
  const filters = page.getByLabel('Filter actions');
  await filters.getByRole('button', { name: 'Done', exact: true }).click();
  await expect(first).toBeVisible();
  await filters.getByRole('button', { name: 'Dismissed', exact: true }).click();
  await expect(second).toBeVisible();
  const all = await (await request.get(`/api/actions?status=all&reel_id=${reel.id}`)).json();
  expect(all).toHaveLength(2);
});

test('tracking and date failures retain user input and allow retry', async ({ page, request }) => {
  const { code } = await prepare(request);
  await page.goto('/');
  await page.locator('.saved-list li').filter({ hasText: code }).getByRole('button').click();
  await page.route('**/api/actions', route => route.abort());
  await page.getByRole('button', { name: 'Track this' }).first().click();
  await expect(page.locator('.track-error')).toBeVisible();
  await page.unroute('**/api/actions');
  await page.getByRole('button', { name: 'Track this' }).first().click();
  await expect(page.getByRole('button', { name: 'Tracked', exact: true })).toBeVisible();
  await page.getByRole('navigation', { name: 'Workspace' }).getByRole('button', { name: 'Actions', exact: true }).click();
  const card = page.getByRole('article', { name: 'Practice joins', exact: true }).filter({ hasText: code });
  await card.getByLabel('Due date (optional)').fill('2027-04-10');
  await page.route('**/api/actions/*', route => route.abort());
  await card.getByRole('button', { name: 'Confirm date' }).click();
  await expect(card.getByRole('alert')).toBeVisible();
  await expect(card.getByLabel('Due date (optional)')).toHaveValue('2027-04-10');
  await page.unroute('**/api/actions/*');
  await card.getByRole('button', { name: 'Confirm date' }).click();
  await expect(card).toContainText('Confirmed due date: 2027-04-10');
  await card.getByRole('button', { name: 'Remove date' }).click();
  await expect(card).toContainText('No confirmed due date');
});
