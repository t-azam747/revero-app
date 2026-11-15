import { defineConfig } from '@playwright/test';
import path from 'node:path';
const root = path.resolve(import.meta.dirname, '..');
const apiPort = Number(process.env.REVERO_TEST_API_PORT || 8002);
const database = path.join(root, 'frontend/.e2e/revero.sqlite3');
export default defineConfig({
  testDir: './tests', workers: 1,
  use: { baseURL: 'http://127.0.0.1:5174', browserName: 'chromium' },
  webServer: [
    { command: `${root}/backend/.venv/bin/python -m uvicorn app.main:app --app-dir ${root}/backend --host 127.0.0.1 --port ${apiPort}`,
      url: `http://127.0.0.1:${apiPort}/api/reels`, env: { REVERO_DB_PATH: database, GEMINI_FREE_TIER_CONFIRMED: 'false', TELEGRAM_BOT_TOKEN: '', TELEGRAM_CHAT_ID: '' }, reuseExistingServer: false },
    { command: 'npm run dev', url: 'http://127.0.0.1:5174',
      env: { REVERO_API_TARGET: `http://127.0.0.1:${apiPort}`, REVERO_WEB_PORT: '5174' }, reuseExistingServer: false },
  ],
});
