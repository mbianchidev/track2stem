import threading

import numpy as np
import pytest
import soundfile as sf

from track2stem_engine.sources import canonical_youtube_url, download_youtube


def test_youtube_import_only_accepts_videos_and_converts_owned_downloads(tmp_path, monkeypatch):
    import yt_dlp

    seen = []

    class Downloader:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, url, download):
            seen.append((url, download))
            sf.write(tmp_path / "source.wav", np.ones((4410, 2)) * .01, 44100)
            return {"duration": .1, "id": "abcdefghijk"}

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Downloader)
    path = download_youtube("https://youtu.be/abcdefghijk?t=12", tmp_path, threading.Event())
    assert sf.info(path).frames == 4410
    assert seen == [("https://www.youtube.com/watch?v=abcdefghijk", True)]
    for url in ("http://youtube.com/watch?v=abcdefghijk", "https://127.0.0.1/test",
                "https://www.youtube.com.evil.test/watch?v=abcdefghijk",
                "https://user:password@youtube.com/watch?v=abcdefghijk",
                "https://youtube.com/playlist?list=abcdefghijk"):
        with pytest.raises(ValueError):
            canonical_youtube_url(url)
