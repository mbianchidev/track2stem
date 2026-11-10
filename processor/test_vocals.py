import threading

import numpy as np

from track2stem_engine.vocals import split_vocals


def test_inaudible_vocal_input_is_preserved_without_loading_a_model(monkeypatch, tmp_path):
    def unexpected(*_args):
        raise AssertionError("Inaudible audio does not need a model download")

    monkeypatch.setattr("track2stem_engine.vocals.get_vocal_separator", unexpected)
    original = np.full((4410, 2), 1e-7, dtype=np.float32)
    lead, backing = split_vocals(original, 44100, tmp_path, lambda *_: None,
                                threading.Event(), method="neural")
    np.testing.assert_array_equal(lead + backing, original)


def test_lead_and_backing_vocals_reconstruct_the_original_across_windows(monkeypatch, tmp_path):
    class Model:
        def __call__(self, audio):
            return np.stack((audio * .5, audio * .5))

    monkeypatch.setattr("track2stem_engine.vocals.get_vocal_separator", lambda *_args: Model())
    rate = 44100
    time = np.arange(rate * 8) / rate
    original = np.column_stack((.1 * np.sin(2 * np.pi * 440 * time),
                                .08 * np.sin(2 * np.pi * 660 * time))).astype(np.float32)
    lead, backing = split_vocals(original, rate, tmp_path, lambda *_args: None, threading.Event(), method="neural")
    np.testing.assert_allclose(lead + backing, original, atol=1e-7)
    assert lead.shape == backing.shape == original.shape
    assert np.mean(backing ** 2) > .0001
    assert np.mean(lead ** 2) > .0001


def test_vocal_stream_identity_survives_window_permutations(monkeypatch, tmp_path):
    class Model:
        def __init__(self):
            self.index = 0

        def __call__(self, audio):
            time = np.arange(len(audio)) / 24000
            sources = np.stack((.05 * np.sin(2 * np.pi * 440 * time), .04 * np.sin(2 * np.pi * 660 * time)))
            self.index += 1
            return sources if self.index % 2 else sources[::-1].copy()

    monkeypatch.setattr("track2stem_engine.vocals.get_vocal_separator", lambda *_args: Model())
    time = np.arange(44100 * 8) / 44100
    audio = np.column_stack((.1 * np.sin(2 * np.pi * 440 * time),
                             .08 * np.sin(2 * np.pi * 660 * time))).astype(np.float32)
    details = {}
    lead, backing = split_vocals(audio, 44100, tmp_path, lambda *_: None, threading.Event(), details=details, method="neural")
    np.testing.assert_allclose(lead + backing, audio, atol=1e-7)
    assert np.mean(lead[:, 0] ** 2) > 10 * np.mean(lead[:, 1] ** 2)
    assert np.mean(backing[:, 1] ** 2) > 10 * np.mean(backing[:, 0] ** 2)
    assert details["weight_license"] == "CC-BY-4.0"
    assert details["stream_realignments"] > 0


def test_audible_input_does_not_turn_failed_vocal_predictions_into_two_fake_stems(monkeypatch, tmp_path):
    import pytest

    monkeypatch.setattr("track2stem_engine.vocals.get_vocal_separator",
                        lambda *_: lambda audio: np.zeros((2, len(audio)), dtype=np.float32))
    with pytest.raises(RuntimeError, match="audible"):
        split_vocals(np.full((44100, 2), .02, dtype=np.float32), 44100,
                     tmp_path, lambda *_: None, threading.Event(), method="neural")


def test_identifiable_stereo_vocals_use_spatial_evidence_without_model_download(monkeypatch, tmp_path):
    def unexpected(*_args):
        raise AssertionError("Identifiable spatial sources do not need a neural download")

    monkeypatch.setattr("track2stem_engine.vocals.get_vocal_separator", unexpected)
    rng = np.random.default_rng(2026)
    first = rng.laplace(size=44100 * 4).astype(np.float32) * .035
    second = rng.uniform(-.04, .04, size=len(first)).astype(np.float32)
    reference = np.column_stack((first, first))
    background = np.column_stack((second, second * .35))
    mixture = reference + background
    details = {}
    lead, backing = split_vocals(mixture, 44100, tmp_path, lambda *_: None, threading.Event(),
                                details=details, method="auto")
    np.testing.assert_allclose(lead + backing, mixture, atol=1e-7)
    assert np.mean((lead - reference) ** 2) < np.mean(background ** 2) / 100
    assert details["method"] == "stereo independent components"
    assert details["models_downloaded"] is False


def test_spatial_mode_does_not_invent_independent_channels_for_mono_audio(tmp_path):
    import pytest

    audio = np.full((44100, 2), .02, dtype=np.float32)
    with pytest.raises(ValueError, match="independent stereo"):
        split_vocals(audio, 44100, tmp_path, lambda *_: None, threading.Event(), method="spatial")
