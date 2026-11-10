import librosa
import numpy as np
import pytest

from track2stem_engine.analysis import HOP, recognize_sections


def test_complete_arrangement_uses_structure_not_individual_chord_changes():
    rate = 22050
    layout = [("Intro", 4), ("Verse", 8), ("Chorus", 8), ("Verse", 8),
              ("Chorus", 8), ("Bridge", 4), ("Solo", 4), ("Outro", 4)]
    levels = {
        "Intro": (0, .05, .02), "Verse": (.08, .04, .02), "Chorus": (.18, .12, .06),
        "Bridge": (.04, .015, .02), "Solo": (0, .2, .03), "Outro": (0, .025, .01),
    }
    stems = {name: np.zeros((48 * rate, 2), dtype=np.float32) for name in ("vocals", "guitar", "bass")}
    reference, start = [], 0
    for label, duration in layout:
        reference.append((start, start + duration, label))
        time = np.arange(duration * rate) / rate
        root = 293.665 if label == "Bridge" else 220.
        envelope = np.minimum(time / .02, 1) * np.minimum((duration - time) / .02, 1)
        for (name, stem), amplitude, frequency in zip(stems.items(), levels[label], (root * 2, root, root / 2)):
            signal = amplitude * (np.sin(2 * np.pi * frequency * time) + .25 * np.sin(4 * np.pi * frequency * time))
            signal *= envelope
            stem[start * rate:(start + duration) * rate] = signal[:, None]
        start += duration
    mono = sum(stems.values()).mean(axis=1)
    chroma = librosa.feature.chroma_stft(y=mono, sr=rate, hop_length=HOP, n_fft=4096)
    result = recognize_sections(mono, rate, chroma, stems)
    assert [entry["label"] for entry in result] == [entry[2] for entry in reference]
    assert [entry["start"] for entry in result] == pytest.approx([entry[0] for entry in reference], abs=.75)
    assert result[0]["start"] == 0 and result[-1]["end"] == 48
    assert result[1]["group"] == result[3]["group"]
    assert result[2]["group"] == result[4]["group"]
    assert result[1]["group"] != result[2]["group"]


def test_missing_vocal_evidence_does_not_invent_a_sung_verse_or_chorus():
    rate = 22050
    time = np.arange(rate * 6) / rate
    mono = (.1 * np.sin(2 * np.pi * 220 * time)).astype(np.float32)
    chroma = librosa.feature.chroma_stft(y=mono, sr=rate, hop_length=HOP, n_fft=4096)
    result = recognize_sections(mono, rate, chroma, {})
    assert all(entry["label"] not in {"Verse", "Chorus"} for entry in result)
