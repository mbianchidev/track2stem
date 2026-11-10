import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const api = () => process.env.TRACK2STEM_E2E_API_URL;
const stems = ['vocals', 'drums', 'bass', 'guitar', 'piano', 'other'];

function fixture(seconds = 10) {
  const rate = 44100;
  const frames = seconds * rate;
  const buffer = Buffer.alloc(44 + frames * 4);
  buffer.write('RIFF', 0);
  buffer.writeUInt32LE(buffer.length - 8, 4);
  buffer.write('WAVEfmt ', 8);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(2, 22);
  buffer.writeUInt32LE(rate, 24);
  buffer.writeUInt32LE(rate * 4, 28);
  buffer.writeUInt16LE(4, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write('data', 36);
  buffer.writeUInt32LE(frames * 4, 40);
  for (let frame = 0; frame < frames; frame++) {
    const time = frame / rate;
    const beat = time % .5;
    const pulse = beat < .08 ? .07 * Math.sin(2 * Math.PI * 80 * beat) * Math.exp(-beat * 55) : 0;
    const hat = beat < .025 ? .025 * Math.sin(2 * Math.PI * 6500 * beat) * Math.exp(-beat * 130) : 0;
    const audio = .06 * Math.sin(2 * Math.PI * 110 * time) + .025 * Math.sin(2 * Math.PI * 440 * time) + pulse + hat;
    buffer.writeInt16LE(Math.round(audio * 32767), 44 + frame * 4);
    buffer.writeInt16LE(Math.round(audio * .9 * 32767), 46 + frame * 4);
  }
  return { name: 'studio-demo.wav', mimeType: 'audio/wav', buffer };
}

function pcm(buffer) {
  expect(buffer.toString('ascii', 0, 4)).toBe('RIFF');
  let samples;
  for (let offset = 12; offset + 8 <= buffer.length;) {
    const kind = buffer.toString('ascii', offset, offset + 4);
    const length = buffer.readUInt32LE(offset + 4);
    if (kind === 'fmt ') {
      expect(buffer.readUInt16LE(offset + 8)).toBe(1);
      expect(buffer.readUInt16LE(offset + 10)).toBe(2);
      expect(buffer.readUInt32LE(offset + 12)).toBe(44100);
      expect(buffer.readUInt16LE(offset + 22)).toBe(16);
    }
    if (kind === 'data') samples = buffer.subarray(offset + 8, offset + 8 + length);
    offset += 8 + length + length % 2;
  }
  expect(samples?.length).toBeGreaterThan(0);
  let squares = 0;
  for (let offset = 0; offset < samples.length; offset += 2) squares += (samples.readInt16LE(offset) / 32768) ** 2;
  return { frames: samples.length / 4, rms: Math.sqrt(squares / (samples.length / 2)) };
}

async function submit(page, request, input) {
  await page.getByLabel('Choose audio file', { exact: true }).setInputFiles(input);
  const response = page.waitForResponse((response) =>
    response.url() === `${api()}/upload` && response.request().method() === 'POST', { timeout: 15000 });
  await page.getByRole('button', { name: 'Upload & Process', exact: true }).click();
  const posted = await response;
  expect(posted.ok(), await posted.text()).toBeTruthy();
  const job = await posted.json();
  let completed;
  await expect.poll(async () => {
    const response = await request.get(`${api()}/jobs/${job.id}`);
    expect(response.ok()).toBeTruthy();
    completed = await response.json();
    if (completed.status === 'failed') throw new Error(completed.error);
    return completed.status;
  }, { timeout: 150000, intervals: [300, 500, 1000] }).toBe('completed');
  await expect(page.locator('.completed-summary')).toContainText('Separation complete');
  return completed;
}

async function downloaded(page, locator) {
  const event = page.waitForEvent('download');
  await locator.click();
  const download = await event;
  expect(await download.failure()).toBeNull();
  return { buffer: await fs.readFile(await download.path()), filename: await download.path() };
}

function mediaInfo(filename) {
  const result = spawnSync('ffprobe', ['-v', 'error', '-show_streams', '-show_format', '-of', 'json', filename], { encoding: 'utf8' });
  expect(result.status, result.stderr).toBe(0);
  return JSON.parse(result.stdout);
}

function probe(filename, codec, duration) {
  const info = mediaInfo(filename);
  const audio = info.streams.find((stream) => stream.codec_type === 'audio');
  expect(audio.codec_name).toBe(codec);
  expect(Number(audio.sample_rate)).toBe(44100);
  expect(audio.channels).toBe(2);
  expect(Math.abs(Number(info.format.duration) - duration)).toBeLessThan(.12);
  if (codec === 'mp3') expect(Number(audio.bit_rate)).toBe(320000);
}

test('real upload, practice artifacts, boosted remix and refresh remain usable', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Separate audio into stems' })).toBeVisible();
  await page.getByRole('radio', { name: 'WAV', exact: true }).check();
  for (const name of ['Tempo, key & song sections', 'Click track', 'Guitar tabs', 'Bass tabs', 'Drum tabs & MIDI']) {
    await page.getByRole('checkbox', { name, exact: true }).check();
  }
  const input = fixture();
  const job = await submit(page, request, input);
  expect(Object.keys(job.output_files).sort()).toEqual([...stems].sort());
  for (const stem of stems) {
    const response = await request.get(`${api()}/download/${job.id}/${stem}`);
    expect(response.ok()).toBeTruthy();
    expect(pcm(await response.body()).frames).toBe(441000);
  }
  expect(job.analysis.bpm).toBeGreaterThan(110);
  expect(job.analysis.bpm).toBeLessThan(130);
  const midi = await downloaded(page, page.getByRole('link', { name: 'Drum MIDI', exact: true }));
  expect(midi.buffer.toString('ascii', 0, 4)).toBe('MThd');
  expect(midi.buffer.length).toBeGreaterThan(30);
  const click = await request.get(`${api()}/artifacts/${job.id}/click`);
  expect(pcm(await click.body()).frames).toBe(441000);
  const before = pcm(await (await request.get(`${api()}/download/${job.id}/bass`)).body()).rms;
  expect(before).toBeGreaterThan(.001);
  await page.getByLabel('Bass volume', { exact: true }).focus();
  await page.keyboard.press('End');
  await expect(page.getByLabel('Bass volume', { exact: true })).toHaveValue('400');
  await page.getByRole('button', { name: 'Export mix', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Mix exported.' })).toBeVisible();
  const bass = await downloaded(page, page.getByRole('button', { name: 'Download bass', exact: true }));
  expect(pcm(bass.buffer).rms / before).toBeCloseTo(4, 2);
  await page.getByRole('button', { name: 'Play mix', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Play mix', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Play mix', exact: true })).toBeEnabled();
  await page.reload();
  await expect(page.locator('.completed-summary')).toContainText('Separation complete');
  await expect(page.getByLabel('Bass volume', { exact: true })).toHaveValue('400');
  if (process.env.TRACK2STEM_CAPTURE_README === '1') {
    await page.getByLabel('Choose audio file', { exact: true }).setInputFiles(input);
    await expect(page.getByRole('img', { name: 'Source waveform', exact: true })).toBeVisible();
    await expect(page.getByText('Generating waveform...', { exact: true })).toHaveCount(0);
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: path.resolve('../docs/images/track2stem.png'), fullPage: true });
  }
  expect(errors).toEqual([]);
});

test('isolation preserves backing controls and FLAC/320-kbps MP3 downloads', async ({ page, request }) => {
  await page.goto('/');
  await page.getByRole('radio', { name: /Isolate one/ }).check();
  await page.getByRole('radio', { name: 'FLAC', exact: true }).check();
  const flac = await submit(page, request, fixture(3));
  expect(Object.keys(flac.output_files).sort()).toEqual(['instrumental', 'vocals']);
  await expect(page.getByLabel('Guitar volume', { exact: true })).toBeVisible();
  const vocal = await downloaded(page, page.getByRole('button', { name: 'Download vocals', exact: true }));
  probe(vocal.filename, 'flac', 3);
  await page.getByRole('radio', { name: 'MP3', exact: true }).check();
  await page.getByLabel('Choose stem to isolate').selectOption('drums');
  const mp3 = await submit(page, request, fixture(3));
  expect(Object.keys(mp3.output_files).sort()).toEqual(['backing', 'drums']);
  const backing = await downloaded(page, page.getByRole('button', { name: 'Download backing', exact: true }));
  probe(backing.filename, 'mp3', 3);
});

test('invalid remote sources do not enqueue work', async ({ page, request }) => {
  await page.goto('/');
  const before = await (await request.get(`${api()}/jobs`)).json();
  await page.getByRole('radio', { name: 'YouTube link', exact: true }).check();
  await page.getByLabel('YouTube video URL').fill('https://example.invalid/synthetic.wav');
  const rejected = page.waitForResponse((response) =>
    response.url() === `${api()}/import` && response.request().method() === 'POST', { timeout: 15000 });
  await page.getByRole('button', { name: 'Import & Process', exact: true }).click();
  expect((await rejected).status()).toBe(400);
  await expect(page.getByRole('alert')).toContainText('single YouTube video');
  const after = await (await request.get(`${api()}/jobs`)).json();
  expect(after.length).toBe(before.length);
});

test('authorized synthetic YouTube source completes a live browser import and export', async ({ page, request }, testInfo) => {
  const url = process.env.TRACK2STEM_TEST_YOUTUBE_URL;
  test.skip(!url, 'Live external import requires an explicitly selected authorized synthetic source');
  await page.goto('/');
  await page.getByRole('radio', { name: 'YouTube link', exact: true }).check();
  await page.getByLabel('YouTube video URL').fill(url);
  await page.getByLabel('CPU profile').selectOption('fast');
  await page.getByRole('radio', { name: /Isolate one/ }).check();
  const response = page.waitForResponse((response) =>
    response.url() === `${api()}/import` && response.request().method() === 'POST', { timeout: 15000 });
  await page.getByRole('button', { name: 'Import & Process', exact: true }).click();
  const posted = await response;
  expect(posted.ok(), await posted.text()).toBeTruthy();
  const job = await posted.json();
  let completed;
  await expect.poll(async () => {
    const response = await request.get(`${api()}/jobs/${job.id}`);
    expect(response.ok()).toBeTruthy();
    completed = await response.json();
    if (completed.status === 'failed') throw new Error(completed.error);
    return completed.status;
  }, { timeout: 160000, intervals: [500, 1000, 2000] }).toBe('completed');
  await expect(page.locator('.completed-summary')).toContainText('Separation complete');
  expect(Object.keys(completed.output_files).sort()).toEqual(['instrumental', 'vocals']);
  const result = await downloaded(page, page.getByRole('button', { name: 'Download instrumental', exact: true }));
  const seconds = Number(process.env.TRACK2STEM_TEST_YOUTUBE_SECONDS);
  expect(seconds).toBeGreaterThan(0);
  const raw = await request.get(`${api()}/stems/${completed.id}/other`);
  expect(raw.ok()).toBeTruthy();
  const reference = testInfo.outputPath('decoded-source-clock.wav');
  await fs.writeFile(reference, await raw.body());
  const duration = Number(mediaInfo(reference).format.duration);
  expect(Math.abs(duration - seconds)).toBeLessThan(1);
  // YouTube metadata rounds seconds; export timing must follow the actual decoded sample clock.
  probe(result.filename, 'mp3', duration);
});
