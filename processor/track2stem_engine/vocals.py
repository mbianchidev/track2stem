import numpy as np
from scipy import signal

from .audio import check_cancelled
from .models import get_session


def split_vocals(audio, sample_rate, model_dir, report, cancelled):
    if sample_rate != 44100 or audio.ndim != 2 or audio.shape[1] != 2:
        raise ValueError("Vocal splitting needs stereo 44.1 kHz audio")
    session = get_session("karaoke", model_dir, report, cancelled)
    n_fft, hop, bins, frames = 5120, 1024, 2048, 256
    window_length = hop * (frames - 1)
    trim = n_fft // 2
    useful = window_length - 2 * trim
    stride = useful // 2
    padded = np.pad(audio, ((trim, window_length), (0, 0)))
    output = np.zeros_like(audio)
    total_weights = np.zeros(len(audio), dtype=np.float32)
    weights = np.minimum(np.arange(1, useful + 1), np.arange(useful, 0, -1)).astype(np.float32)
    weights /= weights.max()
    window = signal.windows.hann(n_fft, sym=False).astype(np.float32)
    offsets = range(0, len(audio), stride)
    for index, offset in enumerate(offsets):
        check_cancelled(cancelled)
        tensor = padded[offset:offset + window_length].T.copy()
        _, _, spectrum = signal.stft(tensor, window=window, nperseg=n_fft, noverlap=n_fft - hop,
                                      boundary="zeros", padded=False)
        spectrum *= window.sum()
        packed = np.stack((spectrum.real, spectrum.imag), axis=1).reshape(4, n_fft // 2 + 1, frames)
        features = packed[:, :bins][None].copy()
        features[:, :, :3] = 0
        prediction = session.run(None, {"input": features})[0][0]
        restored = np.zeros((4, n_fft // 2 + 1, frames), dtype=np.float32)
        restored[:, :bins] = prediction
        restored = restored.reshape(2, 2, n_fft // 2 + 1, frames)
        complex_spectrum = (restored[:, 0] + 1j * restored[:, 1]) / window.sum()
        _, reconstructed = signal.istft(complex_spectrum, window=window, nperseg=n_fft,
                                          noverlap=n_fft - hop, boundary=True)
        backing = reconstructed.T[trim:trim + useful] * 1.065
        count = min(useful, len(audio) - offset)
        output[offset:offset + count] += backing[:count] * weights[:count, None]
        total_weights[offset:offset + count] += weights[:count]
        report(74 + int(2 * (index + 1) / len(offsets)), f"Separating lead/backing vocals {index + 1}/{len(offsets)}")
    check_cancelled(cancelled)
    if np.any(total_weights <= 0):
        raise RuntimeError("Vocal separation left uncovered audio")
    backing = output / total_weights[:, None]
    return audio - backing, backing
