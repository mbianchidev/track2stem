import hashlib
import io
import threading
import urllib.error

import pytest

from track2stem_engine import models

WEIGHTS = b"synthetic weights"


@pytest.fixture
def spec(monkeypatch):
    specification = models.ModelSpec(
        "https://primary.invalid/model.bin", hashlib.sha256(WEIGHTS).hexdigest(), "model.bin",
        mirrors=("https://mirror.invalid/model.bin",),
    )
    monkeypatch.setitem(models.MODELS, "synthetic", specification)
    return specification


def serve(monkeypatch, responses):
    def urlopen(url, timeout):
        response = responses[url]
        if isinstance(response, Exception):
            raise response
        return io.BytesIO(response)
    monkeypatch.setattr(models.urllib.request, "urlopen", urlopen)


@pytest.mark.parametrize("primary", [urllib.error.HTTPError("u", 500, "down", {}, None), b"<html>unavailable</html>"])
def test_verified_mirror_replaces_unavailable_or_wrong_primary(tmp_path, monkeypatch, spec, primary):
    serve(monkeypatch, {spec.url: primary, spec.mirrors[0]: WEIGHTS})

    path = models.ensure_model("synthetic", tmp_path, lambda *_: None, threading.Event())

    assert path.read_bytes() == WEIGHTS
    assert [item.name for item in tmp_path.iterdir()] == ["model.bin"]


def test_unreachable_sources_fail_without_partial_files(tmp_path, monkeypatch, spec):
    serve(monkeypatch, {url: urllib.error.URLError("offline") for url in (spec.url, *spec.mirrors)})

    with pytest.raises(RuntimeError, match="Could not download synthetic"):
        models.ensure_model("synthetic", tmp_path, lambda *_: None, threading.Event())
    assert list(tmp_path.iterdir()) == []
