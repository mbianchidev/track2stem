import math
from collections import defaultdict

import librosa
import numpy as np

from .audio import check_cancelled

DEFAULT_TUNINGS = {"guitar": (40, 45, 50, 55, 59, 64), "bass": (28, 33, 38, 43)}
TUNINGS = {
    "guitar": {
        "E standard": (40, 45, 50, 55, 59, 64),
        "D# standard": (39, 44, 49, 54, 58, 63),
        "D standard": (38, 43, 48, 53, 57, 62),
        "C# standard": (37, 42, 47, 52, 56, 61),
        "C standard": (36, 41, 46, 51, 55, 60),
        "B standard": (35, 40, 45, 50, 54, 59),
        "Drop D": (38, 45, 50, 55, 59, 64),
        "Drop C#": (37, 44, 49, 54, 58, 63),
        "Drop C": (36, 43, 48, 53, 57, 62),
        "Drop B": (35, 42, 47, 52, 56, 61),
        "Drop A#": (34, 41, 46, 51, 55, 60),
        "Drop A": (33, 40, 45, 50, 54, 59),
        "7-string B standard": (35, 40, 45, 50, 55, 59, 64),
        "7-string Drop A": (33, 40, 45, 50, 55, 59, 64),
        "8-string F# standard": (30, 35, 40, 45, 50, 55, 59, 64),
    },
    "bass": {
        "E standard": (28, 33, 38, 43),
        "D# standard": (27, 32, 37, 42),
        "D standard": (26, 31, 36, 41),
        "C# standard": (25, 30, 35, 40),
        "C standard": (24, 29, 34, 39),
        "Drop D": (26, 33, 38, 43),
        "Drop C#": (25, 32, 37, 42),
        "Drop C": (24, 31, 36, 41),
        "Drop B": (23, 30, 35, 40),
        "5-string B standard": (23, 28, 33, 38, 43),
        "5-string Drop A": (21, 28, 33, 38, 43),
        "6-string B standard": (23, 28, 33, 38, 43, 48),
    },
}


def infer_tuning(notes, instrument):
    if instrument not in TUNINGS:
        raise ValueError("Tuning inference supports guitar and bass")
    histogram = defaultdict(float)
    for note in notes:
        pitch, start, end = float(note["pitch"]), float(note["start"]), float(note["end"])
        if (not all(math.isfinite(value) for value in (pitch, start, end))
                or not pitch.is_integer() or not 0 <= pitch <= 127 or start < 0 or end <= start):
            raise ValueError("Tuning inference needs finite MIDI pitches and positive note durations")
        histogram[int(pitch)] += end - start
    empty = {"candidate": None, "confidence": 0, "ambiguous": True, "candidates": [],
             "strings": list(DEFAULT_TUNINGS[instrument]),
             "reason": "Not enough stable pitched audio to propose a tuning"}
    total = sum(histogram.values())
    histogram = {pitch: duration for pitch, duration in histogram.items()
                 if duration >= max(.06, total * .005)}
    if not histogram:
        return empty
    total = sum(histogram.values())
    lowest = min(histogram)
    candidates = []
    for name, strings in TUNINGS[instrument].items():
        playable = all(any(0 <= pitch - string <= 24 for string in strings) for pitch in histogram)
        if not playable:
            continue
        open_duration = sum(histogram.get(pitch, 0) for pitch in strings)
        supported = sum(pitch in histogram for pitch in strings)
        fret_cost = sum(duration * min(pitch - string for string in strings if 0 <= pitch - string <= 24)
                        for pitch, duration in histogram.items()) / total
        score = (.7 * open_duration / total + .15 * max(0, 1 - (lowest - strings[0]) / 12)
                 + .15 * max(0, 1 - fret_cost / 12)
                 - .18 * max(0, len(strings) - len(DEFAULT_TUNINGS[instrument])))
        candidates.append({"name": name, "strings": list(strings), "score": round(max(0, score), 4),
                           "supported_open_strings": supported})
    candidates.sort(key=lambda candidate: candidate["score"], reverse=True)
    if not candidates:
        return {**empty, "lowest_note": librosa.midi_to_note(lowest, unicode=False),
                "reason": "Observed pitches do not fit the supported string/fret ranges"}
    best = candidates[0]
    margin = best["score"] - candidates[1]["score"] if len(candidates) > 1 else best["score"]
    identifiable = (best["supported_open_strings"] >= 3 and lowest == best["strings"][0]
                    and best["score"] >= .6 and margin >= .08)
    return {
        "candidate": best["name"] if identifiable else None,
        "confidence": round(min(.85, .45 + margin * .8), 3) if identifiable else 0,
        "ambiguous": not identifiable,
        "strings": best["strings"],
        "lowest_note": librosa.midi_to_note(lowest, unicode=False),
        "candidates": candidates[:4],
        "reason": "Ranked open-string and fret-range evidence; audio cannot uniquely identify physical tuning. "
                  "Scores are heuristic, not calibrated probabilities.",
    }


def estimate_tuning(stems, sample_rate, cancelled=None):
    result = {}
    target_rate, hop = 22050, 256
    for instrument in ("guitar", "bass"):
        if instrument not in stems:
            continue
        source = stems[instrument]
        observations = defaultdict(lambda: {"seconds": 0., "first": math.inf, "last": 0.})
        for offset in range(0, len(source), sample_rate * 30):
            if cancelled:
                check_cancelled(cancelled)
            chunk = source[offset:offset + sample_rate * 30].mean(axis=1)
            if np.max(np.abs(chunk), initial=0) < .001:
                continue
            mono = librosa.resample(chunk, orig_sr=sample_rate, target_sr=target_rate)
            pitch = librosa.yin(mono, sr=target_rate, fmin=20 if instrument == "bass" else 35,
                                fmax=500, frame_length=4096, hop_length=hop)
            rms = librosa.feature.rms(y=mono, frame_length=4096, hop_length=hop)[0]
            midi = librosa.hz_to_midi(pitch[:len(rms)])
            stable = ((rms > max(.003, float(rms.max()) * .1))
                      & (np.abs(midi - np.round(midi)) < .2)
                      & (np.abs(np.diff(midi, prepend=midi[0])) < .2))
            for value in np.unique(np.round(midi[stable]).astype(int)):
                frames = np.flatnonzero(stable & (np.round(midi) == value))
                observation = observations[int(value)]
                observation["seconds"] += len(frames) * hop / target_rate
                observation["first"] = min(observation["first"], offset / sample_rate + frames[0] * hop / target_rate)
                observation["last"] = max(observation["last"], offset / sample_rate + frames[-1] * hop / target_rate)
        notes = [{"pitch": pitch, "start": value["first"], "end": value["first"] + value["seconds"]}
                 for pitch, value in observations.items()]
        estimate = infer_tuning(notes, instrument)
        result[instrument] = {
            **estimate, "analyzed_seconds": round(len(source) / sample_rate, 3),
            "voiced_seconds": round(min(len(source) / sample_rate, sum(value["seconds"] for value in observations.values())), 3),
            "last_pitched_time": round(min(len(source) / sample_rate, max((value["last"] for value in observations.values()), default=0)), 3),
        }
    return result
