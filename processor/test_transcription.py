import json
import xml.etree.ElementTree as ET

import mido
import numpy as np
import threading
from pathlib import Path

from track2stem_engine.transcription import pitched_notes, write_transcription


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
