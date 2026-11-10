import xml.etree.ElementTree as ET
from pathlib import Path

import mido
import numpy as np
import pytest

from track2stem_engine.analysis import make_click_track
from track2stem_engine.rhythm import decode_meter
from track2stem_engine.transcription import write_transcription


def test_meter_decoder_handles_three_four_then_four_four_despite_spurious_downbeats():
    beats = np.arange(56) * .5
    expected = [index % 3 == 0 if index < 24 else (index - 24) % 4 == 0 for index in range(56)]
    accents = np.where(expected, .95, .08)
    probabilities = np.where(expected, .9, .15)
    probabilities[5::7] = .65
    result = decode_meter(beats, probabilities, accents)
    assert [(entry["numerator"], entry["denominator"]) for entry in result["meter_changes"]] == [(3, 4), (4, 4)]
    assert result["meter_changes"][1]["time"] == pytest.approx(12, abs=.05)
    np.testing.assert_allclose(result["downbeats"], beats[expected], atol=.05)


def test_compound_meter_and_unaccented_uncertainty_are_not_forced_to_four_four():
    beats = np.arange(48) * .25
    downbeats = np.arange(48) % 6 == 0
    result = decode_meter(beats, np.where(downbeats, .9, .1), np.where(downbeats, .9, .1))
    assert result["meter_changes"][0]["numerator"] == 6
    assert result["meter_changes"][0]["denominator"] == 8
    assert result["meter_changes"][0]["pulse_quarters"] == .5
    unknown = decode_meter(beats, np.full(48, .5), np.ones(48))
    assert unknown["meter_changes"] == []
    assert unknown["downbeats"] == []


def test_click_accents_follow_detected_downbeats_instead_of_every_fourth_beat():
    rate = 22050
    beats = np.arange(6) * .5
    audio = make_click_track(beats, 3 * rate, rate, downbeats=[0, 1.5])
    for index, beat in enumerate(beats):
        samples = audio[round(beat * rate):round(beat * rate) + 770, 0]
        frequencies = np.fft.rfftfreq(len(samples), 1 / rate)
        frequency = frequencies[np.argmax(np.abs(np.fft.rfft(samples)))]
        assert frequency == pytest.approx(1800 if index in (0, 3) else 1200, abs=35)


def test_midi_and_musicxml_preserve_meter_changes_and_compound_click_units(tmp_path):
    notes = [{"start": 0, "end": 6, "pitch": 48, "velocity": 100}]
    tempos = [{"time": 0, "bpm": 120}, {"time": 3, "bpm": 90}]
    meters = [
        {"time": 0, "numerator": 3, "denominator": 4, "pulse_quarters": 1},
        {"time": 3, "numerator": 6, "denominator": 8, "pulse_quarters": 1.5},
    ]
    artifacts = write_transcription(notes, "guitar", tmp_path, tempos, meters=meters)
    midi = mido.MidiFile(artifacts["guitar_midi"])
    signatures, tick = [], 0
    for message in midi.tracks[0]:
        tick += message.time
        if message.type == "time_signature":
            signatures.append((tick, message.numerator, message.denominator, message.clocks_per_click))
    assert signatures == [(0, 3, 4, 24), (2880, 6, 8, 36)]
    score = ET.parse(artifacts["guitar_score"])
    assert [(time.findtext("beats"), time.findtext("beat-type"))
            for time in score.findall(".//attributes/time")] == [("3", "4"), ("6", "8")]
    assert "assumed 4/4" not in Path(artifacts["guitar_tabs"]).read_text()


def test_unknown_meter_is_explicitly_unmetered_in_notation(tmp_path):
    artifacts = write_transcription([{"start": 0, "end": .5, "pitch": 36, "velocity": 80}],
                                    "drums", tmp_path, meters=[])
    score = ET.parse(artifacts["drums_score"])
    assert score.find(".//time/senza-misura") is not None
    assert not any(message.type == "time_signature" for message in mido.MidiFile(artifacts["drums_midi"]).tracks[0])


@pytest.mark.parametrize("beats, probabilities, accents", [
    ([0, 1, .5], [.5] * 3, [1.] * 3),
    ([0, .5, 1], [.5], [1.] * 3),
    ([0, .5, 1], [.5, np.nan, .5], [1.] * 3),
])
def test_invalid_meter_evidence_fails_clearly(beats, probabilities, accents):
    with pytest.raises(ValueError):
        decode_meter(beats, probabilities, accents)
