import json
import logging
import math
import os
import sys
import tempfile
from pathlib import Path

import soundfile as sf

from .audio import run_command
from .models import ensure_model

logger = logging.getLogger(__name__)


def drum_notes(source, model_dir, report, cancelled):
    weights = ensure_model("drum-str", model_dir, lambda _, stage: report(82, stage), cancelled)
    duration = sf.info(source).duration
    with tempfile.TemporaryDirectory(prefix="track2stem-drums-") as directory:
        output = Path(directory) / "notes.json"
        frozen = getattr(sys, "frozen", False)
        command = ([sys.executable, "--drums-component"] if frozen
                   else [sys.executable, "-m", "drum_transcriber"])
        command.extend(["--input", str(source), "--weights", str(weights), "--output", str(output),
                        "--parent-pid", str(os.getpid())])

        def progress(line):
            prefix = "T2S_DRUM_PROGRESS "
            if not line.startswith(prefix):
                if line.strip():
                    logger.info("Drum component: %s", line)
                return
            try:
                value = json.loads(line[len(prefix):])
                completed, total = value["completed"], value["total"]
                if not isinstance(completed, int) or not isinstance(total, int) or not 0 < completed <= total <= 2000:
                    raise ValueError("Invalid drum progress counters")
            except (ValueError, KeyError, TypeError) as error:
                raise RuntimeError("The isolated drum component emitted invalid progress") from error
            report(82 + int(6 * completed / total), f"Recognizing 26 drum classes: window {completed}/{total}")

        report(82, "Recognizing the full drum kit with an isolated local CPU model")
        run_command(command, cancelled, timeout=max(600, duration * 8), on_output=progress,
                    cwd=None if frozen else Path(__file__).resolve().parents[1])
        try:
            if output.stat().st_size > 128 * 1024 * 1024:
                raise ValueError("Drum results exceed their size limit")
            result = json.loads(output.read_text(encoding="utf-8"))
            notes = result["notes"]
            if result.get("version") != 1 or not isinstance(notes, list) or len(notes) > 1_000_000:
                raise ValueError("Unsupported drum result contract")
            for note in notes:
                start, end = float(note["start"]), float(note["end"])
                if (not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end <= duration + .001
                        or not isinstance(note["pitch"], int) or not 35 <= note["pitch"] <= 81
                        or not isinstance(note["velocity"], int) or not 1 <= note["velocity"] <= 127):
                    raise ValueError("Invalid drum event")
            return notes
        except (OSError, ValueError, TypeError, KeyError) as error:
            logger.error("Invalid isolated drum result: %s", error)
            raise RuntimeError("The isolated drum component returned invalid events") from error
