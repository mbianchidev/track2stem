import json
import csv
import logging
import re
import shutil
import threading
import time
import uuid
import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

from . import CONTRACT_VERSION
from .audio import check_cancelled, read_audio, write_audio
from .settings import ALLOWED_EXTENSIONS, Settings, safe_join, validate_gains, validate_job_id

logger = logging.getLogger(__name__)


class Engine:
    def __init__(self, output_dir, model_dir, separator=None):
        self.output_dir = Path(output_dir).resolve()
        self.model_dir = Path(model_dir).resolve()
        self._separator = separator
        self._lock = threading.Lock()

    def _acquire(self, cancelled, report):
        report(2, "Waiting for the local processing engine")
        while not self._lock.acquire(timeout=.1):
            check_cancelled(cancelled)
        try:
            check_cancelled(cancelled)
        except BaseException:
            self._lock.release()
            raise

    def _job_dir(self, job_id):
        if not validate_job_id(job_id):
            raise ValueError("Invalid job ID")
        return Path(safe_join(self.output_dir, job_id))

    def run(self, source, job_id, settings, report=None, cancelled=None):
        settings = Settings.from_mapping(settings.to_dict())
        created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        source = Path(source).resolve()
        if not source.is_file() or source.suffix.lower().lstrip(".") not in ALLOWED_EXTENSIONS:
            raise ValueError("Select an existing, supported audio file")
        report = report or (lambda progress, stage: logger.info("%s: %s%% %s", job_id, progress, stage))
        cancelled = cancelled or threading.Event()
        job_dir = self._job_dir(job_id)
        self._acquire(cancelled, report)
        owned = False
        started = time.monotonic()
        try:
            job_dir.mkdir(parents=True, exist_ok=False)
            owned = True
            raw_dir = job_dir / ".stems"
            raw_dir.mkdir()
            if self._separator is None:
                from .separation import Separator
                self._separator = Separator(self.model_dir)
            stems, sample_rate = self._separator(source, settings, report, cancelled)
            if set(stems) != set(settings.stems):
                raise RuntimeError("Separation did not produce every requested instrument")
            if settings.split_vocals:
                from .vocals import split_vocals
                report(74, "Separating lead and backing vocals")
                lead, backing = split_vocals(stems["vocals"], sample_rate, self.model_dir, report, cancelled)
                stems["lead_vocals"] = lead
                stems["backing_vocals"] = backing
            for name, audio in stems.items():
                check_cancelled(cancelled)
                if audio.ndim != 2 or audio.shape[1] != 2 or not audio.size or not np.isfinite(audio).all():
                    raise RuntimeError(f"Separation returned invalid audio for {name}")
                sf.write(raw_dir / f"{name}.wav", audio, sample_rate, subtype="FLOAT")
            manifest = {
                "version": CONTRACT_VERSION, "job_id": job_id, "status": "completed",
                "created_at": created_at,
                "filename": source.name.removeprefix(f"{job_id}_"), "settings": settings.to_dict(),
                "mix_stems": list(settings.mix_stems), "gains": dict.fromkeys(settings.mix_stems, 1.0),
                "stem_files": {name: str(raw_dir / f"{name}.wav") for name in settings.mix_stems},
                "artifacts": {}, "analysis": None,
            }
            if settings.analysis or settings.click_track:
                from .analysis import analyze, make_click_track
                report(76, "Detecting tempo changes, key, tuning and song sections")
                original, rate = read_audio(source, cancelled)
                analysis = analyze(original, rate, stems, cancelled)
                manifest["analysis"] = analysis
                artifact_dir = job_dir / "artifacts"
                artifact_dir.mkdir(exist_ok=True)
                analysis_path = artifact_dir / "analysis.json"
                analysis_path.write_text(json.dumps(analysis, allow_nan=False), encoding="utf-8")
                manifest["artifacts"]["analysis"] = str(analysis_path)
                for name, keys, values in (
                    ("tempo", ("time", "bpm"), analysis["tempo_changes"]),
                    ("sections", ("start", "end", "label", "confidence"), analysis["sections"]),
                ):
                    path = artifact_dir / f"{name}.csv"
                    with path.open("w", newline="", encoding="utf-8") as target:
                        writer = csv.DictWriter(target, fieldnames=keys)
                        writer.writeheader()
                        writer.writerows(values)
                    manifest["artifacts"][name] = str(path)
                if settings.click_track:
                    path = artifact_dir / "click.wav"
                    write_audio(path, make_click_track(analysis["beats"], len(original), rate), rate,
                                cancelled=cancelled)
                    manifest["artifacts"]["click"] = str(path)
            if settings.lyrics:
                from .lyrics import generate_lyrics
                transcript, artifacts = generate_lyrics(
                    stems["vocals"], sample_rate, job_dir / "artifacts", self.model_dir, report, cancelled,
                )
                manifest["lyrics"] = transcript
                manifest["artifacts"].update(artifacts)
            if settings.guitar_tabs or settings.bass_tabs or settings.drum_tabs:
                from .transcription import drum_notes, pitched_notes, write_transcription
                for instrument, requested in (("guitar", settings.guitar_tabs), ("bass", settings.bass_tabs),
                                              ("drums", settings.drum_tabs)):
                    if not requested:
                        continue
                    report(82, f"Transcribing {instrument}")
                    notes = (drum_notes(stems[instrument], sample_rate, cancelled) if instrument == "drums"
                             else pitched_notes(stems[instrument], sample_rate, instrument,
                                                self.model_dir, report, cancelled))
                    artifacts = write_transcription(notes, instrument, job_dir / "artifacts",
                                                     (manifest["analysis"] or {}).get("tempo_changes"))
                    manifest["artifacts"].update(artifacts)
            report(90, "Exporting audio")
            manifest["outputs"] = self._render(job_dir, manifest, cancelled)
            elapsed = int(time.monotonic() - started)
            manifest["processing_time"] = f"{elapsed // 60}m {elapsed % 60}s" if elapsed >= 60 else f"{elapsed}s"
            self._save_manifest(job_dir, manifest)
            report(100, "Complete")
            return manifest
        except BaseException:
            if owned:
                shutil.rmtree(job_dir)
            raise
        finally:
            self._lock.release()

    def _render(self, job_dir, manifest, cancelled):
        settings = Settings.from_mapping(manifest["settings"])
        gains = validate_gains(manifest["gains"], manifest["mix_stems"])
        sources = {}
        sample_rate = None
        for stem in manifest["mix_stems"]:
            sources[stem], rate = sf.read(safe_join(job_dir / ".stems", f"{stem}.wav"), dtype="float32", always_2d=True)
            if sample_rate is not None and rate != sample_rate:
                raise RuntimeError("Stored stems have incompatible sample rates")
            sample_rate = rate
        if len({audio.shape for audio in sources.values()}) != 1:
            raise RuntimeError("Stored stems have incompatible lengths")
        if settings.stem_mode == "isolate":
            selected = ("lead_vocals", "backing_vocals") if settings.split_vocals and settings.isolate_stem == "vocals" else (settings.isolate_stem,)
            outputs = {stem: sources[stem] * gains[stem] for stem in selected}
            remainder = [sources[stem] * gains[stem] for stem in sources if stem not in selected]
            outputs["instrumental" if settings.isolate_stem == "vocals" else "backing"] = np.sum(remainder, axis=0)
        else:
            outputs = {stem: audio * gains[stem] for stem, audio in sources.items()}
        render_dir = job_dir / f"render-{uuid.uuid4()}"
        render_dir.mkdir()
        try:
            result = {}
            for stem, audio in outputs.items():
                check_cancelled(cancelled)
                prefix = re.sub(r"[^a-zA-Z0-9._-]", "_", Path(manifest["filename"]).stem)[:120]
                path = render_dir / f"{prefix}_t2s_{stem}.{settings.output_format}"
                write_audio(path, audio, sample_rate, settings.clip_mode, cancelled)
                result[stem] = str(path)
            return result
        except BaseException:
            shutil.rmtree(render_dir)
            raise

    @staticmethod
    def _save_manifest(job_dir, manifest):
        temporary = job_dir / ".job.tmp"
        temporary.write_text(json.dumps(manifest, allow_nan=False), encoding="utf-8")
        temporary.replace(job_dir / "job.json")

    def load(self, job_id):
        path = self._job_dir(job_id) / "job.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("version") != CONTRACT_VERSION:
            raise ValueError("This job uses an unsupported contract version")
        for path in (*manifest["outputs"].values(), *manifest["artifacts"].values()):
            resolved = Path(safe_join(self._job_dir(job_id), path))
            if not resolved.is_file():
                raise FileNotFoundError(f"Processed audio is missing: {resolved.name}. Import and separate it again.")
        return manifest

    def remix(self, job_id, gains, cancelled=None):
        cancelled = cancelled or threading.Event()
        self._acquire(cancelled, lambda *_: None)
        try:
            manifest = self.load(job_id)
            manifest["gains"] = validate_gains(gains, manifest["mix_stems"])
            job_dir = self._job_dir(job_id)
            manifest["outputs"] = self._render(job_dir, manifest, cancelled)
            self._save_manifest(job_dir, manifest)
            return manifest
        finally:
            self._lock.release()
