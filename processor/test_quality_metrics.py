import importlib.util
from pathlib import Path

import numpy as np
import pytest

specification = importlib.util.spec_from_file_location(
    "benchmark_audio", Path(__file__).resolve().parents[1] / "scripts/benchmark-audio.py")
benchmark = importlib.util.module_from_spec(specification)
specification.loader.exec_module(benchmark)


def test_reference_quality_is_scale_invariant_and_measures_known_added_noise():
    rng = np.random.default_rng(2026)
    reference = rng.normal(size=100000)
    assert benchmark.si_sdr(reference, reference * 3)["si_sdr_db"] > 150
    noise = rng.normal(size=len(reference)) * .1
    assert benchmark.si_sdr(reference, reference + noise)["si_sdr_db"] == pytest.approx(20, abs=.15)
    assert benchmark.si_sdr(np.zeros(100), np.ones(100))["si_sdr_db"] is None
    with pytest.raises(ValueError):
        benchmark.si_sdr([1, np.nan], [1, 2])


def test_event_matching_does_not_lose_valid_fast_hits_to_a_greedy_assignment():
    reference = [{"start": .03, "pitch": 38}, {"start": .07, "pitch": 38}]
    predicted = [{"start": 0, "pitch": 38}, {"start": .04, "pitch": 38}]
    result = benchmark.event_metrics(reference, predicted, tolerance=.04)
    assert result["f1"] == 1
    assert result["per_class"]["38"]["true"] == 2
    extra = benchmark.event_metrics(reference, predicted + [{"start": .1, "pitch": 51}], tolerance=.04)
    assert extra["precision"] == pytest.approx(2 / 3)
    assert extra["recall"] == 1
