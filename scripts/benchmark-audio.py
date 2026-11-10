#!/usr/bin/env python3
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import resource
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import mido
import numpy as np
import soundfile as sf
from scipy.optimize import linear_sum_assignment

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "processor"))
RATE = 44100
STEMS = ("vocals", "drums", "bass", "guitar", "piano", "other")
FONT_SHA256 = "9575028c7a1f589f5770fccc8cff2734566af40cd26ed836944e9a5152688cfe"
FONT_URL = "https://raw.githubusercontent.com/mrbumpy409/GeneralUser-GS/684543d5e5efaef08d02be50dcda8d552478fa60/GeneralUser-GS.sf2"
FONT_LICENSE = "https://github.com/mrbumpy409/GeneralUser-GS/blob/684543d5e5efaef08d02be50dcda8d552478fa60/documentation/LICENSE.txt"
PROGRAMS = {"vocals": 54, "drums": 0, "bass": 33, "guitar": 25, "piano": 0, "other": 48}
DRUM_CANONICAL = {35: 36, 40: 38, 43: 41, 45: 41, 48: 47, 53: 51, 57: 49, 59: 51}


def si_sdr(reference, estimate):
    reference = np.asarray(reference, dtype=np.float64).reshape(-1)
    estimate = np.asarray(estimate, dtype=np.float64).reshape(-1)
    if (reference.shape != estimate.shape or not len(reference)
            or not np.isfinite(reference).all() or not np.isfinite(estimate).all()):
        raise ValueError("SI-SDR needs equal, non-empty sample arrays")
    reference = reference - reference.mean()
    estimate = estimate - estimate.mean()
    norm = float(np.dot(reference, reference))
    if norm < 1e-12:
        return {"si_sdr_db": None, "reason": "silent reference"}
    if np.dot(estimate, estimate) < 1e-12:
        return {"si_sdr_db": None, "reason": "silent estimate"}
    target = reference * np.dot(estimate, reference) / norm
    error = estimate - target
    return {"si_sdr_db": float(10 * np.log10(max(float(np.dot(target, target)), 1e-20)
                                             / max(float(np.dot(error, error)), 1e-20)))}


def event_metrics(reference, predicted, tolerance=.05):
    classes = sorted({note["pitch"] for note in reference} | {note["pitch"] for note in predicted})
    result, totals = {}, [0, 0, 0]
    for pitch in classes:
        expected = [note["start"] for note in reference if note["pitch"] == pitch]
        actual = [note["start"] for note in predicted if note["pitch"] == pitch]
        true = 0
        if expected and actual:
            distances = np.abs(np.asarray(expected)[:, None] - np.asarray(actual)[None, :])
            rows, columns = linear_sum_assignment(np.where(distances <= tolerance, distances, 1e6))
            true = int(np.count_nonzero(distances[rows, columns] <= tolerance))
        false, missing = len(actual) - true, len(expected) - true
        result[str(pitch)] = {"true": true, "false": false, "missing": missing,
                              "f1": 2 * true / max(1, 2 * true + false + missing)}
        totals = [total + value for total, value in zip(totals, (true, false, missing))]
    true, false, missing = totals
    return {"tolerance_seconds": tolerance, "precision": true / max(1, true + false),
            "recall": true / max(1, true + missing), "f1": 2 * true / max(1, 2 * true + false + missing),
            "per_class": result}


def font_file(args, output):
    path = args.soundfont or ROOT / "plugin/build/test-fixtures/GeneralUser-GS.sf2"
    if not path.exists():
        path = output / "assets/GeneralUser-GS.sf2"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".part")
        try:
            with urllib.request.urlopen(FONT_URL, timeout=30) as source, temporary.open("xb") as target:
                while block := source.read(1024 * 1024):
                    target.write(block)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    with path.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != FONT_SHA256:
            raise RuntimeError("The reference SoundFont does not match its published benchmark fingerprint")
    return path


def render_midi(notes, instrument, path, duration, font, program=None):
    channel = 9 if instrument == "drums" else 0
    midi, track = mido.MidiFile(ticks_per_beat=480), mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=500000))
    track.append(mido.Message("program_change", channel=channel, program=PROGRAMS[instrument] if program is None else program))
    events = []
    for note in notes:
        start, end = round(note["start"] * 960), round(min(duration, note["end"]) * 960)
        if end <= start:
            continue
        events.extend(((start, 1, mido.Message("note_on", channel=channel, note=note["pitch"], velocity=note["velocity"])),
                       (end, 0, mido.Message("note_off", channel=channel, note=note["pitch"], velocity=0))))
    previous = 0
    for tick, _, event in sorted(events, key=lambda value: value[:2]):
        event.time = tick - previous
        track.append(event)
        previous = tick
    track.append(mido.MetaMessage("end_of_track", time=max(0, round(duration * 960) - previous)))
    midi_path, raw = path.with_suffix(".mid"), path.with_suffix(".render.wav")
    midi.save(midi_path)
    try:
        subprocess.run(["fluidsynth", "-qni", "-R", "0", "-C", "0", "-g", ".8", "-r", str(RATE),
                        "-F", raw, font, midi_path], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["ffmpeg", "-v", "error", "-i", raw, "-t", str(duration), "-ar", str(RATE),
                        "-ac", "2", "-c:a", "pcm_f32le", path], check=True)
    finally:
        raw.unlink(missing_ok=True)


def note(start, pitch, velocity=85, duration=.2):
    return {"start": float(start), "end": float(start + duration), "pitch": int(pitch), "velocity": int(velocity)}


def arrangement(sections, style):
    result = {stem: [] for stem in STEMS}
    for section in sections:
        start, end, label = section["start"], section["end"], section["label"]
        roots = (50, 46, 53, 55) if label == "Bridge" else (48, 43, 45, 41) if label == "Chorus" else (45, 41, 48, 43)
        vocal = 0 if label in {"Intro", "Solo", "Outro"} else 95 if label == "Chorus" else 58
        for index, beat in enumerate(np.arange(start, end, .5)):
            root = roots[(index // 4) % len(roots)]
            factor = min(1., (end - beat) / 4) if label == "Outro" else 1.
            velocity = max(1, round((100 if label in {"Chorus", "Solo"} else 65) * factor))
            result["bass"].append(note(beat, root - 12, velocity, .4))
            guitar_notes = (root + 24 + index % 12,) if label == "Solo" else (root, root + 7, root + 12)
            for pitch in guitar_notes:
                result["guitar"].append(note(beat, pitch, velocity, .35))
            if index % 2 == 0:
                for pitch in (root + 24, root + 28, root + 31):
                    result["piano"].append(note(beat, pitch, max(1, round(velocity * .5)), .7))
            if index % 4 == 0:
                result["other"].append(note(beat, root + 19, 85 if label == "Bridge" else 35, 1.8))
            if vocal and index % 2 == 0:
                result["vocals"].append(note(beat, root + 24 + (index // 2 % 3) * 2, vocal, .85))
            if label != "Intro" or index % 4 == 0:
                result["drums"].append(note(beat, 36 if index % 2 == 0 else 38, velocity, .1))
            if label not in {"Intro", "Outro"}:
                result["drums"].append(note(beat, 51 if label == "Solo" else 42, max(1, round(velocity * .65)), .1))
                result["drums"].append(note(beat + .25, 42, max(1, round(velocity * .5)), .1))
            if label == "Chorus" and index % 8 == 0:
                result["drums"].append(note(beat, 49, velocity, .1))
    return result


def render_song(root, sections, style, font):
    root.mkdir(parents=True, exist_ok=False)
    duration = sections[-1]["end"]
    expected = arrangement(sections, style)
    stems = {}
    for instrument, notes in expected.items():
        path = root / f"{instrument}.wav"
        render_midi(notes, instrument, path, duration, font,
                    program=30 if instrument == "guitar" and style == "metal" else None)
        stems[instrument], _ = sf.read(path, dtype="float32", always_2d=True)
    mixture = sum(stems.values())
    gain = min(1., .85 / max(float(np.max(np.abs(mixture))), 1e-8))
    for instrument in stems:
        sf.write(root / f"{instrument}.wav", stems[instrument] * gain, RATE, subtype="FLOAT")
    sf.write(root / "mixture.wav", mixture * gain, RATE, subtype="FLOAT")
    (root / "reference.json").write_text(json.dumps({"duration": duration, "sections": sections,
                                                   "style": style, "font_sha256": FONT_SHA256}, indent=2))
    return root


def separation_case(spec, models):
    from track2stem_engine.separation import Separator
    from track2stem_engine.settings import Settings

    case = Path(spec["case"])
    settings = Settings(model=spec["model"], output_format="wav", workers=spec["workers"], overlap=spec["overlap"],
                        segment=spec.get("segment"))
    separator = Separator(models)
    before = resource.getrusage(resource.RUSAGE_SELF)
    started = time.monotonic()
    estimates, rate = separator(case / "mixture.wav", settings, lambda *_: None, threading.Event())
    cold = time.monotonic() - started
    del estimates
    warm = []
    for index in range(spec["repeats"]):
        if index:
            del estimates
        started = time.monotonic()
        estimates, rate = separator(case / "mixture.wav", settings, lambda *_: None, threading.Event())
        warm.append(time.monotonic() - started)
    after = resource.getrusage(resource.RUSAGE_SELF)
    rss = after.ru_maxrss * (1 if platform.system() == "Darwin" else 1024)
    references = {stem: sf.read(case / f"{stem}.wav", dtype="float32", always_2d=True)[0] for stem in STEMS}
    actual = dict(estimates)
    if "guitar" in actual:
        actual["other"] = actual["other"] + actual["guitar"] + actual["piano"]
    references["other"] = references["other"] + references["guitar"] + references["piano"]
    quality = {stem: si_sdr(references[stem], actual[stem]) for stem in ("vocals", "drums", "bass", "other")}
    directory = Path(spec["results"])
    directory.mkdir(parents=True, exist_ok=False)
    for stem, audio in estimates.items():
        sf.write(directory / f"{stem}.wav", audio, rate, subtype="FLOAT")
    duration = len(next(iter(estimates.values()))) / rate
    report = {"case": case.name, "model": settings.model, "workers": settings.workers, "overlap": settings.overlap,
              "segment": settings.segment,
              "libraries": {name: importlib.metadata.version(name) for name in ("torch", "torchaudio", "demucs", "numpy")},
              "duration_seconds": duration, "cold_seconds": cold, "warm_seconds": warm,
              "warm_median_seconds": float(np.median(warm)), "real_time_factor": float(np.median(warm)) / duration,
              "process_peak_rss_bytes": rss,
              "process_cpu_seconds": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
              "common_four_stem_quality": quality}
    Path(spec["report"]).write_text(json.dumps(report, indent=2, allow_nan=False))


def separation_benchmark(cases, output, models, repeats):
    reports = []
    for case in cases:
        for model, overlap in (("htdemucs_6s", .25), ("hdemucs_mmi", .1)):
            for workers in (1, 2, 4):
                if workers > (os.process_cpu_count() or 1):
                    continue
                name = f"{case.name}-{model}-w{workers}"
                spec = {"case": str(case), "model": model, "workers": workers, "overlap": overlap, "repeats": repeats,
                        "segment": 7 if model == "hdemucs_mmi" else None,
                        "results": str(output / name), "report": str(output / f"{name}.json")}
                specification = output / f"{name}.input.json"
                specification.write_text(json.dumps(spec))
                subprocess.run([sys.executable, __file__, "--models", models, "--run-case", specification], check=True)
                report = json.loads(Path(spec["report"]).read_text())
                if workers > 1:
                    baseline = output / f"{case.name}-{model}-w1"
                    difference = 0.
                    for stem in (STEMS if model == "htdemucs_6s" else ("vocals", "drums", "bass", "other")):
                        first, _ = sf.read(baseline / f"{stem}.wav", dtype="float32", always_2d=True)
                        second, _ = sf.read(Path(spec["results"]) / f"{stem}.wav", dtype="float32", always_2d=True)
                        difference = max(difference, float(np.max(np.abs(first - second))))
                    report["parallel_maximum_sample_difference"] = difference
                reports.append(report)
                print(json.dumps(report), flush=True)
    return reports


def drum_benchmark(output, font, models):
    from track2stem_engine.drums import drum_notes

    reports = []
    pitches = (36, 38, 42, 46, 41, 47, 48, 50, 49, 51)
    for program in (0, 8, 16):
        path = output / f"drum-kit-{program}.wav"
        reference = [note(1 + index * 2, pitch, 100, .1) for index, pitch in enumerate(pitches)]
        render_midi(reference, "drums", path, 23, font, program=program)
        started = time.monotonic()
        predicted = drum_notes(path, models, lambda *_: None, threading.Event())
        expected = [{**event, "pitch": DRUM_CANONICAL.get(event["pitch"], event["pitch"])} for event in reference]
        actual = [{**event, "pitch": DRUM_CANONICAL.get(event["pitch"], event["pitch"])} for event in predicted]
        report = {"kit_program": program, "elapsed_seconds": time.monotonic() - started,
                  "reference": expected, "predicted": actual, **event_metrics(expected, actual)}
        reports.append(report)
        print(json.dumps(report), flush=True)
    return reports


def pitched_benchmark(cases, models):
    from track2stem_engine.transcription import assign_frets, pitched_notes

    reports = []
    for case in cases:
        reference = json.loads((case / "reference.json").read_text())
        expected = arrangement(reference["sections"], reference["style"])
        for instrument in ("guitar", "bass"):
            audio, rate = sf.read(case / f"{instrument}.wav", dtype="float32", always_2d=True)
            details = {}
            notes = pitched_notes(audio, rate, instrument, models, lambda *_: None, threading.Event(), details)
            if any(not 0 <= note["start"] < note["end"] <= len(audio) / rate for note in notes):
                raise RuntimeError("Pitched transcription produced invalid event timing")
            assigned, tuning = assign_frets(notes, instrument)
            invalid = [note for note in assigned if "string" in note
                       and (note["pitch"] != tuning[-note["string"]] + note["fret"] or not 0 <= note["fret"] <= 24)]
            report = {"case": case.name, "instrument": instrument,
                      "scope": "rendered reference stem, not separation-plus-transcription accuracy",
                      "raw_candidates": len(details["raw_candidates"]), "selected_notes": len(notes),
                      "unassigned_fingerings": sum("string" not in note for note in assigned),
                      "invalid_assigned_pitches": len(invalid), "onset_alignment": details["onset_alignment"],
                      "raw_candidate_metrics": event_metrics(expected[instrument], details["raw_candidates"]),
                      **event_metrics(expected[instrument], notes)}
            reports.append(report)
            print(json.dumps(report), flush=True)
    return reports


def structure_benchmark(output, font, models):
    from track2stem_engine.separation import Separator
    from track2stem_engine.settings import Settings

    layout = (("Intro", 8), ("Verse", 16), ("Chorus", 16), ("Verse", 16), ("Chorus", 16),
              ("Bridge", 16), ("Solo", 16), ("Chorus", 16), ("Outro", 8))
    sections, previous = [], 0
    for label, duration in layout:
        sections.append({"start": previous, "end": previous + duration, "label": label})
        previous += duration
    case = render_song(output / "structure", sections, "metal", font)
    report = structure_metrics(case, models)
    separator = Separator(models)
    estimates, _ = separator(case / "mixture.wav", Settings(workers=2), lambda *_: None, threading.Event())
    report["end_to_end"] = structure_metrics(case, models, estimates)
    layout = (("Intro", 6), ("Verse", 12), ("Chorus", 12), ("Verse", 12), ("Chorus", 12),
              ("Bridge", 8), ("Solo", 10), ("Chorus", 12), ("Outro", 6))
    sections, previous = [], 0
    for label, duration in layout:
        sections.append({"start": previous, "end": previous + duration, "label": label})
        previous += duration
    case = render_song(output / "structure-holdout", sections, "clean", font)
    report["holdout"] = structure_metrics(case, models)
    estimates, _ = separator(case / "mixture.wav", Settings(workers=2), lambda *_: None, threading.Event())
    report["holdout"]["end_to_end"] = structure_metrics(case, models, estimates)
    return report


def structure_metrics(case, models, estimates=None):
    from track2stem_engine.analysis import analyze

    reference = json.loads((case / "reference.json").read_text())
    sections, duration = reference["sections"], reference["duration"]
    audio, _ = sf.read(case / "mixture.wav", dtype="float32", always_2d=True)
    stems = estimates if estimates is not None else {
        stem: sf.read(case / f"{stem}.wav", dtype="float32", always_2d=True)[0] for stem in STEMS}
    result = analyze(audio, RATE, stems, threading.Event(), models, lambda *_: None)
    predicted = result["sections"]
    expected_boundaries = [{"start": entry["start"], "pitch": 0} for entry in sections[1:]]
    actual_boundaries = [{"start": entry["start"], "pitch": 0} for entry in predicted[1:]]
    edges = sorted({0, duration, *[entry[key] for entry in predicted for key in ("start", "end")],
                    *[entry[key] for entry in sections for key in ("start", "end")]})
    correct = 0.
    per_label = {label: {"correct_seconds": 0., "reference_seconds": 0.} for label in {entry["label"] for entry in sections}}
    for left, right in zip(edges, edges[1:]):
        middle = (left + right) / 2
        expected = next((entry["label"] for entry in sections if entry["start"] <= middle < entry["end"]), None)
        actual = next((entry["label"] for entry in predicted if entry["start"] <= middle < entry["end"]), None)
        if expected in per_label:
            per_label[expected]["reference_seconds"] += right - left
        if expected == actual:
            correct += right - left
            per_label[expected]["correct_seconds"] += right - left
    return {"scope": "generated arrangement with known instrument activity; not a natural-song accuracy claim",
            "stem_source": "htdemucs_6s inference" if estimates is not None else "rendered reference stems",
            "reference": sections, "predicted": predicted, "boundary_metrics": event_metrics(expected_boundaries, actual_boundaries, 1),
            "time_weighted_label_accuracy": correct / duration,
            "per_label": {label: {**values, "recall": values["correct_seconds"] / values["reference_seconds"]}
                          for label, values in per_label.items()}}


def main():
    parser = argparse.ArgumentParser(description="Reproducible CPU, memory and musical-quality checks using original MIDI fixtures")
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--soundfont", type=Path)
    parser.add_argument("--tasks", nargs="+", choices=("separation", "drums", "sections", "pitched"),
                        default=["separation", "drums", "sections", "pitched"])
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--run-case", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.run_case:
        separation_case(json.loads(args.run_case.read_text()), args.models)
        return
    if not args.output or args.output.exists() or not 12 <= args.duration <= 120 or not 1 <= args.repeats <= 5:
        parser.error("Choose a new output directory, 12-120 seconds and 1-5 repetitions")
    args.output.mkdir(parents=True, exist_ok=False)
    font = font_file(args, args.output)
    report = {"scope": "generated MIDI/SoundFont corpus only; not a general song-quality guarantee",
              "font_sha256": FONT_SHA256, "font_license": FONT_LICENSE, "python": sys.version.split()[0],
              "platform": platform.system(), "architecture": platform.machine(), "available_cpus": os.process_cpu_count()}
    if {"separation", "pitched"} & set(args.tasks):
        cases = [render_song(args.output / style, [{"start": 0, "end": args.duration, "label": "Chorus"}], style, font)
                 for style in ("clean", "metal")]
    if "separation" in args.tasks:
        report["separation"] = separation_benchmark(cases, args.output, args.models, args.repeats)
    if "pitched" in args.tasks:
        report["pitched"] = pitched_benchmark(cases, args.models)
    if "drums" in args.tasks:
        report["drums"] = drum_benchmark(args.output, font, args.models)
    if "sections" in args.tasks:
        report["sections"] = structure_benchmark(args.output, font, args.models)
    (args.output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
