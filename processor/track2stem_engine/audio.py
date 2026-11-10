import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from threading import Event

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)


class CancelledError(RuntimeError):
    pass


def check_cancelled(cancelled):
    if cancelled.is_set():
        raise CancelledError("Cancelled by user")


def run_command(command, cancelled=None, timeout=600):
    cancelled = cancelled or Event()
    check_cancelled(cancelled)
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output, stderr=output)
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                check_cancelled(cancelled)
                if time.monotonic() > deadline:
                    raise TimeoutError(f"{Path(command[0]).name} timed out after {timeout}s")
                cancelled.wait(.1)
            output.seek(0)
            details = output.read()[-16000:].decode("utf-8", errors="replace")
            if process.returncode:
                logger.error("%s failed: %s", Path(command[0]).name, details)
                raise RuntimeError(f"{Path(command[0]).name} failed: {details.strip()}")
            check_cancelled(cancelled)
            return details
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def ffmpeg():
    return os.environ.get("TRACK2STEM_FFMPEG", "ffmpeg")


def read_audio(path, cancelled=None, sample_rate=44100):
    with tempfile.TemporaryDirectory(prefix="track2stem-decode-") as directory:
        decoded = Path(directory) / "decoded.wav"
        run_command([
            ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-protocol_whitelist", "file,pipe", "-i", str(path),
            "-vn", "-ac", "2", "-ar", str(sample_rate), "-c:a", "pcm_f32le", str(decoded),
        ], cancelled)
        info = sf.info(decoded)
        if not 0 < info.duration <= 3600:
            raise ValueError("Audio must be non-empty and no longer than 60 minutes")
        audio, rate = sf.read(decoded, dtype="float32", always_2d=True)
    if not np.isfinite(audio).all():
        raise ValueError("Audio contains non-finite samples")
    return audio, rate


def write_audio(path, audio, sample_rate, clip_mode="rescale", cancelled=None):
    path = Path(path)
    if audio.ndim != 2 or not audio.size or not np.isfinite(audio).all():
        raise ValueError("Cannot export empty or invalid audio")
    peak = float(np.max(np.abs(audio)))
    if clip_mode == "rescale" and peak > .999:
        audio = audio * (.999 / peak)
    elif clip_mode == "clamp":
        audio = np.clip(audio, -1, 1)
    with tempfile.TemporaryDirectory(prefix="track2stem-encode-") as directory:
        source = Path(directory) / "source.wav"
        sf.write(source, audio, sample_rate, subtype="FLOAT")
        codecs = {
            ".wav": ["-c:a", "pcm_s16le"],
            ".flac": ["-c:a", "flac", "-sample_fmt", "s16"],
            ".mp3": ["-c:a", "libmp3lame", "-b:a", "320k"],
        }
        run_command([
            ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), *codecs[path.suffix], str(path),
        ], cancelled)
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Audio export produced no data: {path.name}")
