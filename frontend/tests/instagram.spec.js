import { test, expect } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
const root = path.resolve(import.meta.dirname, '../..');

test('DM provider reference appears in the private inbox with a content fallback', async ({ page }) => {
  const script = `
from pathlib import Path
import time
from app.instagram import Config, initialize, intake
path = Path(${JSON.stringify(path.join(root, 'frontend/.e2e/revero.sqlite3'))})
initialize(path)
intake(path, {'object':'instagram','entry':[{'id':'100','messaging':[{
    'sender':{'id':'200'},'recipient':{'id':'100'},'timestamp':int(time.time()*1000),
    'message':{'mid':'browser-fixture','attachments':[{'type':'ig_reel','payload':{
        'reel_video_id':'browser-fixture','url':'https://cdn.example.test/reference'}}]}}]}]},
    Config(account_id='100',sender_id='200'))
`;
  const result = spawnSync(path.join(root, 'backend/.venv/bin/python'), ['-c', script], {
    env: { ...process.env, PYTHONPATH: path.join(root, 'backend') }, encoding: 'utf8',
  });
  expect(result.status, result.stderr).toBe(0);
  await page.goto('/');
  const row = page.locator('.saved-list li').filter({ hasText: 'Reference only' });
  await expect(row).toHaveCount(1);
  await expect(row.locator('a')).toHaveCount(0);
  await row.getByRole('button', { name: 'View / add content' }).click();
  await expect(page.getByLabel('Add or replace content')).toBeVisible();
  await page.reload();
  await expect(page.locator('.saved-list li').filter({ hasText: 'Reference only' })).toHaveCount(1);
});
