import { defineConfig } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const external = process.env.TRACK2STEM_TEST_URL;
const data = process.env.TRACK2STEM_E2E_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'track2stem-e2e-'));
process.env.TRACK2STEM_E2E_DIR = data;
process.env.TRACK2STEM_E2E_API_URL ||= external ? `${external.replace(/\/$/, '')}/api` : 'http://127.0.0.1:20080/api';
const python = process.env.TRACK2STEM_TEST_PYTHON || 'python3.14';
const quote = (value) => `'${value.replaceAll("'", "'\\''")}'`;
const storage = {
  UPLOAD_FOLDER: path.join(data, 'uploads'),
  OUTPUT_FOLDER: path.join(data, 'outputs'),
  MODEL_FOLDER: process.env.TRACK2STEM_TEST_MODELS || path.join(data, 'models'),
};

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.e2e.mjs',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180000,
  expect: { timeout: 15000 },
  use: {
    baseURL: external || 'http://127.0.0.1:20173',
    viewport: { width: 1440, height: 1000 },
    reducedMotion: 'reduce',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: { args: ['--mute-audio'] },
  },
  webServer: external ? undefined : [
    { command: `${quote(python)} processor/app.py`, cwd: root, url: 'http://127.0.0.1:20500/health',
      env: { ...storage, PORT: '20500', FLASK_DEBUG: 'false' }, reuseExistingServer: false },
    { command: 'go run .', cwd: path.join(root, 'backend'), url: 'http://127.0.0.1:20080/api/health',
      env: { ...storage, PORT: '20080', PROCESSOR_URL: 'http://127.0.0.1:20500' }, reuseExistingServer: false },
    { command: 'npm start -- --host 127.0.0.1 --port 20173 --strictPort', cwd: path.join(root, 'frontend'),
      url: 'http://127.0.0.1:20173', env: { VITE_API_URL: process.env.TRACK2STEM_E2E_API_URL }, reuseExistingServer: false },
  ],
});
