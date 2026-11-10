import numpy as np
import pytest

from track2stem_engine.analysis import analyze, make_click_track
from track2stem_engine.engine import Engine
from track2stem_engine.settings import Settings
import soundfile as sf


def test_tempo_change_and_click_track_follow_synthetic_beats():
    rate = 22050
    expected = np.concatenate((np.arange(0, 20, .5), np.arange(20, 40, 2 / 3)))
    audio = np.zeros(40 * rate, dtype=np.float32)
    click = np.sin(2 * np.pi * 1400 * np.arange(400) / rate) * np.hanning(400)
    for beat in expected:
        start = int(beat * rate)
        audio[start:start + len(click)] += click
    result = analyze(np.column_stack((audio, audio)), rate)
    early = [entry["bpm"] for entry in result["tempo_changes"] if 4 < entry["time"] < 15]
    late = [entry["bpm"] for entry in result["tempo_changes"] if 25 < entry["time"] < 36]
    assert np.median(early) == pytest.approx(120, abs=5)
    assert np.median(late) == pytest.approx(90, abs=5)
    rendered = make_click_track(result["beats"], len(audio), rate)
    assert rendered.shape == (len(audio), 2)
    assert np.max(np.abs(rendered)) <= 1
    for beat in result["beats"]:
        start = int(beat * rate)
        assert np.any(rendered[start:start + 800]), "Every detected beat needs an audible click"


def test_requested_analysis_and_click_are_exported_with_the_job(tmp_path, monkeypatch):
    source = tmp_path / "synthetic.wav"
    audio = np.full((4410, 2), .01, dtype=np.float32)
    sf.write(source, audio, 44100)
    expected = {"beats": [0, .05], "bpm": 120, "tempo_changes": [{"time": 0, "bpm": 120}],
                "sections": [{"start": 0, "end": .1, "label": "Intro", "confidence": .3}]}
    monkeypatch.setattr("track2stem_engine.analysis.analyze", lambda *_args, **_kwargs: expected)
    engine = Engine(tmp_path / "output", tmp_path / "models",
                    separator=lambda *_args: ({stem: audio for stem in Settings().stems}, 44100))
    result = engine.run(source, "synthetic-analysis", Settings(output_format="wav", click_track=True))
    assert result["analysis"] == expected
    click, rate = sf.read(result["artifacts"]["click"])
    assert rate == 44100 and len(click) == len(audio)
    assert np.max(np.abs(click)) > .1
    assert engine.load("synthetic-analysis")["analysis"]["bpm"] == 120
