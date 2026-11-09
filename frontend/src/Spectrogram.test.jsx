import React from 'react';
import { act, cleanup, render, screen } from '@testing-library/react';
import { vi } from 'vitest';
import Spectrogram from './Spectrogram.jsx';

const samples = new Float32Array([-1, 0.5, 1, -0.5]);
const decodedAudio = { getChannelData: () => samples };
let decodeAudioData;
let close;
let fetchAudio;
let context;
let resize;
let disconnect;
let canvasWidth;

async function renderWaveform(props = {}) {
  let result;
  await act(async () => {
    result = render(<Spectrogram {...props} />);
  });
  return result;
}

describe('Spectrogram', () => {
  beforeEach(() => {
    canvasWidth = 300;
    decodeAudioData = vi.fn().mockResolvedValue(decodedAudio);
    close = vi.fn().mockResolvedValue(undefined);
    fetchAudio = vi.fn().mockResolvedValue({
      ok: true,
      arrayBuffer: async () => new ArrayBuffer(8),
    });
    vi.stubGlobal('AudioContext', vi.fn(function () {
      this.decodeAudioData = decodeAudioData;
      this.close = close;
    }));
    vi.stubGlobal('fetch', fetchAudio);
    vi.stubGlobal('devicePixelRatio', 1);
    disconnect = vi.fn();
    vi.stubGlobal('ResizeObserver', vi.fn(function (callback) {
      resize = callback;
      this.observe = vi.fn();
      this.disconnect = disconnect;
    }));
    context = {
      fillRect: vi.fn(),
      beginPath: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      stroke: vi.fn(),
    };
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context);
    vi.spyOn(HTMLCanvasElement.prototype, 'getBoundingClientRect').mockImplementation(
      () => ({ width: canvasWidth, height: 80 }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  test('renders its title and a labeled canvas without an audio source', async () => {
    await renderWaveform({ title: 'Source waveform', height: 80 });
    expect(screen.getByText('Source waveform')).toBeInTheDocument();
    const canvas = screen.getByRole('img', { name: 'Source waveform' });
    expect(canvas).toHaveAttribute('width', '600');
    expect(canvas).toHaveAttribute('height', '80');
    expect(canvas).toBeVisible();
    expect(fetchAudio).not.toHaveBeenCalled();
  });

  test('labels a compact stem waveform without duplicating its visible heading', async () => {
    await renderWaveform({ label: 'Vocals waveform', height: 52 });
    expect(screen.getByRole('img', { name: 'Vocals waveform' })).toBeVisible();
    expect(screen.queryByText('Vocals waveform')).not.toBeInTheDocument();
  });

  test('draws real samples across the lane without clipping full-scale peaks', async () => {
    await renderWaveform({ audioUrl: '/synthetic/vocals.wav', label: 'Vocals waveform', height: 80 });
    const canvas = screen.getByRole('img', { name: 'Vocals waveform' });
    expect(canvas).toHaveAttribute('width', '300');
    expect(canvas).toHaveAttribute('height', '80');
    const bars = context.fillRect.mock.calls.slice(1);
    expect(bars).toHaveLength(300);
    for (const [, y, , barHeight] of bars) {
      expect(y).toBeGreaterThanOrEqual(4);
      expect(y + barHeight).toBeLessThanOrEqual(76);
    }
    expect(bars.some(([, , , barHeight]) => barHeight > 0)).toBe(true);
    expect(close).toHaveBeenCalledTimes(1);
  });

  test('uses the selected local file without fetching it', async () => {
    const audioFile = { arrayBuffer: vi.fn().mockResolvedValue(new ArrayBuffer(8)) };
    await renderWaveform({ audioFile, title: 'Source waveform' });
    expect(audioFile.arrayBuffer).toHaveBeenCalledOnce();
    expect(fetchAudio).not.toHaveBeenCalled();
    expect(decodeAudioData).toHaveBeenCalledOnce();
    expect(close).toHaveBeenCalledOnce();
  });

  test('resizes for device pixels without downloading or decoding the audio again', async () => {
    vi.stubGlobal('devicePixelRatio', 2);
    await renderWaveform({ audioUrl: '/synthetic/vocals.wav', label: 'Vocals waveform', height: 52 });
    const canvas = screen.getByRole('img', { name: 'Vocals waveform' });
    expect(canvas).toHaveAttribute('width', '600');
    expect(canvas).toHaveAttribute('height', '104');
    canvasWidth = 450;
    act(() => resize());
    expect(canvas).toHaveAttribute('width', '900');
    expect(fetchAudio).toHaveBeenCalledOnce();
    expect(decodeAudioData).toHaveBeenCalledOnce();
  });

  test('loads and draws a different source when the output URL changes', async () => {
    const { rerender } = await renderWaveform({ audioUrl: '/synthetic/vocals.wav' });
    await act(async () => {
      rerender(<Spectrogram audioUrl="/synthetic/drums.wav" />);
    });
    expect(fetchAudio).toHaveBeenCalledTimes(2);
    expect(fetchAudio).toHaveBeenLastCalledWith('/synthetic/drums.wav', expect.objectContaining({
      signal: expect.any(AbortSignal),
    }));
    expect(decodeAudioData).toHaveBeenCalledTimes(2);
    expect(close).toHaveBeenCalledTimes(2);
  });

  test('announces loading and closes its context if unmounted during decoding', async () => {
    let finishDecoding;
    decodeAudioData.mockImplementation(() => new Promise((resolve) => { finishDecoding = resolve; }));
    const { unmount } = await renderWaveform({ audioUrl: '/synthetic/vocals.wav' });
    expect(screen.getByRole('status')).toHaveTextContent('Generating waveform');
    unmount();
    expect(close).toHaveBeenCalledOnce();
    await act(async () => finishDecoding(decodedAudio));
    expect(context.fillRect).not.toHaveBeenCalled();
    expect(close).toHaveBeenCalledOnce();
  });

  test('does not replace a new waveform with an older decode that finishes late', async () => {
    let finishOldDecoding;
    decodeAudioData.mockImplementationOnce(() => new Promise((resolve) => { finishOldDecoding = resolve; }));
    const { rerender } = await renderWaveform({ audioUrl: '/synthetic/old.wav' });
    await act(async () => rerender(<Spectrogram audioUrl="/synthetic/new.wav" />));
    const drawCount = context.fillRect.mock.calls.length;
    await act(async () => finishOldDecoding(decodedAudio));
    expect(context.fillRect).toHaveBeenCalledTimes(drawCount);
    expect(close).toHaveBeenCalledTimes(2);
  });

  test.each(['fetch', 'decode'])('reports %s failures and always closes the audio context', async (failure) => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    if (failure === 'fetch') {
      fetchAudio.mockResolvedValue({ ok: false, status: 404 });
    } else {
      decodeAudioData.mockRejectedValue(new Error('Synthetic unsupported codec'));
    }
    await renderWaveform({ audioUrl: '/synthetic/vocals.wav', label: 'Vocals waveform' });
    expect(screen.getByRole('status')).toHaveTextContent(/Waveform unavailable/i);
    expect(screen.getByRole('status')).toHaveTextContent(/process or download/i);
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(close).toHaveBeenCalledOnce();
  });

  test('disconnects its resize observer when unmounted', async () => {
    const { unmount } = await renderWaveform({ audioUrl: '/synthetic/vocals.wav' });
    unmount();
    expect(disconnect).toHaveBeenCalledOnce();
  });
});
