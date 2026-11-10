import threading

import numpy as np

from track2stem_engine.vocals import split_vocals


def test_lead_and_backing_vocals_reconstruct_the_original_across_windows(monkeypatch, tmp_path):
    class Model:
        def run(self, _names, inputs):
            return [inputs["input"] * .5]

    monkeypatch.setattr("track2stem_engine.vocals.get_session", lambda *_args: Model())
    rate = 44100
    time = np.arange(rate * 8) / rate
    original = np.column_stack((.1 * np.sin(2 * np.pi * 440 * time),
                                .08 * np.sin(2 * np.pi * 660 * time))).astype(np.float32)
    lead, backing = split_vocals(original, rate, tmp_path, lambda *_args: None, threading.Event())
    np.testing.assert_allclose(lead + backing, original, atol=1e-7)
    assert lead.shape == backing.shape == original.shape
    assert np.mean(backing ** 2) > .0001
    assert np.mean(lead ** 2) > .0001
