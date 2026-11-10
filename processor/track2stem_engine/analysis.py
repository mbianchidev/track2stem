import logging

import librosa
import numpy as np
from scipy.signal import find_peaks

from .audio import check_cancelled
from .tuning import estimate_tuning

logger = logging.getLogger(__name__)
HOP = 256
RATE = 22050
KEY_PROFILES = {
    "major": np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]),
    "minor": np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]),
}
PITCH_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def estimate_key(chroma):
    profile = chroma.mean(axis=1)
    if np.linalg.norm(profile) < 1e-6 or np.std(profile) < .005:
        return {"name": None, "confidence": 0, "method": "chroma profile correlation"}
    scores = []
    for mode, template in KEY_PROFILES.items():
        for root in range(12):
            scores.append((float(np.corrcoef(profile, np.roll(template, root))[0, 1]), root, mode))
    scores.sort(reverse=True)
    best, root, mode = scores[0]
    return {
        "name": f"{PITCH_NAMES[root]} {mode}",
        "confidence": round(max(0, min(1, best)) * max(0, min(1, (best - scores[1][0]) * 5)), 3),
        "method": "chroma profile correlation; estimate, not a score annotation",
    }


def recognize_sections(mono, rate, chroma, stems):
    duration = len(mono) / rate
    rms = librosa.feature.rms(y=mono, hop_length=HOP)[0]
    window = max(1, round(2 * rate / HOP))
    count = min(chroma.shape[1], len(rms)) // window
    if count < 2:
        return [{"start": 0, "end": round(duration, 3), "label": "Instrumental", "confidence": .2}]
    features = np.array([np.r_[chroma[:, index * window:(index + 1) * window].mean(axis=1),
                                      rms[index * window:(index + 1) * window].mean()]
                         for index in range(count)])
    features /= np.maximum(np.linalg.norm(features, axis=1, keepdims=True), 1e-8)
    novelty = np.linalg.norm(np.diff(features, axis=0), axis=1)
    peaks, _ = find_peaks(novelty, distance=4, prominence=max(.12, float(np.std(novelty))))
    boundaries = [0, *[float((index + 1) * window * HOP / rate) for index in peaks], duration]
    boundaries = sorted(set(boundaries))
    summaries = []
    for start, end in zip(boundaries, boundaries[1:]):
        first, last = int(start * rate), max(int(start * rate) + 1, int(end * rate))
        energy = float(np.sqrt(np.mean(mono[first:last] ** 2)))
        vocals = stems.get("vocals")
        guitar = stems.get("guitar")
        vocal_energy = float(np.sqrt(np.mean(vocals[first:last] ** 2))) if vocals is not None else 0
        guitar_energy = float(np.sqrt(np.mean(guitar[first:last] ** 2))) if guitar is not None else 0
        left, right = int(start * rate / HOP), max(int(start * rate / HOP) + 1, int(end * rate / HOP))
        summaries.append((energy, vocal_energy, guitar_energy, chroma[:, left:right].mean(axis=1)))
    median_energy = float(np.median([item[0] for item in summaries]))
    result = []
    for index, ((start, end), (energy, voice, guitar, profile)) in enumerate(zip(zip(boundaries, boundaries[1:]), summaries)):
        similarities = [float(np.dot(profile, other[3]) / max(np.linalg.norm(profile) * np.linalg.norm(other[3]), 1e-8))
                        for other_index, other in enumerate(summaries) if abs(other_index - index) > 1]
        repeated = max(similarities, default=0) > .93
        has_voice = voice > max(.002, energy * .2)
        if index == 0 and not has_voice and len(summaries) > 1:
            label = "Intro"
        elif index == len(summaries) - 1 and not has_voice and len(summaries) > 1:
            label = "Outro"
        elif not has_voice and guitar > energy * .4:
            label = "Solo"
        elif has_voice and repeated and energy >= median_energy:
            label = "Chorus"
        elif has_voice:
            label = "Verse"
        elif not repeated and 0 < index < len(summaries) - 1:
            label = "Bridge"
        else:
            label = "Instrumental"
        result.append({"start": round(start, 3), "end": round(end, 3), "label": label,
                       "confidence": .55 if has_voice and repeated else .3})
    return result


def analyze(audio, sample_rate, stems=None, cancelled=None, model_dir=None, report=None):
    if cancelled:
        check_cancelled(cancelled)
    if audio.ndim != 2 or not audio.size or not np.isfinite(audio).all():
        raise ValueError("Analysis needs non-empty, finite audio")
    mono = librosa.resample(audio.mean(axis=1), orig_sr=sample_rate, target_sr=RATE)
    if np.max(np.abs(mono)) < 1e-6:
        raise ValueError("Cannot analyze silent audio")
    if model_dir is not None:
        from .rhythm import detect_rhythm
        rhythm = detect_rhythm(audio, sample_rate, model_dir, report or (lambda *_: None), cancelled)
    else:
        onset = librosa.onset.onset_strength(y=mono, sr=RATE, hop_length=HOP)
        tempos = librosa.feature.tempo(onset_envelope=onset, sr=RATE, hop_length=HOP,
                                      aggregate=None, ac_size=6, max_tempo=240)
        _, beat_frames = librosa.beat.beat_track(onset_envelope=onset, sr=RATE, hop_length=HOP,
                                               bpm=tempos, trim=False)
        beats = librosa.frames_to_time(beat_frames, sr=RATE, hop_length=HOP)
        beats = beats[beats < len(mono) / RATE]
        if len(beats) < 2:
            raise ValueError("No reliable beat grid found; try a recording with a clearer pulse")
        rhythm = {
            "bpm": round(float(np.median(tempos)), 2),
            "tempo_changes": [{"time": round(float(index * HOP / RATE), 3), "bpm": round(float(tempos[index]), 2)}
                              for index in range(0, len(tempos), max(1, round(2 * RATE / HOP)))],
            "beats": [round(float(beat), 6) for beat in beats], "meter_changes": [], "downbeats": [],
            "rhythm_model": "spectral pulse analysis; no meter inference requested",
        }
    if cancelled:
        check_cancelled(cancelled)
    chroma = librosa.feature.chroma_stft(y=mono, sr=RATE, hop_length=HOP, n_fft=4096)
    resampled_stems = {
        name: librosa.resample(value, orig_sr=sample_rate, target_sr=RATE, axis=0)
        for name, value in (stems or {}).items() if name in {"vocals", "guitar", "bass"}
    }
    return {
        "duration": round(len(audio) / sample_rate, 3),
        **rhythm,
        "key": estimate_key(chroma),
        "tuning": estimate_tuning(stems or {}, sample_rate, cancelled),
        "sections": recognize_sections(mono, RATE, chroma, resampled_stems),
        "notes": [
            *rhythm.get("notes", []),
            "Tempo and key are estimates; half/double-tempo ambiguity is possible.",
            "Section names use repetition, energy and stem activity, not semantic certainty.",
            "Click accents follow detected downbeats; uncertain meter is left unmetered.",
        ],
    }


def make_click_track(beats, frames, sample_rate, downbeats=None):
    result = np.zeros((frames, 2), dtype=np.float32)
    count = max(1, round(.035 * sample_rate))
    time = np.arange(count) / sample_rate
    downbeats = np.asarray(downbeats if downbeats is not None else [], dtype=float)
    for beat in beats:
        start = round(beat * sample_rate)
        if not 0 <= start < frames:
            continue
        accented = bool(len(downbeats) and np.min(np.abs(downbeats - beat)) < .06)
        click = .65 * np.sin(2 * np.pi * (1800 if accented else 1200) * time) * np.exp(-time * 120)
        length = min(count, frames - start)
        result[start:start + length] += click[:length, None]
    return np.clip(result, -1, 1)
