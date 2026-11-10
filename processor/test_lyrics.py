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
    result, artifacts = generate_lyrics(np.zeros((44100, 2), dtype=np.float32), 44100,
                                       tmp_path / "artifacts", tmp_path / "models",
                                       lambda *_args: None, threading.Event())
    assert result["text"] == "Synthetic demo."
    assert result["words"][0]["start"] == .2
    assert "00:00:00,200 --> 00:00:01,100" in Path(artifacts["lyrics_srt"]).read_text()
    assert Path(artifacts["lyrics"]).read_text().strip() == "Synthetic demo."
