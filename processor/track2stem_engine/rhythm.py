import logging
import os
import threading
from functools import lru_cache

import numpy as np

from .audio import check_cancelled
from .models import ensure_model

logger = logging.getLogger(__name__)


def decode_meter(beats, downbeat_probabilities, accent_strengths):
    beats = np.asarray(beats, dtype=float)
    probabilities = np.asarray(downbeat_probabilities, dtype=float)
    accents = np.asarray(accent_strengths, dtype=float)
    if (beats.ndim != 1 or probabilities.shape != beats.shape or accents.shape != beats.shape
            or not np.isfinite(beats).all() or not np.isfinite(probabilities).all()
            or not np.isfinite(accents).all() or np.any(np.diff(beats) <= 0)
            or np.any(beats < 0) or np.any((probabilities < 0) | (probabilities > 1)) or np.any(accents < 0)):
        raise ValueError("Meter inference needs increasing beat times and finite, aligned evidence")
    unknown = {"meter_changes": [], "downbeats": [],
               "meter_method": "undetermined; no fixed time signature is assumed"}
    if len(beats) < 6 or (np.ptp(accents) < 1e-6 and np.ptp(probabilities) < .15):
        return unknown
    lower, upper = np.quantile(accents, [.2, .9])
    acoustic = np.clip((accents - lower) / max(upper - lower, 1e-8), .05, .95)
    if upper - lower < 1e-6:
        acoustic = np.full(len(beats), .5)
    neural = np.clip(probabilities, .03, .97)
    logits = .45 * np.log(neural / (1 - neural)) + .55 * np.log(acoustic / (1 - acoustic))
    combined = np.clip(1 / (1 + np.exp(-logits)), .02, .98)
    states = [(meter, phase) for meter in (2, 3, 4, 5, 6, 7) for phase in range(meter)]
    transitions = np.full((len(states), len(states)), -np.inf)
    for previous, (old_meter, old_phase) in enumerate(states):
        for current, (meter, phase) in enumerate(states):
            if old_meter == meter and phase == (old_phase + 1) % meter:
                transitions[previous, current] = 0
            elif old_meter != meter and old_phase == old_meter - 1 and phase == 0:
                transitions[previous, current] = -3.5
    emissions = np.array([np.log(combined) - .9 if phase == 0 else np.log1p(-combined)
                          for _, phase in states]).T
    scores = emissions[0].copy()
    parents = np.zeros((len(beats), len(states)), dtype=int)
    for index in range(1, len(beats)):
        candidates = scores[:, None] + transitions
        parents[index] = np.argmax(candidates, axis=0)
        scores = candidates[parents[index], np.arange(len(states))] + emissions[index]
    path = np.zeros(len(beats), dtype=int)
    path[-1] = int(np.argmax(scores))
    for index in range(len(beats) - 1, 0, -1):
        path[index - 1] = parents[index, path[index]]
    decoded = [states[index] for index in path]
    boundaries = [0, *[index for index in range(1, len(beats)) if decoded[index][0] != decoded[index - 1][0]], len(beats)]
    changes, downbeats = [], []
    for first, last in zip(boundaries, boundaries[1:]):
        meter = decoded[first][0]
        if last - first < meter * 2:
            continue
        positions = [index for index in range(first, last) if decoded[index][1] == 0]
        others = [index for index in range(first, last) if decoded[index][1] != 0]
        contrast = float(np.mean(combined[positions]) - np.mean(combined[others])) if positions and others else 0
        if contrast < .15:
            continue
        changes.append({"time": round(float(beats[first]), 6) if first else 0,
                        "numerator": meter, "denominator": 8 if meter == 6 else 4,
                        "pulse_quarters": .5 if meter == 6 else 1.,
                        "confidence": round(min(.9, .4 + contrast * .5), 3)})
        downbeats.extend(round(float(beats[index]), 6) for index in positions)
    return {"meter_changes": changes, "downbeats": downbeats,
            "meter_method": "metrical-state decoding of neural downbeats and acoustic accents; estimate"}


@lru_cache(maxsize=1)
def _tracker(path):
    import torch
    from beat_this.inference import Audio2Beats

    torch.set_num_threads(max(1, min(4, os.process_cpu_count() or 1)))
    return Audio2Beats(checkpoint_path=str(path), device="cpu", float16=False, dbn=False)


def detect_rhythm(audio, sample_rate, model_dir, report, cancelled):
    if audio.ndim != 2 or not audio.size or not np.isfinite(audio).all():
        raise ValueError("Rhythm analysis needs non-empty, finite audio")
    cancelled = cancelled or threading.Event()
    tracker = _tracker(ensure_model("beat-small", model_dir, report, cancelled))
    mono = audio.mean(axis=1)
    beats, probabilities, accents = [], [], []
    duration = len(audio) / sample_rate
    for first in range(0, len(mono), 25 * sample_rate):
        check_cancelled(cancelled)
        last = min(len(mono), first + 25 * sample_rate)
        context = max(0, first - 2 * sample_rate)
        end = min(len(mono), last + 2 * sample_rate)
        spectrum = tracker.signal2spect(mono[context:end], sample_rate)
        beat_logits, downbeat_logits = tracker.spect2frames(spectrum)
        predicted, _ = tracker.frames2beats(beat_logits, downbeat_logits)
        downbeat_scores = downbeat_logits.sigmoid().cpu().numpy()
        for local in predicted:
            time = float(local + context / sample_rate)
            if not first / sample_rate <= time < min(last / sample_rate, duration - .03):
                continue
            if beats and time - beats[-1] < .12:
                continue
            center = round(float(local) * 50)
            left, right = max(0, center - 3), min(len(downbeat_scores), center + 4)
            probability = float(downbeat_scores[left:right].max(initial=0))
            offset = max(0, round((time - .02) * sample_rate))
            excerpt = mono[offset:min(len(mono), offset + round(.14 * sample_rate))]
            strength = float(np.sqrt(np.mean(excerpt ** 2))) if len(excerpt) else 0
            beats.append(time)
            probabilities.append(probability)
            accents.append(strength)
        report(76 + int(2 * last / len(mono)), "Tracking beats, downbeats and meter changes")
    if len(beats) < 2:
        raise ValueError("No reliable beat grid found; try a recording with a clearer pulse")
    meter = decode_meter(beats, probabilities, accents)
    intervals = np.diff(beats)
    points = []
    for index, beat in enumerate(beats[:-1]):
        active = next((entry for entry in reversed(meter["meter_changes"]) if entry["time"] <= beat), None)
        pulse_quarters = active["pulse_quarters"] if active else 1
        interval = float(np.median(intervals[max(0, index - 2):min(len(intervals), index + 3)]))
        bpm = round(60 * pulse_quarters / interval, 2)
        if not 20 <= bpm <= 400:
            raise ValueError("Detected quarter-note tempo is outside the supported 20-400 BPM range")
        if not points or beat - points[-1]["time"] >= 2 or (active and abs(beat - active["time"]) < .03):
            points.append({"time": round(beat, 6) if points else 0, "bpm": bpm})
    return {
        "duration": round(duration, 3), "bpm": round(float(np.median([point["bpm"] for point in points])), 2),
        "beats": [round(beat, 6) for beat in beats], "tempo_changes": points, **meter,
        "rhythm_model": "Beat This small0; MIT; CPU",
        "notes": [
            "Tempo uses quarter-note BPM; detected pulses may be eighth notes in compound meter.",
            "Meter, bar phase and tempo are estimates; half/double-tempo and denominator ambiguity remain possible.",
            "Missing meter evidence is unmetered, not an implicit 4/4 claim.",
        ],
    }
