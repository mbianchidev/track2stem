#!/usr/bin/env python3
import argparse
import io
import json
import math
import os
import selectors
import signal
import struct
import subprocess
import time
import urllib.request
import wave
from pathlib import Path


def fixture():
    rate = 44100
    data = io.BytesIO()
    with wave.open(data, "wb") as target:
        target.setparams((2, 2, rate, 0, "NONE", "not compressed"))
        audio = bytearray()
        for index in range(rate * 6):
            timepoint = index / rate
            phase = timepoint % .5
            click = .15 * math.sin(2 * math.pi * 1400 * phase) * math.exp(-phase * 120)
            sample = .12 * math.sin(2 * math.pi * 110 * timepoint) + .05 * math.sin(2 * math.pi * 440 * timepoint) + click
            audio.extend(struct.pack("<hh", round(sample * 32767), round(sample * .9 * 32767)))
        target.writeframes(audio)
    return data.getvalue()


def request(base, path, values=None, audio=None):
    if audio is not None:
        boundary = "track2stem-native-generated-fixture"
        body = bytearray()
        for key, value in values.items():
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode())
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"synthetic.wav\"\r\nContent-Type: audio/wav\r\n\r\n".encode())
        body.extend(audio)
        body.extend(f"\r\n--{boundary}--\r\n".encode())
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    elif values is not None:
        body = json.dumps(values).encode()
        headers = {"Content-Type": "application/json"}
    else:
        body, headers = None, {}
    with urllib.request.urlopen(urllib.request.Request(base + path, data=body, headers=headers), timeout=30) as response:
        return json.load(response)


def completed(base, job):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        job = request(base, "/jobs/" + job["id"])
        if job["status"] == "completed":
            return job
        if job["status"] == "failed":
            raise RuntimeError(job.get("error", "Native processing failed"))
        time.sleep(.2)
    raise TimeoutError("Native inference did not complete within three minutes")


def check_downloads(base, job, expected, codec, directory, ffprobe, duration=6):
    if set(job["output_files"]) != set(expected):
        raise AssertionError(f"Unexpected stems: {list(job['output_files'])}")
    for stem in expected:
        path = directory / f"{job['id']}-{stem}.{job['output_format']}"
        with urllib.request.urlopen(base + f"/download/{job['id']}/{stem}") as response:
            path.write_bytes(response.read())
        data = json.loads(subprocess.check_output([
            ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", path,
        ]))
        audio = next(stream for stream in data["streams"] if stream["codec_type"] == "audio")
        assert audio["codec_name"] == codec, audio
        assert int(audio["sample_rate"]) == 44100 and audio["channels"] == 2, audio
        assert abs(float(data["format"]["duration"]) - duration) < .12, data
        if codec == "pcm_s16le":
            assert audio["bits_per_sample"] == 16, audio
        if codec == "mp3":
            assert int(audio["bit_rate"]) == 320000, audio


def main():
    parser = argparse.ArgumentParser(description="Exercise the real packaged worker using generated audio")
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--models", type=Path)
    parser.add_argument("--ui", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fixture-only", type=Path)
    parser.add_argument("--youtube-url")
    parser.add_argument("--youtube-seconds", type=float)
    args = parser.parse_args()
    if args.fixture_only:
        args.fixture_only.write_bytes(fixture())
        return
    if not all((args.worker, args.models, args.ui, args.output)):
        parser.error("--worker, --models, --ui and --output are required for inference")
    if ((args.youtube_url is None) != (args.youtube_seconds is None)
            or (args.youtube_url is not None and not args.youtube_url.strip())
            or (args.youtube_seconds is not None and not 0 < args.youtube_seconds <= 3600)):
        parser.error("Live import requires both an authorized synthetic --youtube-url and positive --youtube-seconds")
    args.output.mkdir(parents=True, exist_ok=False)
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"PYTHONPATH", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH", "VIRTUAL_ENV"}}
    with (args.output / "worker.log").open("wb") as log:
        worker = subprocess.Popen([args.worker, "--root", args.output / "data", "--models", args.models,
                                   "--ui", args.ui, "--serve"], stdout=subprocess.PIPE, stderr=log,
                                  env=environment, start_new_session=True)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(worker.stdout, selectors.EVENT_READ)
                if not selector.select(timeout=30):
                    raise TimeoutError("Packaged worker did not report readiness")
                ready = json.loads(worker.stdout.readline())
            assert ready["version"] == 1 and ready["type"] == "ready", ready
            base = ready["api_base"]
            audio = fixture()
            six = completed(base, request(base, "/upload", {
                "output_format": "wav", "workers": "2", "analysis": "true", "click_track": "true",
                "guitar_tabs": "true", "bass_tabs": "true", "drum_tabs": "true",
            }, audio))
            ffprobe = args.worker.parent / "_internal/ffprobe"
            check_downloads(base, six, ("vocals", "drums", "bass", "guitar", "piano", "other"),
                            "pcm_s16le", args.output, ffprobe)
            assert {"analysis", "click", "guitar_score", "bass_midi", "drums_midi"} <= set(six["artifacts"])
            bass_notes = request(base, f"/artifacts/{six['id']}/bass_notes")
            assert bass_notes["selection_policy"] == "clean monophonic bassline"
            assert len(bass_notes["raw_candidates"]) >= len(bass_notes["notes"])
            assert six["transcriptions"]["bass"]["selection_policy"] == "clean monophonic bassline"
            assert "raw_candidates" not in six["transcriptions"]["bass"]
            assert all(first["end"] <= second["start"] for first, second in
                       zip(bass_notes["notes"], bass_notes["notes"][1:]))
            mixed = request(base, f"/jobs/{six['id']}/mix", {"gains": {"bass": 1.5, "drums": .5}})
            assert mixed["gains"]["bass"] == 1.5
            flac = completed(base, request(base, "/upload", {
                "output_format": "flac", "stem_mode": "isolate", "isolate_stem": "vocals",
                "split_vocals": "true", "lyrics": "true",
            }, audio))
            check_downloads(base, flac, ("lead_vocals", "backing_vocals", "instrumental"),
                            "flac", args.output, ffprobe)
            assert {"lyrics", "lyrics_srt", "lyrics_words"} <= set(flac["artifacts"])
            mp3 = completed(base, request(base, "/upload", {
                "output_format": "mp3", "stem_mode": "isolate", "isolate_stem": "drums",
                "model": "hdemucs_mmi",
            }, audio))
            check_downloads(base, mp3, ("drums", "backing"), "mp3", args.output, ffprobe)
            if args.youtube_url:
                imported = completed(base, request(base, "/import", {
                    "url": args.youtube_url,
                    "settings": {"model": "hdemucs_mmi", "segment": "7", "overlap": ".1",
                                 "output_format": "mp3", "stem_mode": "isolate", "isolate_stem": "vocals"},
                }))
                clock = args.output / "live-source-clock.wav"
                with urllib.request.urlopen(base + f"/stems/{imported['id']}/other") as response:
                    clock.write_bytes(response.read())
                info = json.loads(subprocess.check_output(
                    [ffprobe, "-v", "error", "-show_format", "-of", "json", clock]))
                duration = float(info["format"]["duration"])
                assert abs(duration - args.youtube_seconds) < 1, info
                check_downloads(base, imported, ("vocals", "instrumental"), "mp3", args.output, ffprobe, duration)
            print(json.dumps({"status": "pass", "contract": 1, "jobs": 4 if args.youtube_url else 3, "cpu_only": True,
                              "live_import": bool(args.youtube_url),
                              "formats": ["PCM16 WAV", "FLAC", "320-kbps MP3"],
                              "practice_artifacts": len(six["artifacts"]) + len(flac["artifacts"])}))
        finally:
            if worker.poll() is None:
                os.killpg(worker.pid, signal.SIGTERM)
                try:
                    worker.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    os.killpg(worker.pid, signal.SIGKILL)
                    worker.wait(timeout=3)
    diagnostics = (args.output / "worker.log").read_text(encoding="utf-8")
    assert "unrecognized arguments: -B" not in diagnostics, "Frozen multiprocessing bypassed freeze_support"
    assert "resource_tracker: process died unexpectedly" not in diagnostics, "Owned resource tracker crashed"


if __name__ == "__main__":
    main()
