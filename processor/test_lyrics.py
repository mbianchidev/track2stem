import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from track2stem_engine.lyrics import generate_lyrics


def test_lyrics_export_text_subtitles_and_word_timing(tmp_path, monkeypatch):
    class Model:
        def transcribe(self, audio, **_kwargs):
            assert audio.ndim == 1
            return iter([SimpleNamespace(
                start=.2, end=1.1, text=" Synthetic demo.",
                words=[SimpleNamespace(start=.2, end=.6, word=" Synthetic", probability=.9),
                       SimpleNamespace(start=.7, end=1.1, word=" demo.", probability=.95)],
            )]), SimpleNamespace(language="en", language_probability=.95)

    monkeypatch.setattr("track2stem_engine.lyrics.get_whisper_model", lambda *_args: Model())
    result, artifacts = generate_lyrics(np.full((88200, 2), .02, dtype=np.float32), 44100,
                                       tmp_path / "artifacts", tmp_path / "models",
                                       lambda *_args: None, threading.Event())
    assert result["text"] == "Synthetic demo."
    assert result["words"][0]["start"] == .2
    assert "00:00:00,200 --> 00:00:01,100" in Path(artifacts["lyrics_srt"]).read_text()
    assert Path(artifacts["lyrics"]).read_text().strip() == "Synthetic demo."


def test_singing_preserves_notes_without_speech_vad_and_keeps_word_timings(tmp_path, monkeypatch):
    seen = {}

    class Model:
        def transcribe(self, audio, **options):
            seen.update(options)
            word = SimpleNamespace(start=.1, end=.5, word=" melody", probability=.95)
            segment = SimpleNamespace(start=.1, end=.5, text="Melody", words=[word],
                                      no_speech_prob=.02, avg_logprob=-.1)
            return iter([segment]), SimpleNamespace(language="en")

    monkeypatch.delenv("TRACK2STEM_LYRICS_MODEL", raising=False)
    monkeypatch.setattr("track2stem_engine.lyrics.get_whisper_model", lambda *_args: Model())
    audio = np.full((16000, 2), .02, dtype=np.float32)
    result, artifacts = generate_lyrics(audio, 16000, tmp_path, tmp_path, lambda *_: None, threading.Event())
    assert seen["beam_size"] == 5
    assert seen["vad_filter"] is False
    assert result["model"] == "large-v3-turbo"
    assert result["text"] == "Melody"
    assert result["words"] == [{"start": .1, "end": .5, "word": "melody", "confidence": .95}]
    assert "00:00:00,100 --> 00:00:00,500" in Path(artifacts["lyrics_srt"]).read_text()


def test_unreliable_no_speech_segments_are_not_presented_as_lyrics(tmp_path, monkeypatch):
    class Model:
        def transcribe(self, audio, **options):
            word = SimpleNamespace(start=0., end=.8, word=" invented", probability=.1)
            segment = SimpleNamespace(start=0., end=.8, text="Invented", words=[word],
                                      no_speech_prob=.95, avg_logprob=-1.8)
            return iter([segment]), SimpleNamespace(language="en")

    monkeypatch.setattr("track2stem_engine.lyrics.get_whisper_model", lambda *_args: Model())
    result, _ = generate_lyrics(np.full((16000, 2), .02, dtype=np.float32), 16000,
                               tmp_path, tmp_path, lambda *_: None, threading.Event())
    assert result["text"] == ""
    assert result["words"] == []
    assert result["rejected_segments"] == 1
    assert "unreliable" in result["warning"].lower()


def test_silent_vocals_do_not_download_or_run_a_lyrics_model(tmp_path, monkeypatch):
    def unexpected(*_args):
        raise AssertionError("Silent vocals must not provision the large lyrics model")

    monkeypatch.setattr("track2stem_engine.lyrics.get_whisper_model", unexpected)
    result, _ = generate_lyrics(np.zeros((16000, 2), dtype=np.float32), 16000,
                               tmp_path, tmp_path, lambda *_: None, threading.Event())
    assert result["text"] == ""
    assert "no words" in result["warning"].lower()
