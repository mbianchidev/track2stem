import threading
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

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


def test_real_downloader_and_ffmpeg_convert_a_synthetic_network_fixture(tmp_path, monkeypatch):
    import yt_dlp

    media = tmp_path / "media"
    media.mkdir()
    time = np.arange(4410) / 44100
    tone = .1 * np.sin(2 * np.pi * 440 * time)
    sf.write(media / "synthetic.flac", np.column_stack((tone, tone * .8)), 44100)
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(SimpleHTTPRequestHandler, directory=media))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    extract = yt_dlp.YoutubeDL.extract_info

    def network_fixture(self, url, *args, **kwargs):
        if url == "https://www.youtube.com/watch?v=abcdefghijk":
            url = f"http://127.0.0.1:{server.server_port}/synthetic.flac"
        return extract(self, url, *args, **kwargs)

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", network_fixture)
    try:
        output = download_youtube("https://youtu.be/abcdefghijk", tmp_path / "download", threading.Event())
        info = sf.info(output)
        assert info.format == "WAV" and info.frames == 4410 and info.channels == 2
        decoded, rate = sf.read(output)
        assert rate == 44100
        np.testing.assert_allclose(decoded[:, 0], tone, atol=2 / 32768)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
