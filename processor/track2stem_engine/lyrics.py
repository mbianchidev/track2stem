import json
import logging
import os
from functools import lru_cache
from pathlib import Path

import librosa
import numpy as np

from .audio import check_cancelled

logger = logging.getLogger(__name__)


def lyrics_model_name():
    name = os.environ.get("TRACK2STEM_LYRICS_MODEL", "large-v3-turbo")
    if name not in {"base", "small", "large-v3-turbo"}:
        logger.error("Unsupported TRACK2STEM_LYRICS_MODEL: %s", name)
        raise ValueError("TRACK2STEM_LYRICS_MODEL must be base, small or large-v3-turbo")
    return name


@lru_cache(maxsize=1)
def _whisper_model(model_dir, name):
    from faster_whisper import WhisperModel
    from huggingface_hub.errors import HfHubHTTPError, LocalEntryNotFoundError

    try:
        return WhisperModel(name, device="cpu", compute_type="int8",
                            cpu_threads=min(4, os.process_cpu_count() or 1),
                            download_root=str(Path(model_dir) / "whisper"),
                            local_files_only=os.environ.get("TRACK2STEM_OFFLINE") == "1")
    except (HfHubHTTPError, LocalEntryNotFoundError, OSError) as error:
        logger.error("Could not provision the local lyrics model: %s", error)
        raise RuntimeError(f"Lyrics model is unavailable. Connect once to download Whisper {name}, then retry.") from error


def get_whisper_model(model_dir):
    return _whisper_model(model_dir, lyrics_model_name())


def srt_time(seconds):
    milliseconds = max(0, round(seconds * 1000))
    return f"{milliseconds // 3600000:02}:{milliseconds // 60000 % 60:02}:{milliseconds // 1000 % 60:02},{milliseconds % 1000:03}"


def generate_lyrics(audio, sample_rate, directory, model_dir, report, cancelled):
    check_cancelled(cancelled)
    if audio.ndim != 2 or not audio.size or not np.isfinite(audio).all():
        raise ValueError("Lyrics need non-empty, finite audio")
    name = lyrics_model_name()
    mono = librosa.resample(audio.mean(axis=1), orig_sr=sample_rate, target_sr=16000).astype(np.float32)
    segments, language = [], None
    if np.max(np.abs(mono)) >= 1e-4:
        report(78, f"Loading local Whisper {name}; first use downloads model weights")
        model = get_whisper_model(str(model_dir))
        check_cancelled(cancelled)
        segments, info = model.transcribe(mono, beam_size=5, word_timestamps=True, vad_filter=False,
                                          condition_on_previous_text=False, no_speech_threshold=.6)
        language = info.language
    lines, words, subtitles = [], [], []
    rejected = 0
    for segment in segments:
        check_cancelled(cancelled)
        probability = getattr(segment, "no_speech_prob", 0)
        log_probability = getattr(segment, "avg_logprob", 0)
        word_confidence = np.mean([word.probability for word in segment.words]) if segment.words else 1
        if (probability > .9 or (probability > .6 and log_probability < -.5)
                or log_probability < -1.2 or word_confidence < .25):
            rejected += 1
            logger.warning("Excluded an unreliable lyrics segment at %.2fs", segment.start)
            continue
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
        "text": "\n".join(lines), "language": language, "words": words,
        "estimated": True, "model": name, "compute_type": "CPU int8", "rejected_segments": rejected,
        "warning": "Singing, distortion and overlapping voices can reduce transcription accuracy." if lines
                   else ("No words detected; unreliable no-speech segments were excluded." if rejected
                         else "No words detected. The source may be instrumental or vocals may be too faint."),
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
