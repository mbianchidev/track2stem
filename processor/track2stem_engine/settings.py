import json
import math
import os
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path

JOB_ID_PATTERN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9\-]{0,254}")
ALLOWED_MODELS = frozenset({
    "htdemucs", "htdemucs_ft", "htdemucs_6s", "hdemucs_mmi",
    "mdx", "mdx_extra", "mdx_q", "mdx_extra_q",
})
SIX_STEM_MODELS = frozenset({"htdemucs_6s"})
SIX_STEMS = ("vocals", "drums", "bass", "guitar", "piano", "other")
FOUR_STEMS = ("vocals", "drums", "bass", "other")
ALLOWED_STEMS = frozenset(SIX_STEMS)
ALLOWED_OUTPUT_FORMATS = frozenset({"mp3", "wav", "flac"})
ALLOWED_STEM_MODES = frozenset({"all", "isolate"})
ALLOWED_CLIP_MODES = frozenset({"rescale", "clamp"})
ALLOWED_SHIFTS = frozenset(range(11))
ALLOWED_SEGMENTS = frozenset({None, 5, 7, 8, 10, 15, 20, 25, 30, 40, 60})
ALLOWED_OVERLAPS = frozenset({None, .1, .15, .2, .25, .3, .35, .4, .5})
ALLOWED_EXTENSIONS = frozenset({"mp3", "wav", "flac", "ogg", "m4a", "aac"})
FEATURES = ("analysis", "click_track", "lyrics", "guitar_tabs", "bass_tabs", "drum_tabs", "split_vocals")


def validate_job_id(value):
    return isinstance(value, str) and JOB_ID_PATTERN.fullmatch(value) is not None


def safe_join(base_dir, *parts):
    base = Path(base_dir).resolve()
    result = base.joinpath(*parts).resolve()
    if not result.is_relative_to(base):
        raise ValueError(f"Path traversal detected: {result} escapes {base}")
    return str(result)


def parse_flag(value):
    if value in (True, "true", "1", 1):
        return True
    if value in (False, "false", "0", 0, None, ""):
        return False
    raise ValueError("Feature flags must be true or false")


@dataclass(frozen=True)
class Settings:
    model: str = "htdemucs_6s"
    output_format: str = "mp3"
    stem_mode: str = "all"
    isolate_stem: str = "vocals"
    shifts: int = 0
    segment: int | None = None
    overlap: float | None = .25
    clip_mode: str = "rescale"
    workers: int = 1
    analysis: bool = False
    click_track: bool = False
    lyrics: bool = False
    guitar_tabs: bool = False
    bass_tabs: bool = False
    drum_tabs: bool = False
    split_vocals: bool = False

    @property
    def stems(self):
        return SIX_STEMS if self.model in SIX_STEM_MODELS else FOUR_STEMS

    @property
    def mix_stems(self):
        if self.split_vocals:
            return ("lead_vocals", "backing_vocals", *self.stems[1:])
        return self.stems

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_mapping(cls, values):
        options = {}
        for field in fields(cls):
            name = field.name
            value = values.get(name, field.default)
            if name in FEATURES:
                options[name] = parse_flag(value)
            elif name in {"shifts", "segment", "workers", "overlap"}:
                try:
                    options[name] = (None if name in {"segment", "overlap"} and value in ("", None)
                                     else float(value) if name == "overlap" else int(value))
                except (TypeError, ValueError, OverflowError) as error:
                    raise ValueError(f"Invalid {name} value") from error
                if isinstance(value, bool) or (
                    isinstance(value, float) and name != "overlap" and value != options[name]
                ):
                    raise ValueError(f"Invalid {name} value")
            elif isinstance(value, str):
                options[name] = value.lower()
            else:
                raise ValueError(f"Invalid {name} value")
        settings = cls(**options)
        checks = (
            (settings.model in ALLOWED_MODELS, "Invalid model"),
            (settings.output_format in ALLOWED_OUTPUT_FORMATS, "Invalid output format"),
            (settings.stem_mode in ALLOWED_STEM_MODES, "Invalid stem mode"),
            (settings.isolate_stem in ALLOWED_STEMS, "Invalid isolate stem"),
            (settings.isolate_stem in settings.stems, "Incompatible isolate_stem for selected model"),
            (settings.clip_mode in ALLOWED_CLIP_MODES, "Invalid clip mode"),
            (settings.shifts in ALLOWED_SHIFTS, "Invalid shifts value"),
            (settings.segment in ALLOWED_SEGMENTS, "Invalid segment value"),
            (settings.overlap in ALLOWED_OVERLAPS, "Invalid overlap value"),
            (1 <= settings.workers <= min(4, os.process_cpu_count() or 1), "Invalid workers value"),
            (not settings.guitar_tabs or "guitar" in settings.stems,
             "Guitar transcription requires the six-stem model"),
        )
        for valid, message in checks:
            if not valid:
                raise ValueError(message)
        return settings


def validate_gains(values, stems):
    if isinstance(values, str):
        try:
            values = json.loads(values)
        except json.JSONDecodeError as error:
            raise ValueError("Gains must be a JSON object") from error
    if not isinstance(values, dict) or set(values) - set(stems):
        raise ValueError("Gains must name only this job's instruments")
    result = dict.fromkeys(stems, 1.0)
    for stem, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Invalid gain for {stem}")
        if not math.isfinite(value) or not 0 <= value <= 4:
            raise ValueError(f"Gain for {stem} must be between 0 and 4 (0-400%)")
        result[stem] = float(value)
    return result
