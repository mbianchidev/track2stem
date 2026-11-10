import numpy as np

from track2stem_engine.analysis import estimate_tuning
from track2stem_engine.tuning import infer_tuning


def test_drop_tuning_uses_open_string_evidence_after_the_first_ninety_seconds():
    rate = 8000
    audio = np.zeros(120 * rate, dtype=np.float32)
    strings = [38, 45, 50, 55, 59, 64]
    time = np.arange(2 * rate) / rate
    envelope = np.minimum(time / .03, 1) * np.minimum((2 - time) / .03, 1)
    for index, midi in enumerate(strings):
        frequency = 440 * 2 ** ((midi - 69) / 12)
        tone = (.12 * np.sin(2 * np.pi * frequency * time)
                + .035 * np.sin(4 * np.pi * frequency * time)) * envelope
        start = (96 + index * 3) * rate
        audio[start:start + len(tone)] = tone
    result = estimate_tuning({"guitar": np.column_stack((audio, audio))}, rate)["guitar"]
    assert result["analyzed_seconds"] == 120
    assert result["lowest_note"] == "D2"
    assert result["candidate"] == "Drop D"
    assert result["strings"] == strings
    assert result["last_pitched_time"] > 110
    assert result["voiced_seconds"] > 10


def test_fretted_notes_do_not_claim_a_uniquely_identified_tuning():
    notes = [{"pitch": pitch, "start": index, "end": index + .8}
             for index, pitch in enumerate((47, 50, 54, 59))]
    result = infer_tuning(notes, "guitar")
    assert result["ambiguous"]
    assert result["candidate"] is None
    assert len(result["candidates"]) > 1
    assert "cannot uniquely" in result["reason"]


def test_bass_tuning_distinguishes_drop_from_uniform_detuning_with_multiple_open_strings():
    strings = [24, 31, 36, 41]
    notes = [{"pitch": pitch, "start": index, "end": index + 1}
             for index, pitch in enumerate(strings * 3)]
    result = infer_tuning(notes, "bass")
    assert result["candidate"] == "Drop C"
    assert result["strings"] == strings
    assert result["confidence"] >= .5
