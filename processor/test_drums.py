import json
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from drum_transcriber.events import allowed_tokens, attack_envelope, decode_tokens
from track2stem_engine.audio import run_command
from track2stem_engine.drums import drum_notes


@pytest.mark.parametrize("frequencies", [(95, 150, 170, 240), (140, 210, 225, 330)])
def test_tom_registers_use_the_recordings_pitches_not_a_fixed_soundfont(frequencies):
    from drum_transcriber import events

    rate = 24000
    time = np.arange(round(rate * .15)) / rate
    measured = [events.tom_frequency(
        (np.sin(2 * np.pi * frequency * time) + .2 * np.sin(2 * np.pi * frequency * 1.6 * time))
        * np.exp(-15 * time), rate,
    ) for frequency in frequencies]
    assert measured == pytest.approx(frequencies, rel=.05)
    notes = [{"start": index * .5, "end": index * .5 + .1, "pitch": 41 if index < 3 else 50,
              "velocity": 100} for index in range(4)]
    refined, details = events.refine_tom_registers(notes, measured)
    assert [entry["pitch"] for entry in refined] == [41, 47, 47, 50]
    assert [entry["start"] for entry in refined] == [entry["start"] for entry in notes]
    assert details["changed"] == 2
    assert events.refine_tom_registers(notes, [100, 100.2, 180, 180.5])[0] == notes


def test_acoustic_onsets_retain_quiet_attacks_but_not_unsupported_release_hits():
    from drum_transcriber import events

    time = np.arange(24000) / 24000
    audio = .2 * np.sin(2 * np.pi * 140 * time) * np.exp(-6 * time)
    audio[12000:12240] += .005
    attacks = attack_envelope(audio)
    assert events.supported_onset(.53, attacks, .0005) == pytest.approx(.5, abs=.011)
    assert events.supported_onset(.85, attacks, .0005) is None


def test_tom_calibration_does_not_collapse_simultaneous_distinct_hits():
    from drum_transcriber import events

    notes = [{"start": index, "end": index + .1, "pitch": pitch, "velocity": 100}
             for index, pitch in enumerate((41, 47, 47, 50))]
    notes.extend([{"start": 4., "end": 4.1, "pitch": pitch, "velocity": 90} for pitch in (41, 50)])
    refined, _ = events.refine_tom_registers(notes, [90, 140, 155, 230, 150, 150])
    assert [entry["pitch"] for entry in refined[-2:]] == [41, 50]


def test_full_kit_tokens_map_to_actual_general_midi_classes():
    tokens = [2]
    classes = [36, 38, 42, 44, 41, 45, 47, 46, 48]
    for index, instrument in enumerate(classes):
        tokens.extend((4 + index * 25, 300 + instrument, 500))
    tokens.append(3)
    notes = decode_tokens(tokens)
    assert [note["pitch"] for note in notes] == [36, 38, 42, 46, 41, 47, 50, 49, 51]
    assert [note["start"] for note in notes] == [index * .25 for index in range(len(classes))]
    assert all(note["velocity"] == 100 for note in notes)


@pytest.mark.parametrize("tokens", [
    [2, 4, 399, 500, 3],
    [2, 4, 336, 300, 3],
    [2, 4, 336, 3],
    [2, 4, 336, 500],
])
def test_invalid_or_unfinished_drum_predictions_fail_explicitly(tokens):
    with pytest.raises(ValueError):
        decode_tokens(tokens)


def test_decoder_grammar_prevents_the_observed_repeated_same_time_same_hit_loop():
    prefix = [2, 24, 354, 500, 224, 353, 500, 224]
    allowed = allowed_tokens(prefix)
    assert 353 not in allowed
    assert 347 in allowed
    after_event = allowed_tokens(prefix[:-1])
    assert 3 in after_event
    assert all(value == 3 or 224 <= value <= 259 for value in after_event)
    assert allowed_tokens([2, 0]) == [3]
    with pytest.raises(ValueError):
        decode_tokens([2, 224, 353, 500, 224, 353, 500, 3])
    assert decode_tokens([2, 4, 342, 400, 3]) == [], "MIDI velocity zero must not be invented as an audible hit"


def test_release_only_audio_does_not_create_new_attack_windows():
    time = np.arange(24000) / 24000
    release = np.sin(2 * np.pi * 100 * time) * np.exp(-5 * time)
    assert attack_envelope(release).max() < 1e-4
    struck = release.copy()
    struck[12000:12240] += .5
    assert attack_envelope(struck).max() > .1

def test_component_boundary_validates_events_and_reports_real_progress(tmp_path, monkeypatch):
    source = tmp_path / "synthetic.wav"
    sf.write(source, np.zeros((8000, 2), dtype=np.float32), 8000)
    monkeypatch.setattr("track2stem_engine.drums.ensure_model", lambda *_args: tmp_path / "weights.safetensors")
    expected = [{"start": .25, "end": .35, "pitch": 46, "velocity": 100}]
    progress = []

    def execute(command, cancelled, **options):
        assert command[0] == sys.executable
        assert command[1:3] == ["-m", "drum_transcriber"]
        options["on_output"]('T2S_DRUM_PROGRESS {"completed":1,"total":1}')
        output = Path(command[command.index("--output") + 1])
        output.write_text(json.dumps({"version": 1, "notes": expected}))
        return ""

    monkeypatch.setattr("track2stem_engine.drums.run_command", execute)
    assert drum_notes(source, tmp_path, lambda *entry: progress.append(entry), threading.Event()) == expected
    assert any("1/1" in stage for _, stage in progress)


def test_owned_command_progress_is_streamed_without_losing_output():
    lines = []
    details = run_command([sys.executable, "-c", "print('first',flush=True);print('second',flush=True)"],
                          on_output=lines.append)
    assert lines == ["first", "second"]
    assert "first" in details and "second" in details


def test_orphan_component_refuses_to_start_before_importing_model_code(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "drum_transcriber", "--input", str(tmp_path / "missing.wav"),
         "--weights", str(tmp_path / "missing.safetensors"), "--output", str(tmp_path / "notes.json"),
         "--parent-pid", "1"],
        cwd=Path(__file__).parent, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0
    assert "owning process" in result.stderr.lower()
    assert not (tmp_path / "notes.json").exists()
