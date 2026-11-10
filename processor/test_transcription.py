import json
import xml.etree.ElementTree as ET

import mido
import numpy as np
import pytest
import threading
from pathlib import Path

from track2stem_engine.transcription import align_note_attacks, pitched_notes, write_transcription


def test_playable_guitar_score_and_drum_midi_share_timed_events(tmp_path):
    tempo = [{"time": 0, "bpm": 120}, {"time": 1, "bpm": 90}]
    guitar = [
        {"start": 0, "end": .5, "pitch": pitch, "velocity": 90}
        for pitch in (40, 45, 50)
    ] + [{"start": .75, "end": 1.5, "pitch": 64, "velocity": 100}]
    artifacts = write_transcription(guitar, "guitar", tmp_path, tempo)
    score = ET.parse(artifacts["guitar_score"])
    assert score.findtext(".//staff-lines") == "6"
    technical = score.findall(".//technical")
    assert len(technical) >= 4
    assert all(item.find("string") is not None and item.find("fret") is not None for item in technical)
    assert "guitar" in Path(artifacts["guitar_tabs"]).read_text(encoding="utf-8").lower()
    drums = [{"start": time, "end": time + .05, "pitch": pitch, "velocity": 100}
             for time, pitch in ((0, 36), (.5, 38), (1, 42), (1.666667, 36))]
    artifacts = write_transcription(drums, "drums", tmp_path, tempo)
    midi = mido.MidiFile(artifacts["drums_midi"])
    hits = [message for track in midi.tracks for message in track if message.type == "note_on"]
    assert [hit.note for hit in hits] == [36, 38, 42, 36]
    assert all(hit.channel == 9 for hit in hits)
    tempos = [message.tempo for track in midi.tracks for message in track if message.type == "set_tempo"]
    assert tempos == [500000, 666667]
    with open(artifacts["drums_notes"], encoding="utf-8") as source:
        assert json.load(source)["notes"] == drums


def test_repeated_attacks_do_not_discard_a_sustained_pitch(tmp_path, monkeypatch):
    class Model:
        def run(self, _names, _inputs):
            frames = np.zeros((1, 172, 88), dtype=np.float32)
            attacks = frames.copy()
            frames[0, 20:100, 64 - 21] = .8
            attacks[0, 20:23, 64 - 21] = .9
            attacks[0, 60:63, 64 - 21] = .9
            return frames, attacks

    monkeypatch.setattr("track2stem_engine.transcription.get_session", lambda *_args: Model())
    notes = pitched_notes(np.zeros((44100, 2), dtype=np.float32), 44100, "guitar",
                          tmp_path, lambda *_args: None, threading.Event())
    assert len(notes) == 2
    assert all(note["pitch"] == 64 and note["end"] - note["start"] > .2 for note in notes)


@pytest.mark.parametrize("pitch", [21, 23])
@pytest.mark.filterwarnings("error::RuntimeWarning")
def test_clean_bassline_keeps_extended_range_and_preserves_octave_candidates(tmp_path, monkeypatch, pitch):
    class Model:
        def run(self, _names, _inputs):
            frames = np.zeros((1, 172, 88), dtype=np.float32)
            attacks = frames.copy()
            frames[0, 20:100, pitch - 21] = .9
            frames[0, 20:100, pitch + 12 - 21] = .7
            return frames, attacks

    monkeypatch.setattr("track2stem_engine.transcription.get_session", lambda *_args: Model())
    rate = 44100
    time = np.arange(rate) / rate
    waveform = .1 * np.sin(2 * np.pi * 440 * 2 ** ((pitch - 69) / 12) * time)
    audio = np.column_stack((waveform, waveform)).astype(np.float32)
    details = {}
    notes = pitched_notes(audio, rate, "bass", tmp_path, lambda *_: None,
                          threading.Event(), details=details)
    assert [entry["pitch"] for entry in notes] == [pitch]
    assert {entry["pitch"] for entry in details["raw_candidates"]} == {pitch, pitch + 12}
    artifacts = write_transcription(notes, "bass", tmp_path, details=details)
    saved = json.loads(Path(artifacts["bass_notes"]).read_text())
    assert saved["notes"] == notes
    assert saved["raw_candidates"] == details["raw_candidates"]
    assert saved["selection_policy"] == "clean monophonic bassline"


def test_pitched_onsets_follow_actual_attacks_instead_of_delayed_pitch_activation(tmp_path, monkeypatch):
    class Model:
        def run(self, _names, _inputs):
            frames = np.zeros((1, 172, 88), dtype=np.float32)
            for start in (.2, .7):
                first = 15 + round(start * 22050 / 256)
                frames[0, first:first + 20, 64 - 21] = .8
            return frames, np.zeros_like(frames)

    monkeypatch.setattr("track2stem_engine.transcription.get_session", lambda *_args: Model())
    rate = 44100
    waveform = np.zeros(rate)
    time = np.arange(round(rate * .25)) / rate
    for onset in (.1, .6):
        waveform[round(onset * rate):round(onset * rate) + len(time)] = (
            .1 * np.sin(2 * np.pi * 329.6276 * time) * (1 - np.exp(-300 * time)) * np.exp(-10 * time))
    notes = pitched_notes(np.column_stack((waveform, waveform)).astype(np.float32), rate, "guitar",
                          tmp_path, lambda *_: None, threading.Event())
    assert [entry["start"] for entry in notes] == pytest.approx([.1, .6], abs=.035)


def test_backtracking_does_not_create_negative_or_duplicate_same_pitch_notes(monkeypatch):
    monkeypatch.setattr("librosa.onset.onset_detect", lambda **_: np.array([0., .5]))
    notes = [{"start": .02, "end": .1, "pitch": 64, "velocity": 80},
             {"start": .1, "end": .4, "pitch": 64, "velocity": 90}]
    aligned, _ = align_note_attacks(notes, np.zeros(22050), {(.1, 64)})
    assert aligned == [{"start": 0., "end": .4, "pitch": 64, "velocity": 90}]
    assert notes[0]["start"] == .02


def test_full_kit_musicxml_and_midi_preserve_distinct_drum_instruments(tmp_path):
    pitches = [36, 38, 42, 46, 41, 47, 50, 49, 51]
    notes = [{"start": index * .25, "end": index * .25 + .1, "pitch": pitch, "velocity": 100}
             for index, pitch in enumerate(pitches)]
    artifacts = write_transcription(notes, "drums", tmp_path, meters=[])
    score = ET.parse(artifacts["drums_score"])
    declared = {item.attrib["id"]: int(item.findtext("midi-unpitched")) - 1
                for item in score.findall(".//midi-instrument")}
    assert declared == {f"D{pitch}": pitch for pitch in pitches}
    instrument_notes = [item for item in score.findall(".//note") if item.find("instrument") is not None]
    assert {item.find("instrument").attrib["id"] for item in instrument_notes} == set(declared)
    open_hat = next(item for item in instrument_notes if item.find("instrument").attrib["id"] == "D46")
    assert open_hat.findtext("notehead") == "circle-x"
    hits = [message.note for message in mido.MidiFile(artifacts["drums_midi"]).tracks[0]
            if message.type == "note_on" and message.velocity > 0]
    assert hits == pitches
    text = Path(artifacts["drums_tabs"]).read_text()
    assert all(name in text for name in ("Open hi-hat", "Low tom", "Mid tom", "High tom", "Crash", "Ride"))
