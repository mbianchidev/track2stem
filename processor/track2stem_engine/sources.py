import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .audio import check_cancelled, ffmpeg

logger = logging.getLogger(__name__)


def canonical_youtube_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("Provide a single HTTPS YouTube video URL")
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.username is not None or parsed.port is not None:
            raise ValueError("Use an HTTPS YouTube URL without credentials or a port")
    except ValueError as error:
        raise ValueError("Invalid YouTube video URL") from error
    video = ""
    if parsed.hostname == "youtu.be":
        video = parsed.path.removeprefix("/")
    elif parsed.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            video = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith("/shorts/"):
            video = parsed.path.removeprefix("/shorts/")
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", video) is None:
        raise ValueError("Provide a single YouTube video, not a playlist or another website")
    return f"https://www.youtube.com/watch?v={video}"


def download_youtube(url, directory, cancelled):
    import yt_dlp

    url = canonical_youtube_url(url)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 600

    def progress(info):
        check_cancelled(cancelled)
        if time.monotonic() > deadline:
            raise TimeoutError("YouTube import timed out after 10 minutes")
        if info.get("downloaded_bytes", 0) > 100 * 1024 * 1024:
            raise ValueError("YouTube audio exceeds the 100 MiB download limit")

    def match(info, *, incomplete=False):
        check_cancelled(cancelled)
        if (info.get("duration") or 0) > 3600:
            return "Videos longer than 60 minutes are not supported"
        if info.get("is_live"):
            return "Live streams are not supported"
        return None

    node = os.environ.get("TRACK2STEM_NODE")
    options = {
        "format": "bestaudio/best", "outtmpl": str(directory / "source.%(ext)s"),
        "noplaylist": True, "playlistend": 1, "max_filesize": 100 * 1024 * 1024,
        "socket_timeout": 15, "retries": 1, "fragment_retries": 1,
        "skip_unavailable_fragments": False, "cachedir": False,
        "match_filter": match, "progress_hooks": [progress], "postprocessor_hooks": [progress],
        "logger": logger, "js_runtimes": {"node": {"path": node} if node else {}},
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
    }
    if Path(ffmpeg()).is_absolute():
        options["ffmpeg_location"] = str(Path(ffmpeg()).parent)
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as error:
        check_cancelled(cancelled)
        logger.error("YouTube import failed: %s", error)
        raise RuntimeError("YouTube import failed. The video may be unavailable, restricted, or require an extractor update. Upload a local audio file instead.") from error
    check_cancelled(cancelled)
    path = directory / "source.wav"
    if not info or not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError("YouTube import produced no audio. Check the duration/size limits or upload a local file.")
    return path
