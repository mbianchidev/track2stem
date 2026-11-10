#!/usr/bin/env python3
import argparse
import json
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

import soundfile as sf


CASES = (
    ("good-news", "Good News", "Bright notes follow the rhythm of the drums. We sing together as the melody rises."),
    ("cellos", "Cellos", "Keep the chorus moving with the bass. Let every voice return to the melody."),
)


def word_error_rate(reference, hypothesis):
    expected = re.findall(r"\w+", reference.casefold())
    actual = re.findall(r"\w+", hypothesis.casefold())
    if not expected:
        raise ValueError("A lyrics reference must contain words")
    costs = list(range(len(actual) + 1))
    for row, word in enumerate(expected, 1):
        previous, costs = costs, [row]
        for column, candidate in enumerate(actual, 1):
            costs.append(min(costs[-1] + 1, previous[column] + 1,
                             previous[column - 1] + (word != candidate)))
    return {"word_error_rate": costs[-1] / len(expected), "reference_words": len(expected),
            "word_errors": costs[-1], "hypothesis_words": len(actual)}


def main():
    parser = argparse.ArgumentParser(description="Measure local ASR on original, synthetically sung lyrics")
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--model", nargs="+", default=["base", "small"])
    parser.add_argument("--vad", choices=("on", "off", "both"), default="both")
    parser.add_argument("--generate-macos", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.generate_macos:
        if platform.system() != "Darwin":
            parser.error("The fixture generator uses existing macOS synthetic singing voices")
        if args.fixtures.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
            parser.error("Apple system-voice outputs must remain private, outside this repository")
        print("Apple system-voice outputs are for personal, non-commercial evaluation only; do not redistribute them.",
              file=sys.stderr)
        args.fixtures.mkdir(parents=True, exist_ok=True)
        for name, voice, _ in CASES:
            if (args.fixtures / f"{name}.wav").exists():
                parser.error("Singing fixtures already exist; do not overwrite evidence")
        for name, voice, text in CASES:
            source = args.fixtures / f"{name}.aiff"
            subprocess.run(["/usr/bin/say", "-v", voice, "-o", source, text], check=True)
            subprocess.run(["ffmpeg", "-v", "error", "-i", source, "-ar", "16000", "-ac", "1",
                            args.fixtures / f"{name}.wav"], check=True)
    if args.output.exists():
        parser.error("Output exists; choose a new evidence path")
    from faster_whisper import WhisperModel
    results = []
    for model_name in args.model:
        loaded = time.monotonic()
        model = WhisperModel(model_name, device="cpu", compute_type="int8",
                             cpu_threads=4, download_root=str(args.models / "whisper"))
        loading = time.monotonic() - loaded
        for name, voice, text in CASES:
            audio, rate = sf.read(args.fixtures / f"{name}.wav", dtype="float32")
            if rate != 16000 or audio.ndim != 1:
                raise ValueError("Singing fixtures must be mono 16-kHz audio")
            for vad in ([True, False] if args.vad == "both" else [args.vad == "on"]):
                started = time.monotonic()
                segments, info = model.transcribe(audio, beam_size=5, word_timestamps=True, vad_filter=vad,
                                                  condition_on_previous_text=False, no_speech_threshold=.6)
                transcript = " ".join(segment.text.strip() for segment in segments)
                result = {"model": model_name, "voice": voice, "synthetic_singing": True, "vad": vad,
                          "reference": text, "transcript": transcript, "language": info.language,
                          "duration_seconds": len(audio) / rate, "inference_seconds": time.monotonic() - started,
                          "loading_seconds": loading, **word_error_rate(text, transcript)}
                results.append(result)
                print(json.dumps(result), flush=True)
        del model
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"scope": "generated singing only; not a natural-singing accuracy claim",
                                      "results": results}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
