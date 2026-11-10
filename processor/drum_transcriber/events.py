# SPDX-License-Identifier: CC-BY-SA-4.0
# Adapted from ADT_STR 77dbef225e7029478ebfb916f20c7a00274f0f12; see LICENSE.
import numpy as np

GENERAL_MIDI = {
    35: 35, 36: 36, 37: 37, 38: 38, 39: 39, 40: 40, 41: 41, 42: 42,
    43: 44, 44: 46, 45: 47, 46: 49, 47: 50, 48: 51, 49: 52,
    50: 54, 51: 55, 52: 56, 53: 58, 54: 64, 55: 70, 56: 71,
    57: 73, 58: 75, 59: 78, 60: 81,
}


def attack_envelope(audio, include_initial=False):
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim != 1 or not len(audio) or not np.isfinite(audio).all():
        raise ValueError("Attack analysis needs finite mono audio")
    padded = np.pad(audio, (0, (-len(audio)) % 240))
    envelope = np.sqrt(np.mean(padded.reshape(-1, 240) ** 2, axis=1))
    changes = np.maximum(0, np.diff(envelope, prepend=envelope[0]))
    if include_initial:
        changes[0] = envelope[0]
    return changes


def supported_onset(start, attacks, threshold):
    center = round(start * 100)
    first, last = max(0, center - 6), min(len(attacks), center + 7)
    if first >= last:
        return None
    strongest = first + int(np.argmax(attacks[first:last]))
    return strongest / 100 if attacks[strongest] >= threshold else None


def tom_frequency(audio, rate):
    audio = np.asarray(audio, dtype=np.float64)
    if audio.ndim != 1 or not np.isfinite(audio).all() or rate <= 0:
        raise ValueError("Tom pitch analysis needs finite mono audio and a positive sample rate")
    if len(audio) < rate * .04:
        return None
    window = (audio - audio.mean()) * np.hanning(len(audio))
    spectrum = np.fft.rfft(window, n=1 << (2 * len(window) - 1).bit_length())
    correlation = np.fft.irfft(np.abs(spectrum) ** 2)
    if correlation[0] < 1e-12:
        return None
    first, last = max(2, round(rate / 500)), min(len(audio) - 2, round(rate / 40))
    peaks = np.flatnonzero((correlation[first:last] >= correlation[first - 1:last - 1])
                          & (correlation[first:last] > correlation[first + 1:last + 1])) + first
    if not len(peaks):
        return None
    strongest = float(correlation[peaks].max())
    lag = int(peaks[correlation[peaks] >= strongest * .9][0])
    if correlation[lag] / correlation[0] < .35:
        return None
    left, middle, right = correlation[lag - 1:lag + 2]
    denominator = left - 2 * middle + right
    fractional = .5 * (left - right) / denominator if abs(denominator) > 1e-12 else 0
    return float(rate / (lag + fractional))


def refine_tom_registers(notes, frequencies):
    if len(notes) != len(frequencies):
        raise ValueError("Each drum event must have its own pitch-evidence entry")
    if any(frequency is not None and (not np.isfinite(frequency) or frequency <= 0) for frequency in frequencies):
        raise ValueError("Tom pitch evidence must be finite and positive")
    result = [dict(note) for note in notes]
    neighbors = sorted((note["start"], index) for index, note in enumerate(notes)
                       if note["pitch"] in {35, 36, 41, 47, 50})
    ambiguous = set()
    for (first, left), (last, right) in zip(neighbors, neighbors[1:]):
        if last - first < .06:
            ambiguous.update((left, right))
    observed = sorted((12 * np.log2(frequency), index) for index, (note, frequency) in enumerate(zip(notes, frequencies))
                      if note["pitch"] in {41, 47, 50} and frequency is not None and index not in ambiguous)
    details = {"calibrated": False, "changed": 0}
    if len(observed) < 3 or observed[-1][0] - observed[0][0] < 8:
        return result, details
    values = np.asarray([value for value, _ in observed])
    gaps = np.diff(values)
    splits = (np.flatnonzero(gaps >= 2) + 1).tolist()
    if len(splits) < 2:
        return result, details
    groups = np.split(np.arange(len(observed)), splits)
    if max(float(np.ptp(values[group])) for group in groups) > min(gaps[split - 1] for split in splits):
        return result, details
    details["calibrated"] = True
    details["cluster_frequencies_hz"] = [float(2 ** (np.median(values[group]) / 12)) for group in groups]
    for group_index, group in enumerate(groups):
        pitch = 41 if group_index == 0 else 50 if group_index == len(groups) - 1 else 47
        for position in group:
            index = observed[position][1]
            details["changed"] += int(result[index]["pitch"] != pitch)
            result[index]["pitch"] = pitch
    return result, details


def allowed_tokens(tokens):
    if not tokens or tokens[0] != 2:
        raise ValueError("Drum decoding must begin with the start token")
    values = tokens[1:]
    if values == [0] or 3 in values:
        return [3]
    phase = len(values) % 3
    complete = values[:len(values) - phase] if phase else values
    seen = {(complete[index], complete[index + 1]) for index in range(0, len(complete), 3)}
    if phase == 1:
        return [300 + pitch for pitch in GENERAL_MIDI if (values[-1], 300 + pitch) not in seen]
    if phase == 2:
        return list(range(400, 528))
    minimum = complete[-3] if complete else 4
    times = [value for value in range(minimum, 260)
             if any((value, 300 + pitch) not in seen for pitch in GENERAL_MIDI)]
    return [3, *times, *([0] if not values else [])]


def decode_tokens(tokens):
    if not tokens or tokens[0] != 2 or 3 not in tokens:
        raise ValueError("Drum prediction has no complete start/end sequence")
    stop = tokens.index(3)
    if tokens[1:stop] == [0]:
        return []
    values = tokens[1:stop]
    if len(values) % 3:
        raise ValueError("Drum prediction contains an incomplete onset/pitch/velocity event")
    notes = []
    seen = set()
    for index in range(0, len(values), 3):
        time, pitch, velocity = values[index:index + 3]
        if not 4 <= time < 300 or pitch - 300 not in GENERAL_MIDI or not 400 <= velocity <= 527:
            raise ValueError("Drum prediction contains an invalid time, instrument or velocity token")
        if (time, pitch) in seen:
            raise ValueError("Drum prediction repeats the same instrument at the same onset")
        seen.add((time, pitch))
        if velocity == 400:
            continue
        start = (time - 4) / 100
        notes.append({"start": start, "end": round(start + .1, 5),
                      "pitch": GENERAL_MIDI[pitch - 300], "velocity": velocity - 400})
    return sorted(notes, key=lambda note: (note["start"], note["pitch"]))
