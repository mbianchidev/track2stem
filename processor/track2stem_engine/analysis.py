import logging
import math

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
    block = max(1, round(rate * .5))
    count = int(np.ceil(len(mono) / block))
    if count < 6:
        return [{"start": 0, "end": round(duration, 3), "label": "Instrumental", "confidence": .2}]

    def rms(value):
        return float(np.sqrt(np.mean(np.asarray(value, dtype=np.float64) ** 2))) if len(value) else 0

    names = ("vocals", "guitar", "bass", "drums", "piano", "other")
    raw, chroma_blocks = [], []
    for index in range(count):
        first, last = index * block, min(len(mono), (index + 1) * block)
        energy = rms(mono[first:last])
        activity = {name: rms(stems[name][first:last]) if name in stems else 0 for name in names}
        total = max(sum(activity.values()), 1e-8)
        spectrum = np.abs(np.fft.rfft(mono[first:last])) ** 2
        frequencies = np.fft.rfftfreq(last - first, 1 / rate)
        bands = [float(spectrum[mask].sum() / max(float(spectrum.sum()), 1e-12))
                 for mask in (frequencies < 250, (frequencies >= 250) & (frequencies < 2500), frequencies >= 2500)]
        raw.append([np.log10(max(energy, 1e-6)), activity["vocals"] / total,
                    (activity["guitar"] if "guitar" in stems else activity["other"]) / total,
                    activity["bass"] / total, *bands])
        left, right = first // HOP, min(chroma.shape[1], max(first // HOP + 1, math.ceil(last / HOP)))
        chroma_blocks.append(chroma[:, left:right].mean(axis=1))
    raw, chroma_blocks = np.asarray(raw), np.asarray(chroma_blocks)
    floors = np.array([.15, .06, .06, .06, .08, .08, .08])
    scales = np.array([1.8, 1.8, 1.4, .5, .4, .4, .4])
    features = (raw - np.median(raw, axis=0)) / np.maximum(raw.std(axis=0), floors) * scales
    novelty = np.zeros(count)
    for index in range(1, count - 1):
        left = features[max(0, index - 4):index].mean(axis=0)
        right = features[index:min(count, index + 4)].mean(axis=0)
        novelty[index] = np.linalg.norm(right - left)
    peaks, _ = find_peaks(novelty, distance=6, prominence=max(.35, float(novelty.std()) * .35),
                         height=max(.8, float(np.median(novelty) + novelty.std() * 1.1)))
    peaks = [index for index in peaks if index * block / rate >= 3 and duration - index * block / rate >= 3]
    boundaries = [0, *[float(index * block / rate) for index in peaks], duration]
    summaries = []
    for start, end in zip(boundaries, boundaries[1:]):
        first, last = int(start * rate), max(int(start * rate) + 1, int(end * rate))
        energy = rms(mono[first:last])
        activity = {name: rms(stems[name][first:last]) if name in stems else 0 for name in names}
        left, right = int(first / block), min(count, max(int(first / block) + 1, math.ceil(last / block)))
        positions = np.linspace(left, right - 1, 8)
        harmonic = np.stack([np.interp(positions, np.arange(count), chroma_blocks[:, pitch]) for pitch in range(12)])
        harmonic /= np.maximum(np.linalg.norm(harmonic, axis=0, keepdims=True), 1e-8)
        summaries.append({
            "start": start, "end": end, "energy": energy, "activity": activity,
            "has_voice": activity["vocals"] > max(.001, energy * .12),
            "structure": features[left:right].mean(axis=0), "harmonic": harmonic,
        })

    def distance(first, second):
        structure = np.linalg.norm(first["structure"] - second["structure"]) / np.sqrt(features.shape[1])
        harmony = np.mean(np.linalg.norm(first["harmonic"] - second["harmonic"], axis=0))
        return float(structure + harmony)

    groups, identifiers = [], []
    for index, summary in enumerate(summaries):
        candidates = [(float(np.mean([distance(summary, summaries[member]) for member in group])), group_index)
                      for group_index, group in enumerate(groups)
                      if summaries[group[0]]["has_voice"] == summary["has_voice"]]
        best = min(candidates) if candidates else (float("inf"), -1)
        if best[0] < .8:
            groups[best[1]].append(index)
            identifiers.append(best[1])
        else:
            identifiers.append(len(groups))
            groups.append([index])
    occurrences = [sum(index == 0 or identifiers[index - 1] != group for index in members)
                   for group, members in enumerate(groups)]
    repeated = [group for group, members in enumerate(groups)
                if occurrences[group] > 1 and summaries[members[0]]["has_voice"]]
    chorus = max(repeated, key=lambda group: np.mean([summaries[index]["energy"] for index in groups[group]])) if repeated else None
    vocal_positions = [index for index, summary in enumerate(summaries) if summary["has_voice"]]
    first_voice, last_voice = (min(vocal_positions), max(vocal_positions)) if vocal_positions else (-1, -1)
    chorus_positions = groups[chorus] if chorus is not None else []
    median_guitar = float(np.median([summary["activity"]["guitar"] if "guitar" in stems
                                     else summary["activity"]["other"] for summary in summaries]))
    result = []
    for index, summary in enumerate(summaries):
        group = identifiers[index]
        activity, has_voice = summary["activity"], summary["has_voice"]
        guitar = activity["guitar"] if "guitar" in stems else activity["other"]
        if first_voice >= 0 and index < first_voice:
            label, confidence = "Intro", .65
        elif last_voice >= 0 and index == len(summaries) - 1 and not has_voice:
            label, confidence = "Outro", .65
        elif (not has_voice and guitar > max(.002, summary["energy"] * .4)
              and guitar > median_guitar * .9):
            label, confidence = "Solo", .6
        elif last_voice >= 0 and index > last_voice:
            label, confidence = "Outro", .65
        elif group == chorus:
            label, confidence = "Chorus", min(.8, .55 + occurrences[group] * .05)
        elif (occurrences[group] == 1 and chorus_positions
              and min(chorus_positions) < index < len(summaries) - 1):
            label, confidence = "Bridge", .55
        elif has_voice:
            label, confidence = "Verse", .6 if occurrences[group] > 1 else .4
        else:
            label, confidence = "Instrumental", .3
        name = chr(65 + group) if group < 26 else f"S{group + 1}"
        if (result and result[-1]["label"] == label
                and (result[-1]["group"] == name or label in {"Intro", "Outro"})):
            result[-1]["end"] = round(summary["end"], 3)
        else:
            result.append({"start": round(summary["start"], 3), "end": round(summary["end"], 3),
                           "label": label, "group": name, "confidence": round(confidence, 2)})
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
        for name, value in (stems or {}).items() if name in {"vocals", "guitar", "bass", "drums", "piano", "other"}
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
