import pytest
import numpy as np
import soundfile as sf
import threading
import io
import app as web

from track2stem_engine.engine import Engine
from track2stem_engine.settings import Settings


def test_settings_preserve_defaults_and_reject_incompatible_transcription():
    settings = Settings.from_mapping({})
    assert settings.model == "htdemucs_6s"
    assert settings.stems == ("vocals", "drums", "bass", "guitar", "piano", "other")
    assert settings.shifts == 0
    with pytest.raises(ValueError, match="Guitar transcription requires"):
        Settings.from_mapping({"model": "htdemucs", "guitar_tabs": "true"})


def test_headless_engine_rejects_unvalidated_settings_before_creating_output(tmp_path):
    source = tmp_path / "synthetic.wav"
    sf.write(source, np.full((4410, 2), .01), 44100)
    engine = Engine(tmp_path / "outputs", tmp_path / "models",
                    separator=lambda *_args: ({stem: np.full((4410, 2), .01) for stem in Settings().stems}, 44100))
    with pytest.raises(ValueError, match="Invalid model"):
        engine.run(source, "synthetic-invalid", Settings(model="unknown"))
    assert not (tmp_path / "outputs" / "synthetic-invalid").exists()


def test_isolated_backing_can_remix_each_original_instrument(tmp_path):
    source = tmp_path / "synthetic.wav"
    sf.write(source, np.zeros((4410, 2)), 44100)

    def separate(path, settings, report, cancelled):
        return {stem: np.full((4410, 2), .02 * (index + 1), dtype=np.float32)
                for index, stem in enumerate(settings.stems)}, 44100

    engine = Engine(tmp_path / "outputs", tmp_path / "models", separator=separate)
    result = engine.run(source, "synthetic-job", Settings(
        output_format="wav", stem_mode="isolate", isolate_stem="drums",
    ), cancelled=threading.Event())
    assert set(result["outputs"]) == {"drums", "backing"}
    assert set(result["mix_stems"]) == set(Settings().stems)
    remixed = engine.remix("synthetic-job", {"vocals": 0, "bass": 2})
    backing, rate = sf.read(remixed["outputs"]["backing"])
    assert rate == 44100
    assert np.mean(backing) == pytest.approx(.02 * (3 * 2 + 4 + 5 + 6), abs=1 / 32768)
    drums, _ = sf.read(remixed["outputs"]["drums"])
    assert np.mean(drums) == pytest.approx(.04, abs=1 / 32768)
    assert source.exists(), "The engine must never delete a caller-owned source"


def test_web_adapter_uses_headless_engine(tmp_path, monkeypatch):
    seen = []

    def separate(path, settings, report, cancelled):
        seen.append(settings)
        return {stem: np.full((4410, 2), .02, dtype=np.float32) for stem in settings.stems}, 44100

    engine = Engine(tmp_path / "outputs", tmp_path / "models", separator=separate)
    monkeypatch.setattr(web, "get_engine", lambda: engine, raising=False)
    with web.app.test_client() as client:
        response = client.post("/process", data={
            "job_id": "synthetic-web", "output_format": "flac",
            "file": (io.BytesIO(b"synthetic fixture"), "synthetic.wav"),
        })
    assert response.status_code == 200
    result = response.get_json()
    assert result["version"] == 1
    assert len(result["outputs"]) == 6
    assert seen[0].output_format == "flac"
