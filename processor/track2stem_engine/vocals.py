import logging
import math
import os

import numpy as np
from scipy import signal

from .audio import check_cancelled
from .vocal_model import get_vocal_separator

logger = logging.getLogger(__name__)


def _correlation(first, second):
    a, b = first.reshape(-1), second.reshape(-1)
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denominator) if denominator > 1e-10 else 0


def _spatial_sample(audio):
    if len(audio) < 256:
        return None
    sample = audio[::max(1, math.ceil(len(audio) / 100000))]
    eigenvalues = np.linalg.eigvalsh(np.cov(sample, rowvar=False))
    if eigenvalues[-1] <= 1e-12 or eigenvalues[0] / eigenvalues[-1] < 1e-4:
        return None
    return sample


def _spatial_separation(audio, sample, report, cancelled):
    from sklearn.decomposition import FastICA

    check_cancelled(cancelled)
    report(74, "Separating independent stereo vocal images on CPU")
    estimator = FastICA(n_components=2, whiten="unit-variance", random_state=0, max_iter=500, tol=1e-5)
    estimator.fit(sample)
    check_cancelled(cancelled)
    if estimator.n_iter_ >= 500:
        logger.error("Spatial vocal separation did not converge")
        raise RuntimeError("Spatial vocal separation did not converge; select the neural vocal method and retry")
    sources = estimator.transform(audio)
    images = sources.T[:, :, None] * estimator.mixing_.T[:, None, :]
    lead_index = int(np.argmax(np.mean(images ** 2, axis=(1, 2))))
    lead = (images[lead_index] + estimator.mean_).astype(np.float32)
    metadata = {
        "method": "stereo independent components", "model": "none; spatial CPU inference",
        "weight_license": "not applicable; no model weights", "requires_model_weights": False,
        "models_downloaded": False, "estimated": True, "stream_realignments": 0,
        "mixing_condition": float(np.linalg.cond(estimator.mixing_)), "ambiguous": False,
        "role_policy": "Independent stereo images are unmixed; the dominant image is proposed as lead.",
        "warning": "Spatial separation assumes stable, distinct stereo positions and at most two independent vocal groups. "
                   "Lead/backing roles remain estimates; centered, changing-pan or reverberant voices can be ambiguous.",
    }
    return lead, audio - lead, metadata


def split_vocals(audio, sample_rate, model_dir, report, cancelled, details=None, method=None):
    if (sample_rate != 44100 or audio.ndim != 2 or audio.shape[1] != 2
            or not len(audio) or not np.isfinite(audio).all()):
        raise ValueError("Vocal splitting needs stereo 44.1 kHz audio")
    check_cancelled(cancelled)
    selected = method or os.environ.get("TRACK2STEM_VOCAL_METHOD", "auto")
    if selected not in {"auto", "neural", "spatial"}:
        logger.error("Unsupported vocal method: %s", selected)
        raise ValueError("TRACK2STEM_VOCAL_METHOD must be auto, neural or spatial")
    sample = _spatial_sample(audio) if selected != "neural" else None
    if selected == "spatial" and sample is None:
        raise ValueError("Spatial vocal separation requires independent stereo channels; use the neural method for mono")
    if sample is not None:
        lead, backing, metadata = _spatial_separation(audio, sample, report, cancelled)
        if details is not None:
            details.update(metadata)
        return lead, backing
    metadata = {
        "model": "MedleyVox multi_singing_librispeech EMA",
        "method": "licensed neural vocal separator", "requires_model_weights": True,
        "weight_license": "CC-BY-4.0",
        "source": "https://huggingface.co/Cyru5/MedleyVox",
        "role_policy": "Overlapping streams are aligned; the globally dominant stream is proposed as lead.",
        "estimated": True,
    }
    if np.max(np.abs(audio)) < 1e-5:
        metadata.update(ambiguous=True, warning="No audible vocal content; no distinct backing voice was detected.",
                        stream_realignments=0)
        if details is not None:
            details.update(metadata)
        return np.zeros_like(audio), audio.copy()
    separate = get_vocal_separator(model_dir, report, cancelled)
    original = signal.resample_poly(audio, 80, 147, axis=0).astype(np.float32)
    length, stride, n_fft, hop = 72000, 36000, 2048, 512
    combined = np.zeros((2, len(original), 2), dtype=np.float32)
    total_weights = np.zeros(len(original), dtype=np.float32)
    weights = np.minimum(np.arange(1, length + 1), np.arange(length, 0, -1)).astype(np.float32)
    weights /= weights.max()
    window = signal.windows.hann(n_fft, sym=False).astype(np.float32)
    offsets = range(0, len(original), stride)
    realignments, ambiguous_windows = 0, 0
    for index, offset in enumerate(offsets):
        check_cancelled(cancelled)
        count = min(length, len(original) - offset)
        chunk = np.pad(original[offset:offset + count], ((0, length - count), (0, 0)))
        mono = chunk.mean(axis=1)
        prediction = separate(mono)
        if (prediction.ndim != 2 or prediction.shape[0] != 2 or prediction.shape[1] < length
                or not np.isfinite(prediction).all()):
            raise RuntimeError("The licensed vocal model returned invalid stream dimensions")
        prediction = prediction[:, :length]
        if np.max(np.abs(mono)) > 1e-5 and np.sum(prediction ** 2) < 1e-10:
            raise RuntimeError("The vocal model returned no usable estimates for audible input")
        _, _, estimates = signal.stft(prediction, window=window, nperseg=n_fft,
                                       noverlap=n_fft - hop, boundary="zeros")
        power = np.abs(estimates) ** 2
        energy = np.mean(prediction ** 2, axis=1)
        prior = float(energy[0] / max(float(energy.sum()), 1e-12))
        first_mask = np.divide(power[0], power.sum(axis=0),
                               out=np.full_like(power[0], prior), where=power.sum(axis=0) > 1e-12)
        _, _, spectrum = signal.stft(chunk.T, window=window, nperseg=n_fft,
                                     noverlap=n_fft - hop, boundary="zeros")
        masks = np.stack((first_mask, 1 - first_mask))
        _, reconstructed = signal.istft(spectrum[None] * masks[:, None], window=window,
                                         nperseg=n_fft, noverlap=n_fft - hop, boundary=True)
        streams = reconstructed[:, :, :length].transpose(0, 2, 1)
        if offset:
            overlap = min(stride, count)
            existing = combined[:, offset:offset + overlap] / total_weights[None, offset:offset + overlap, None]
            direct = sum(_correlation(existing[voice], streams[voice, :overlap]) for voice in range(2))
            swapped = sum(_correlation(existing[voice], streams[1 - voice, :overlap]) for voice in range(2))
            if abs(direct - swapped) < .05:
                ambiguous_windows += 1
            if swapped > direct:
                streams = streams[::-1]
                realignments += 1
        combined[:, offset:offset + count] += streams[:, :count] * weights[None, :count, None]
        total_weights[offset:offset + count] += weights[:count]
        report(74 + int(2 * (index + 1) / len(offsets)), f"Separating lead/backing vocals {index + 1}/{len(offsets)}")
    check_cancelled(cancelled)
    if np.any(total_weights <= 0):
        raise RuntimeError("Vocal separation left uncovered audio")
    combined /= total_weights[None, :, None]
    energies = np.mean(combined ** 2, axis=(1, 2))
    lead_index = int(np.argmax(energies))
    lead = signal.resample_poly(combined[lead_index], 147, 80, axis=0)[:len(audio)].astype(np.float32)
    backing = audio - lead
    ambiguous = (ambiguous_windows > max(1, len(offsets) // 3) or abs(_correlation(lead, backing)) > .9)
    metadata.update(
        stream_realignments=realignments, ambiguous=ambiguous,
        warning="Lead/backing roles are estimated from dominant vocal streams, not guaranteed semantic identities. "
                + ("The stream assignment is ambiguous; review both exports." if ambiguous
                   else "Unisons, overlapping harmonies and more than two vocal groups can reduce accuracy."),
    )
    if ambiguous:
        logger.warning("Vocal stream assignment is ambiguous; both estimated exports require review")
    if details is not None:
        details.update(metadata)
    return lead, backing
