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
