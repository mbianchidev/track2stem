import { createNativeStorage, initializeNativeHost } from './native-host.js';

test('DAW project state survives reopen without touching browser storage', () => {
  const states = [];
  window.localStorage.clear();
  const first = createNativeStorage({ version: 1, storage: {} }, (state) => states.push(state));
  first.setItem('track2stem_settings', JSON.stringify({ model: 'htdemucs', workers: '2' }));
  first.setItem('track2stem_current_job', JSON.stringify({ id: 'synthetic-job', status: 'completed' }));
  const reopened = createNativeStorage(states.at(-1), () => {});
  expect(JSON.parse(reopened.getItem('track2stem_settings'))).toEqual({ model: 'htdemucs', workers: '2' });
  expect(JSON.parse(reopened.getItem('track2stem_current_job')).id).toBe('synthetic-job');
  expect(window.localStorage.getItem('track2stem_settings')).toBeNull();
  reopened.removeItem('track2stem_current_job');
  expect(reopened.getItem('track2stem_current_job')).toBeNull();
  expect(() => createNativeStorage({ version: 99, storage: {} }, () => {})).toThrow(/version/i);
});

test('native exports reject missing cached files and non-local destinations before navigation', async () => {
  const ready = vi.fn();
  const failed = vi.fn();
  const messages = [];
  const receive = (event) => messages.push(event.detail);
  const report = vi.spyOn(console, 'error').mockImplementation(() => {});
  const request = vi.fn().mockResolvedValue({ ok: false, status: 404 });
  vi.stubGlobal('fetch', request);
  window.IPlugSendMsg = vi.fn();
  window.addEventListener('track2stem-native-message', receive);
  try {
    initializeNativeHost(ready, failed);
    const apiBase = 'http://127.0.0.1:23456/abcdefghijklmnopqrstuvwxyz012345/api';
    const message = { type: 'host_ready', version: 1, generation: 0, api_base: apiBase, state: { version: 1, storage: {} } };
    window.SAMFD(0, 0, btoa(JSON.stringify(message)));
    await vi.waitFor(() => expect(ready).toHaveBeenCalledOnce());
    await window.track2stemHost.download(`${apiBase}/download/synthetic-job/bass`);
    expect(request).toHaveBeenCalledWith(`${apiBase}/download/synthetic-job/bass`, {
      method: 'HEAD', signal: expect.any(AbortSignal),
    });
    expect(messages.at(-1)).toMatchObject({ type: 'native_error', message: expect.stringMatching(/Export failed.*404.*Import the source again/) });
    request.mockClear();
    await window.track2stemHost.download('https://example.invalid/synthetic.wav');
    expect(request).not.toHaveBeenCalled();
    expect(messages.at(-1).message).toContain('non-local export');
    expect(failed).not.toHaveBeenCalled();
  } finally {
    window.removeEventListener('track2stem-native-message', receive);
    delete window.track2stemHost;
    delete window.IPlugSendMsg;
    vi.unstubAllGlobals();
    report.mockRestore();
  }
});
