import { test, expect } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
const root = path.resolve(import.meta.dirname, '../..');

async function prepare(request) {
  const code = `Insights_${Date.now()}`;
  const topic = `IndexHints${Date.now()}`;
  const caption = `${topic}: Practice SQLite joins next week for backend interviews.`;
  const reel = await (await request.post('/api/reels', { data: { url: `https://www.instagram.com/reel/${code}/` } })).json();
  const job = await (await request.post(`/api/reels/${reel.id}/content`, { multipart: { caption } })).json();
  const script = `
from pathlib import Path
from app.extraction import connect, run_one
path = Path(${JSON.stringify(path.join(root, 'frontend/.e2e/revero.sqlite3'))})
with connect(path) as db:
    db.execute('UPDATE extraction_jobs SET available_at=99999999999 WHERE id != ?', (${job.id},))
class FixtureProvider:
    def extract(self, caption, *args):
        return {'summary': caption, 'topics': [${JSON.stringify(topic)}], 'suggestions': [{'text': 'Practice SQLite joins', 'source_index': 0}], 'date_candidates': [{'original_text':'next week','source_index':0}], 'sources': [{'excerpt':caption,'origin':'caption','timestamp_seconds':None}]}
assert run_one(path, FixtureProvider())
`;
  const result = spawnSync(path.join(root, 'backend/.venv/bin/python'), ['-c', script], { env: { ...process.env, PYTHONPATH: path.join(root, 'backend') }, encoding: 'utf8' });
  expect(result.status, result.stderr).toBe(0);
  return { code, topic, reel, job };
}

async function open(page, name) {
  await page.getByRole('navigation', { name: 'Workspace' }).getByRole('button', { name, exact: true }).click();
}

test('ask retrieves actual saved evidence, no-match, and cited answer rendering', async ({ page, request }) => {
  const { code, topic, reel } = await prepare(request);
  await page.goto('/'); await open(page, 'Ask');
  const input = page.getByLabel('Question about your saves');
  await input.fill(`What did I save about ${topic}?`);
  await page.getByRole('button', { name: 'Ask Revero', exact: true }).click();
  await expect(page.getByText('Related excerpts found.', { exact: false })).toBeVisible();
  await expect(page.locator('.answer-sources')).toContainText(topic);
  const { sources } = await (await request.get(`/api/search?q=${topic}`)).json();
  expect(sources[0].url).toBe(reel.url);
  // Only the provider response is simulated here; retrieval above used the real API.
  await page.route('**/api/ask', route => route.fulfill({ json: { status: 'answered', answer: 'Practice SQLite joins.', claims: [{ text: 'Practice SQLite joins.', source_ids: [sources[0].id] }], sources: [sources[0]] } }));
  await input.fill(`How should I practice ${topic}?`);
  await page.getByRole('button', { name: 'Ask Revero', exact: true }).click();
  const answer = page.locator('.answer-card').last();
  await expect(answer).toContainText('Supporting excerpts');
  await expect(answer.getByRole('link', { name: `Reel / ${code} ↗` })).toHaveAttribute('href', reel.url);
  await expect(answer.getByRole('link', { name: '[Source 1]', exact: true })).toBeVisible();
  await page.screenshot({ path: '/tmp/revero-m4-desktop.png', fullPage: true });
  await page.unroute('**/api/ask');
  await input.fill(`quasarNotSaved${Date.now()}`);
  await page.getByRole('button', { name: 'Ask Revero', exact: true }).click();
  await expect(page.getByText('I couldn’t find that in your saves.', { exact: true })).toBeVisible();
  await page.route('**/api/ask', route => route.abort());
  await input.fill('Retry this question');
  await page.getByRole('button', { name: 'Ask Revero', exact: true }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(input).toHaveValue('Retry this question');
});

test('digest ranks interests, shows independently tracked deadlines, and preserves settings', async ({ page, request }) => {
  const { code, topic, reel, job } = await prepare(request);
  const action = await (await request.post('/api/actions', { data: { job_id: job.id, suggestion_index: 0 } })).json();
  const preview = await (await request.get('/api/digest')).json();
  await request.patch(`/api/actions/${action.id}`, { data: { due_date: preview.preview.local_date } });
  await page.goto('/'); await open(page, 'Digest');
  await page.getByLabel('Your interests (separate with commas)').fill(topic);
  await page.getByLabel('Daily delivery time (Asia/Kolkata)').fill('20:45');
  await page.getByRole('button', { name: 'Save preferences', exact: true }).click();
  await expect(page.getByText('Digest preferences saved.', { exact: true })).toBeVisible();
  await expect(page.locator('.digest-picks li').first()).toContainText(topic);
  await expect(page.locator('.digest-deadlines')).toContainText('Practice SQLite joins');
  await expect(page.getByRole('button', { name: 'Send digest now' })).toBeDisabled();
  await expect(page.getByRole('checkbox')).toBeDisabled();
  await page.locator('.digest-picks li').first().getByText('Why this pick?', { exact: true }).click();
  await expect(page.locator('.digest-picks li').first()).toContainText(`Interest matches: ${topic.toLowerCase()}`);
  await page.screenshot({ path: '/tmp/revero-m5-desktop.png', fullPage: true });
  await page.reload(); await open(page, 'Digest');
  await expect(page.getByLabel('Your interests (separate with commas)')).toHaveValue(topic.toLowerCase());
  await expect(page.getByLabel('Daily delivery time (Asia/Kolkata)')).toHaveValue('20:45');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/revero-m5-mobile.png', fullPage: true });
});

test('uncertain delivery requires review and does not send automatically', async ({ page, request }) => {
  const state = await (await request.get('/api/digest')).json();
  state.preferences.telegram_configured = true;
  state.runs = [{ local_date: state.preview.local_date, state: 'uncertain', error: 'Check the chat.', next_attempt_at: 0 }];
  let sends = 0;
  await page.route('**/api/digest', route => route.fulfill({ json: state }));
  await page.route('**/api/digest/send', route => { sends++; return route.fulfill({ json: { state: 'sent' } }); });
  await page.route('**/resolve', route => { state.runs[0].state = 'sent'; return route.fulfill({ json: { state: 'sent' } }); });
  await page.goto('/'); await open(page, 'Digest');
  await expect(page.getByRole('button', { name: 'Send digest now' })).toBeEnabled();
  await page.getByRole('button', { name: 'Confirm last part was delivered', exact: true }).click();
  await expect(page.getByText('Today’s delivery: sent', { exact: true })).toBeVisible();
  expect(sends).toBe(0);
});

test('manual send remains separate and repeat clicks cannot start a second request', async ({ page, request }) => {
  const state = await (await request.get('/api/digest')).json();
  state.preferences.telegram_configured = true;
  state.runs = [{ local_date: state.preview.local_date, state: 'sent', next_attempt_at: 0 }];
  state.manual_runs = [];
  let sends = 0;
  let release;
  const held = new Promise(resolve => { release = resolve; });
  await page.route('**/api/digest', route => route.fulfill({ json: state }));
  await page.route('**/api/digest/send', async route => {
    sends++;
    expect(route.request().postDataJSON().request_id).toBeTruthy();
    await held;
    state.manual_runs = [{ run_id: 'manual-ui', local_date: state.preview.local_date, state: 'sent' }];
    await route.fulfill({ json: { state: 'sent', run_id: 'manual-ui' } });
  });
  await page.goto('/'); await open(page, 'Digest');
  const button = page.getByRole('button', { name: 'Send digest now' });
  await expect(button).toBeEnabled();
  await button.click();
  await expect(button).toBeDisabled();
  expect(sends).toBe(1);
  release();
  await expect(page.getByText('Delivery status: sent.', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Manual delivery history' })).toBeVisible();
  await expect(button).toBeEnabled();
  expect(sends).toBe(1);
});
