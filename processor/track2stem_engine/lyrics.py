import json
import logging
import os
from functools import lru_cache
from pathlib import Path

import librosa
import numpy as np

from .audio import check_cancelled

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_whisper_model(model_dir):
    from faster_whisper import WhisperModel
    from huggingface_hub.errors import HfHubHTTPError, LocalEntryNotFoundError

    try:
        return WhisperModel("base", device="cpu", compute_type="int8",
                            cpu_threads=min(4, os.process_cpu_count() or 1),
                            download_root=str(Path(model_dir) / "whisper"),
                            local_files_only=os.environ.get("TRACK2STEM_OFFLINE") == "1")
    except (HfHubHTTPError, LocalEntryNotFoundError, OSError) as error:
        logger.error("Could not provision the local lyrics model: %s", error)
        raise RuntimeError("Lyrics model is unavailable. Connect once to download Whisper base, then retry.") from error


def srt_time(seconds):
    milliseconds = max(0, round(seconds * 1000))
    return f"{milliseconds // 3600000:02}:{milliseconds // 60000 % 60:02}:{milliseconds // 1000 % 60:02},{milliseconds % 1000:03}"


def generate_lyrics(audio, sample_rate, directory, model_dir, report, cancelled):
    report(78, "Loading local Whisper base; first use downloads model weights")
    model = get_whisper_model(str(model_dir))
    check_cancelled(cancelled)
    mono = librosa.resample(audio.mean(axis=1), orig_sr=sample_rate, target_sr=16000).astype(np.float32)
    segments, info = model.transcribe(mono, beam_size=3, word_timestamps=True, vad_filter=True,
                                      condition_on_previous_text=False, no_speech_threshold=.6)
    lines, words, subtitles = [], [], []
    for segment in segments:
        check_cancelled(cancelled)
        text = segment.text.strip()
        if not text:
            continue
        lines.append(text)
        subtitles.append(f"{len(lines)}\n{srt_time(segment.start)} --> {srt_time(segment.end)}\n{text}\n")
        for word in segment.words or []:
            words.append({"start": round(word.start, 3), "end": round(word.end, 3),
                          "word": word.word.strip(), "confidence": round(word.probability, 3)})
        report(78 + int(4 * min(1, segment.end / max(len(mono) / 16000, .001))), "Transcribing lyrics locally")
    result = {
        "text": "\n".join(lines), "language": info.language, "words": words,
        "estimated": True,
        "warning": "Singing, distortion and overlapping voices can reduce transcription accuracy." if lines
                   else "No words detected. The source may be instrumental or vocals may be too faint.",
    }
    if not lines:
        logger.warning("Lyrics transcription detected no words")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    artifacts = {name: str(directory / filename) for name, filename in (
        ("lyrics", "lyrics.txt"), ("lyrics_srt", "lyrics.srt"), ("lyrics_words", "lyrics.json"))}
    Path(artifacts["lyrics"]).write_text(result["text"] + "\n" if lines else result["warning"] + "\n", encoding="utf-8")
    Path(artifacts["lyrics_srt"]).write_text("\n".join(subtitles), encoding="utf-8")
    Path(artifacts["lyrics_words"]).write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
    return result, artifacts
