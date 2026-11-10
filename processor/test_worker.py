import io
import json
import time
import urllib.request
import urllib.error
import threading
import subprocess
import sys
import os
import signal
import http.client

import numpy as np
import pytest
import soundfile as sf

from track2stem_engine.engine import Engine
from track2stem_engine.settings import Settings
from track2stem_engine.worker import WorkerService
from track2stem_engine.audio import check_cancelled


def test_native_worker_imports_and_serves_audio_without_flask(tmp_path):
    audio = np.full((4410, 2), .02, dtype=np.float32)
    engine = Engine(tmp_path / "outputs", tmp_path / "models",
                    separator=lambda *_args: ({stem: audio for stem in Settings().stems}, 44100))
    service = WorkerService(tmp_path, tmp_path / "models", engine=engine)
    base = service.start()
    try:
        fixture = io.BytesIO()
        sf.write(fixture, audio, 44100, format="WAV")
        boundary = "synthetic-worker-boundary"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"output_format\"\r\n\r\nwav\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"synthetic.wav\"\r\n"
                "Content-Type: audio/wav\r\n\r\n").encode() + fixture.getvalue() + f"\r\n--{boundary}--\r\n".encode()
        request = urllib.request.Request(base + "/upload", data=body,
                                         headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(request) as response:
            job = json.load(response)
        deadline = time.monotonic() + 5
        while job["status"] in {"pending", "processing"} and time.monotonic() < deadline:
            with urllib.request.urlopen(base + "/jobs/" + job["id"]) as response:
                job = json.load(response)
            time.sleep(.01)
        assert job["status"] == "completed", job.get("error")
        assert len(job["output_files"]) == 6
        request = urllib.request.Request(base + f"/download/{job['id']}/vocals", headers={"Range": "bytes=0-3"})
        with urllib.request.urlopen(request) as response:
            assert response.status == 206
            assert response.read() == b"RIFF"
        request = urllib.request.Request(base + f"/download/{job['id']}/vocals", method="HEAD")
        with urllib.request.urlopen(request) as response:
            assert response.status == 200 and response.read() == b""
            assert int(response.headers["Content-Length"]) > 44
        with pytest.raises(urllib.error.HTTPError) as failure:
            urllib.request.urlopen(base.replace(service.token, "wrong-token") + "/jobs")
        assert failure.value.code == 403
    finally:
        service.close()
    assert not service.server_thread.is_alive()


def test_native_worker_teardown_cancels_owned_processing(tmp_path):
    entered = threading.Event()

    def separate(_source, _settings, _report, cancelled):
        entered.set()
        cancelled.wait(5)
        check_cancelled(cancelled)
        raise RuntimeError("The test should cancel before this point")

    engine = Engine(tmp_path / "outputs", tmp_path / "models", separator=separate)
    service = WorkerService(tmp_path, tmp_path / "models", engine=engine)
    service.start()
    job = service.submit("synthetic.wav", b"synthetic fixture", {})
    assert entered.wait(2)
    started = time.monotonic()
    service.close()
    assert time.monotonic() - started < 3
    assert all(not thread.is_alive() for thread in service.threads)
    assert not (tmp_path / "outputs" / job["id"]).exists()


def test_native_worker_stops_when_its_owning_host_exits(tmp_path):
    script = """
import json,subprocess,sys
worker=subprocess.Popen([sys.executable,'-m','track2stem_engine.worker',
    '--root',sys.argv[1],'--models',sys.argv[2],'--serve'],
    stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,start_new_session=True)
print(json.dumps({'ready':json.loads(worker.stdout.readline()),'pid':worker.pid}),flush=True)
"""
    result = json.loads(subprocess.check_output(
        [sys.executable, "-c", script, str(tmp_path / "data"), str(tmp_path / "models")],
        text=True, timeout=15))
    ready = result["ready"]
    deadline = time.monotonic() + 6
    stopped = False
    try:
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(ready["api_base"] + "/health", timeout=.2).close()
            except urllib.error.URLError:
                stopped = True
                break
            except (ConnectionResetError, http.client.RemoteDisconnected):
                pass
            time.sleep(.1)
    finally:
        if not stopped:
            try:
                os.killpg(result["pid"], signal.SIGTERM)
            except ProcessLookupError:
                pass
    assert stopped, "An orphaned native worker must not keep serving after its host exits"
