import React from 'react';
import { act, cleanup, render, screen, fireEvent, within } from '@testing-library/react';
import { vi } from 'vitest';
import axios from 'axios';
import App from './App.jsx';

vi.mock('axios', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('./Spectrogram.jsx', () => ({
  default: ({ title, label }) => <div role="img" aria-label={label || title || 'Audio waveform'} />,
}));

const savedState = new Map();
const localStorageMock = {
  getItem: vi.fn((key) => savedState.get(key) ?? null),
  setItem: vi.fn((key, value) => savedState.set(key, String(value))),
  removeItem: vi.fn((key) => savedState.delete(key)),
  clear: vi.fn(() => savedState.clear()),
};
Object.defineProperty(window, 'localStorage', { value: localStorageMock });

const makeJob = (overrides = {}) => ({
  id: 'synthetic-job',
  filename: 'synthetic-demo.wav',
  status: 'pending',
  created_at: '2026-01-01T12:00:00Z',
  ...overrides,
});

const makeFile = () => new File(['synthetic audio'], 'synthetic-demo.wav', { type: 'audio/wav' });

async function renderApp() {
  let result;
  await act(async () => {
    result = render(<App />);
  });
  return result;
}

function chooseFile(file = makeFile()) {
  fireEvent.change(screen.getByLabelText('Choose audio file'), { target: { files: [file] } });
  return file;
}

async function uploadFile() {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Upload & Process' }));
  });
  return axios.post.mock.calls[0][1];
}

describe('App', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    savedState.clear();
    axios.get.mockReset().mockResolvedValue({ data: [] });
    axios.post.mockReset().mockResolvedValue({ data: makeJob() });
    axios.delete.mockReset().mockResolvedValue({ data: { status: 'deleted' } });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  test('renders the source, settings, results, and browser-local history', async () => {
    await renderApp();
    expect(screen.getByRole('link', { name: 'Track2stem workspace' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Separate audio into stems' })).toBeInTheDocument();
    expect(screen.getByText('No audio selected')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Source audio' })).toBeInTheDocument();
    expect(screen.getByRole('form', { name: 'Separation settings' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Separated stems' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Recent jobs' })).toHaveTextContent(/This browser stores job history/i);
    expect(screen.getByText(/Powered by Demucs/i)).toBeInTheDocument();
  });

  test('disables processing until a file is selected', async () => {
    await renderApp();
    expect(screen.getByRole('button', { name: 'Upload & Process' })).toBeDisabled();
    expect(screen.getByText('No stems yet')).toBeInTheDocument();
  });

  test('provides a labeled picker for the existing audio formats', async () => {
    await renderApp();
    expect(screen.getByLabelText('Choose audio file')).toHaveAttribute('type', 'file');
    expect(screen.getByLabelText('Choose audio file')).toHaveAttribute(
      'accept', '.mp3,.wav,.flac,.ogg,.m4a,.aac,audio/*',
    );
    chooseFile();
    expect(screen.getByRole('button', { name: 'Upload & Process' })).toBeEnabled();
    expect(screen.getByRole('img', { name: 'Source waveform' })).toBeInTheDocument();
  });

  test('rejects unsupported files and clears the error after a valid selection', async () => {
    await renderApp();
    chooseFile(new File(['synthetic'], 'synthetic.txt', { type: 'text/plain' }));
    expect(screen.getByRole('alert')).toHaveTextContent(/valid audio file/i);
    expect(screen.getByRole('button', { name: 'Upload & Process' })).toBeDisabled();
    chooseFile();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  test('rejects files larger than the existing 100 MiB limit', async () => {
    await renderApp();
    const file = makeFile();
    Object.defineProperty(file, 'size', { value: 100 * 1024 * 1024 + 1 });
    chooseFile(file);
    expect(screen.getByRole('alert')).toHaveTextContent(/file is too large/i);
    expect(screen.getByRole('button', { name: 'Upload & Process' })).toBeDisabled();
  });

  test('keeps all six stems, MP3, and htdemucs_6s as defaults', async () => {
    await renderApp();
    expect(screen.getByRole('radio', { name: /All 6 stems/i })).toBeChecked();
    expect(screen.getByRole('radio', { name: 'MP3' })).toBeChecked();
    expect(screen.getByLabelText('AI model')).toHaveValue('htdemucs_6s');
    expect(within(screen.getByLabelText('AI model')).getAllByRole('option')).toHaveLength(8);
  });

  test('switches modes and exposes model-dependent isolation choices', async () => {
    await renderApp();
    expect(screen.queryByLabelText('Choose stem to isolate')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('radio', { name: /Isolate one/i }));
    const isolate = screen.getByLabelText('Choose stem to isolate');
    expect(isolate).toHaveValue('vocals');
    expect(within(isolate).getByRole('option', { name: 'Guitar' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('AI model'), { target: { value: 'htdemucs' } });
    expect(screen.getByRole('radio', { name: /All 4 stems/i })).toBeInTheDocument();
    expect(within(isolate).queryByRole('option', { name: 'Guitar' })).not.toBeInTheDocument();
    expect(within(isolate).queryByRole('option', { name: 'Piano' })).not.toBeInTheDocument();
  });

  test('explains a reset when the selected isolated instrument is unavailable in a new model', async () => {
    await renderApp();
    fireEvent.click(screen.getByRole('radio', { name: /Isolate one/i }));
    fireEvent.change(screen.getByLabelText('Choose stem to isolate'), { target: { value: 'guitar' } });
    fireEvent.change(screen.getByLabelText('AI model'), { target: { value: 'htdemucs' } });
    expect(screen.getByLabelText('Choose stem to isolate')).toHaveValue('vocals');
    expect(screen.getByText(/isolation changed to vocals/i)).toBeInTheDocument();
  });

  test.each(['MP3', 'WAV', 'FLAC'])('selects and submits %s without changing upload fields', async (format) => {
    await renderApp();
    const file = chooseFile();
    fireEvent.click(screen.getByRole('radio', { name: format }));
    const formData = await uploadFile();
    expect(axios.post).toHaveBeenCalledWith('/api/upload', expect.any(FormData), expect.any(Object));
    expect(formData.get('file').name).toBe(file.name);
    expect(formData.get('stem_mode')).toBe('all');
    expect(formData.get('isolate_stem')).toBe('vocals');
    expect(formData.get('output_format')).toBe(format.toLowerCase());
    expect(formData.get('model')).toBe('htdemucs_6s');
    expect(formData.get('shifts')).toBe('0');
    expect(formData.get('clip_mode')).toBe('rescale');
    expect(formData.get('overlap')).toBe('0.25');
    expect(formData.has('segment')).toBe(false);
  });

  test('exposes accessible advanced settings and submits their values', async () => {
    await renderApp();
    const toggle = screen.getByRole('button', { name: /Advanced tuning/i });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByLabelText('Segment size')).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(document.getElementById(toggle.getAttribute('aria-controls'))).toBeVisible();
    fireEvent.change(screen.getByLabelText('Segment size'), { target: { value: '8' } });
    fireEvent.change(screen.getByLabelText('Overlap'), { target: { value: '0.5' } });
    fireEvent.change(screen.getByLabelText('Shifts (quality)'), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText('Clip mode'), { target: { value: 'clamp' } });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByLabelText('Segment size')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('radio', { name: /Isolate one/i }));
    fireEvent.change(screen.getByLabelText('Choose stem to isolate'), { target: { value: 'drums' } });
    chooseFile();
    const formData = await uploadFile();
    expect(formData.get('segment')).toBe('8');
    expect(formData.get('overlap')).toBe('0.5');
    expect(formData.get('shifts')).toBe('2');
    expect(formData.get('clip_mode')).toBe('clamp');
    expect(formData.get('stem_mode')).toBe('isolate');
    expect(formData.get('isolate_stem')).toBe('drums');
  });

  test('disables editable controls during upload and exposes actual upload progress', async () => {
    let finishUpload;
    axios.post.mockImplementation(() => new Promise((resolve) => { finishUpload = resolve; }));
    await renderApp();
    chooseFile();
    fireEvent.click(screen.getByRole('button', { name: 'Upload & Process' }));
    expect(screen.getByLabelText('Choose audio file')).toBeDisabled();
    expect(screen.getByLabelText('AI model')).toBeDisabled();
    expect(screen.getByRole('radio', { name: 'WAV' })).toBeDisabled();
    expect(screen.getByRole('progressbar', { name: 'Upload progress' })).toHaveAttribute('value', '0');
    act(() => axios.post.mock.calls[0][2].onUploadProgress({ loaded: 25 }));
    expect(screen.getByRole('progressbar', { name: 'Upload progress' })).not.toHaveAttribute('value');
    act(() => axios.post.mock.calls[0][2].onUploadProgress({ loaded: 25, total: 100 }));
    expect(screen.getByRole('progressbar', { name: 'Upload progress' })).toHaveAttribute('value', '25');
    await act(async () => finishUpload({ data: makeJob() }));
    expect(screen.getByLabelText('Choose audio file')).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Upload & Process' })).toBeDisabled();
  });

  test.each([
    [{ response: { status: 413 } }, /File is too large/i],
    [{ message: 'Synthetic network failure' }, /Synthetic network failure/i],
    [{ response: { data: { error: 'Synthetic server error' } } }, /Synthetic server error/i],
  ])('shows a useful upload failure without losing the selected file', async (failure, message) => {
    axios.post.mockRejectedValue(failure);
    await renderApp();
    chooseFile();
    await uploadFile();
    expect(screen.getByRole('alert')).toHaveTextContent(message);
    expect(screen.getByRole('button', { name: 'Upload & Process' })).toBeEnabled();
  });

  test('recovers the timer and zero progress, then polls the existing endpoints', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T12:01:05Z'));
    const job = makeJob({ status: 'processing' });
    savedState.set('track2stem_current_job', JSON.stringify(job));
    savedState.set('track2stem_start_time', String(Date.now() - 65000));
    savedState.set('track2stem_progress', JSON.stringify({ progress: 0, stage: 'Starting separation' }));
    axios.get.mockImplementation((url) => Promise.resolve({
      data: url === '/api/jobs' ? [] : url.includes('processing-status')
        ? { progress: 43, stage: 'Separating audio' } : job,
    }));
    await renderApp();
    expect(screen.getByRole('progressbar', { name: 'Separation progress' })).toHaveAttribute('value', '0');
    expect(screen.getByRole('timer', { name: 'Elapsed processing time' })).toHaveTextContent('1m 5s');
    expect(screen.getByRole('timer')).toHaveAttribute('aria-live', 'off');
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(axios.get).toHaveBeenCalledWith(`/api/jobs/${job.id}`);
    expect(axios.get).toHaveBeenCalledWith(`/api/processing-status/${job.id}`);
    expect(screen.getByRole('progressbar', { name: 'Separation progress' })).toHaveAttribute('value', '43');
    expect(savedState.get('track2stem_progress')).toContain('Separating audio');
  });

  test.each([
    [['vocals', 'drums', 'bass', 'guitar', 'piano', 'other']],
    [['vocals', 'drums', 'bass', 'other']],
    [['vocals', 'instrumental']],
    [['drums', 'backing']],
  ])('keeps every returned output downloadable alongside its waveform: %j', async (stems) => {
    const job = makeJob({
      status: 'completed',
      processing_time: '12s',
      output_files: Object.fromEntries(stems.map((stem) => [stem, `/synthetic/${stem}.wav`])),
    });
    savedState.set('track2stem_current_job', JSON.stringify(job));
    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    await renderApp();
    const results = within(screen.getByRole('region', { name: 'Separated stems' }));
    expect(results.getByText('Separation complete')).toBeInTheDocument();
    for (const stem of stems) {
      expect(results.getByRole('img', { name: `${stem[0].toUpperCase() + stem.slice(1)} waveform` })).toBeInTheDocument();
      fireEvent.click(results.getByRole('button', { name: `Download ${stem}` }));
      expect(open).toHaveBeenLastCalledWith(`/api/download/${job.id}/${stem}`, '_blank');
    }
  });

  test('shows processor errors and clears the current job without deleting history', async () => {
    const job = makeJob({ status: 'failed', error: 'Synthetic processor failure' });
    savedState.set('track2stem_current_job', JSON.stringify(job));
    savedState.set('track2stem_jobs', JSON.stringify([job]));
    await renderApp();
    expect(screen.getByRole('alert')).toHaveTextContent('Synthetic processor failure');
    fireEvent.click(screen.getByRole('button', { name: 'Clear current job' }));
    expect(savedState.has('track2stem_current_job')).toBe(false);
    expect(savedState.has('track2stem_progress')).toBe(false);
    expect(savedState.has('track2stem_start_time')).toBe(false);
    expect(savedState.get('track2stem_jobs')).toContain(job.id);
    expect(screen.getByLabelText('Choose audio file')).toHaveFocus();
  });

  test('shows the ten most recent jobs and removes completed metadata without cancelling', async () => {
    const jobs = Array.from({ length: 12 }, (_, index) => makeJob({
      id: `synthetic-${index}`,
      filename: `synthetic-${index}.wav`,
      status: 'completed',
      output_files: { vocals: '/synthetic/vocals.wav' },
    }));
    axios.get.mockResolvedValue({ data: jobs });
    await renderApp();
    const history = within(screen.getByRole('region', { name: 'Recent jobs' }));
    expect(history.queryByText('synthetic-0.wav')).not.toBeInTheDocument();
    expect(history.queryByText('synthetic-1.wav')).not.toBeInTheDocument();
    expect(history.getAllByRole('button', { name: /Remove .* from history/ })).toHaveLength(10);
    fireEvent.click(history.getByRole('button', { name: 'Remove synthetic-11.wav from history' }));
    expect(history.queryByText('synthetic-11.wav')).not.toBeInTheDocument();
    expect(savedState.get('track2stem_jobs')).not.toContain('"synthetic-11"');
    expect(axios.delete).not.toHaveBeenCalled();
    expect(history.getByRole('heading', { name: 'Recent jobs' })).toHaveFocus();
  });

  test('keeps best-effort cancellation for a processing history entry', async () => {
    const job = makeJob({ status: 'processing' });
    savedState.set('track2stem_jobs', JSON.stringify([job]));
    await renderApp();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: `Remove ${job.filename} from history` }));
    });
    expect(axios.delete).toHaveBeenCalledWith(`/api/jobs/${job.id}`);
    expect(savedState.get('track2stem_jobs')).toBe('[]');
  });

  test('reports a history refresh failure while retaining saved metadata', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    axios.get.mockRejectedValue(new Error('Synthetic network failure'));
    savedState.set('track2stem_jobs', JSON.stringify([makeJob({ status: 'completed' })]));
    await renderApp();
    expect(screen.getByRole('alert')).toHaveTextContent(/Could not refresh recent jobs/i);
    expect(within(screen.getByRole('region', { name: 'Recent jobs' })).getByText('synthetic-demo.wav')).toBeInTheDocument();
  });

  test.each(['status', 'progress'])('reports a transient %s failure and recovers on the next poll', async (endpoint) => {
    vi.useFakeTimers();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const job = makeJob({ status: 'processing' });
    savedState.set('track2stem_current_job', JSON.stringify(job));
    let failNext = true;
    axios.get.mockImplementation((url) => {
      if (url === '/api/jobs') return Promise.resolve({ data: [] });
      const progressRequest = url.includes('/processing-status/');
      if (failNext && progressRequest === (endpoint === 'progress')) {
        failNext = false;
        return Promise.reject(new Error('Synthetic connection failure'));
      }
      return Promise.resolve({
        data: progressRequest ? { progress: 12, stage: 'Separating audio' } : job,
      });
    });
    await renderApp();
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    const message = endpoint === 'progress' ? /Live progress is unavailable/ : /Could not refresh this job/;
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: 'Separation progress' })).toBeInTheDocument();
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(screen.queryByText(message)).not.toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: 'Separation progress' })).toHaveAttribute('value', '12');
  });
});
