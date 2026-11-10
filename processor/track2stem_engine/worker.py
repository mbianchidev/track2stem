import argparse
import contextlib
import datetime
import email.policy
import email.parser
import json
import logging
import mimetypes
import os
import re
import secrets
import shutil
import signal
import sys
import ssl
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import CONTRACT_VERSION
from .audio import CancelledError, ffmpeg, run_command
from .engine import Engine
from .settings import ALLOWED_EXTENSIONS, Settings, safe_join, validate_job_id
from .sources import canonical_youtube_url, download_youtube

logger = logging.getLogger(__name__)


class WorkerService:
    def __init__(self, root, model_dir, engine=None, ui_dir=None):
        self.root = Path(root).resolve()
        self.engine = engine or Engine(self.root / "outputs", model_dir)
        self.ui_dir = Path(ui_dir).resolve() if ui_dir else None
        self.token = secrets.token_urlsafe(32)
        self.jobs = {}
        self.progress = {}
        self.active = {}
        self.deleted = set()
        self.lock = threading.RLock()
        self.threads = []
        self.closed = threading.Event()
        self.server = None
        self.server_thread = None

    def start(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "Track2stem"
            sys_version = ""

            def log_message(self, format, *args):
                logger.debug(format, *args)

            def reply(self, status, value):
                data = json.dumps(value, allow_nan=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", "null")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(data)

            def route(self):
                origin = self.headers.get("Origin")
                expected = f"http://127.0.0.1:{service.server.server_port}"
                if origin not in (None, "null", expected):
                    raise PermissionError("This worker accepts only its local plugin UI")
                parts = [unquote(part) for part in urlsplit(self.path).path.split("/") if part]
                if not parts or not secrets.compare_digest(parts[0], service.token):
                    raise PermissionError("Invalid local worker capability")
                return parts[1:]

            def dispatch(self, method):
                try:
                    parts = self.route()
                    if parts and parts[0] == "ui" and method in {"GET", "HEAD"} and service.ui_dir:
                        asset = "/".join(parts[1:]) or "index.html"
                        return self.file(Path(safe_join(service.ui_dir, asset)), attachment=False)
                    if not parts or parts[0] != "api":
                        return self.reply(404, {"error": "Endpoint not found"})
                    parts = parts[1:]
                    if method == "OPTIONS":
                        self.send_response(204)
                        self.send_header("Access-Control-Allow-Origin", "null")
                        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
                        self.send_header("Access-Control-Allow-Headers", "Content-Type")
                        self.end_headers()
                        return
                    if method in {"GET", "HEAD"}:
                        return self.get(parts)
                    if method == "DELETE" and len(parts) == 2 and parts[0] == "jobs":
                        service.cancel(parts[1])
                        return self.reply(200, {"status": "deleted"})
                    if method != "POST":
                        return self.reply(405, {"error": "Method not allowed"})
                    length = int(self.headers.get("Content-Length", "0"))
                    limit = 101 << 20 if parts == ["upload"] else 1 << 20
                    if length <= 0 or length > limit:
                        return self.reply(413, {"error": "Request is empty or exceeds the size limit"})
                    body = self.rfile.read(length)
                    if len(body) != length:
                        raise ValueError("Incomplete request body")
                    if parts == ["upload"]:
                        content_type = self.headers.get("Content-Type", "")
                        if "\r" in content_type or "\n" in content_type:
                            raise ValueError("Invalid multipart content type")
                        message = email.parser.BytesParser(policy=email.policy.default).parsebytes(
                            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body)
                        if not message.is_multipart():
                            raise ValueError("Expected multipart audio")
                        options, filename, data = {}, None, None
                        for item in message.iter_parts():
                            name = item.get_param("name", header="content-disposition")
                            if name == "file":
                                filename, data = item.get_filename(), item.get_payload(decode=True)
                            elif name:
                                options[name] = item.get_payload(decode=True).decode("utf-8")
                        return self.reply(200, service.submit(filename, data, options))
                    values = json.loads(body)
                    if not isinstance(values, dict):
                        raise ValueError("Expected a JSON object")
                    if parts == ["import"]:
                        url = canonical_youtube_url(values.get("url"))
                        return self.reply(200, service.submit(None, None, values.get("settings", {}), url=url))
                    if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "mix":
                        job = service.get_job(parts[1])
                        if job["status"] != "completed":
                            return self.reply(409, {"error": "Job is not completed"})
                        result = service.engine.remix(parts[1], values.get("gains"))
                        return self.reply(200, service.complete(parts[1], result))
                    return self.reply(404, {"error": "Endpoint not found"})
                except PermissionError as error:
                    self.reply(403, {"error": str(error)})
                except (ValueError, UnicodeError) as error:
                    self.reply(400, {"error": str(error)})
                except FileNotFoundError as error:
                    self.reply(404, {"error": f"{error}. Import the source again if processed files are missing."})
                except (OSError, RuntimeError, TimeoutError) as error:
                    logger.exception("Local worker request failed")
                    if not isinstance(error, (BrokenPipeError, ConnectionResetError)):
                        self.reply(500, {"error": str(error)})

            def get(self, parts):
                if parts == ["health"]:
                    return self.reply(200, {"status": "ok", "version": CONTRACT_VERSION})
                if parts == ["jobs"]:
                    with service.lock:
                        return self.reply(200, list(service.jobs.values()))
                if len(parts) == 2 and parts[0] == "jobs":
                    return self.reply(200, service.get_job(parts[1]))
                if len(parts) == 2 and parts[0] == "processing-status":
                    service.get_job(parts[1])
                    with service.lock:
                        return self.reply(200, service.progress.get(parts[1], {"status": "unknown", "progress": 0}))
                if len(parts) == 3 and parts[0] in {"download", "stems", "artifacts"}:
                    job = service.get_job(parts[1])
                    if job["status"] != "completed":
                        return self.reply(409, {"error": "Job is not completed"})
                    field = {"download": "output_files", "stems": "stem_files", "artifacts": "artifacts"}[parts[0]]
                    path = job.get(field, {}).get(parts[2])
                    if path is None:
                        raise FileNotFoundError("Asset not found")
                    return self.file(Path(safe_join(service.engine.output_dir / parts[1], path)))
                self.reply(404, {"error": "Endpoint not found"})

            def file(self, path, attachment=True):
                with path.open("rb") as source:
                    size = os.fstat(source.fileno()).st_size
                    first, last = 0, size - 1
                    status = 200
                    range_header = self.headers.get("Range")
                    if range_header:
                        match = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header)
                        if not match:
                            return self.reply(416, {"error": "Unsupported byte range"})
                        first = int(match[1])
                        last = min(size - 1, int(match[2]) if match[2] else size - 1)
                        if first > last:
                            return self.reply(416, {"error": "Byte range is outside the file"})
                        status = 206
                    self.send_response(status)
                    self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                    self.send_header("Content-Length", str(max(0, last - first + 1)))
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Access-Control-Allow-Origin", "null")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    if attachment:
                        self.send_header("Content-Disposition", f'attachment; filename="{path.name.replace(chr(34), "_")}"')
                    if status == 206:
                        self.send_header("Content-Range", f"bytes {first}-{last}/{size}")
                    self.end_headers()
                    if self.command == "HEAD":
                        return
                    source.seek(first)
                    remaining = last - first + 1
                    while remaining > 0:
                        chunk = source.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)

            def do_GET(self):
                self.dispatch("GET")

            def do_HEAD(self):
                self.dispatch("HEAD")

            def do_POST(self):
                self.dispatch("POST")

            def do_DELETE(self):
                self.dispatch("DELETE")

            def do_OPTIONS(self):
                self.dispatch("OPTIONS")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="local-worker-http")
        self.server_thread.start()
        return f"http://127.0.0.1:{self.server.server_port}/{self.token}/api"

    def submit(self, filename, data, options, url=None):
        if self.closed.is_set():
            raise RuntimeError("The local worker is shutting down")
        if not isinstance(options, dict):
            raise ValueError("Settings must be an object")
        settings = Settings.from_mapping(options)
        if not url:
            if not isinstance(filename, str) or not isinstance(data, bytes):
                raise ValueError("Select an audio file")
            filename = re.sub(r"[^a-zA-Z0-9._-]", "_", Path(filename).name)[:160]
            if Path(filename).suffix.lower().lstrip(".") not in ALLOWED_EXTENSIONS or len(data) > 100 << 20:
                raise ValueError("Select a supported audio file up to 100 MiB")
        job_id = str(uuid.uuid4())
        cancelled = threading.Event()
        job = {"id": job_id, "status": "pending", "filename": filename or "YouTube audio",
               "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               **settings.to_dict()}
        directory = Path(safe_join(self.root / "uploads", job_id))
        directory.mkdir(parents=True, exist_ok=False)
        source = directory / filename if filename else None
        try:
            if source:
                source.write_bytes(data)
        except OSError:
            shutil.rmtree(directory)
            raise
        with self.lock:
            self.jobs[job_id] = job
            self.active[job_id] = cancelled

        def report(progress, stage):
            with self.lock:
                self.progress[job_id] = {"status": "processing", "progress": progress, "stage": stage}

        def process():
            try:
                with self.lock:
                    job["status"] = "processing"
                report(1, "Importing audio locally")
                actual_source = download_youtube(url, directory, cancelled) if url else source
                with contextlib.redirect_stdout(sys.stderr):
                    result = self.engine.run(actual_source, job_id, settings, report, cancelled)
                self.complete(job_id, result)
            except (OSError, RuntimeError, ValueError, TimeoutError, ImportError) as error:
                if isinstance(error, CancelledError):
                    logger.info("Local job %s cancelled", job_id)
                else:
                    logger.exception("Local job %s failed", job_id)
                with self.lock:
                    job.update(status="failed", error=str(error))
                    self.progress[job_id] = {"status": "failed", "progress": 0, "stage": str(error)}
            finally:
                with self.lock:
                    self.active.pop(job_id, None)
                shutil.rmtree(directory)

        thread = threading.Thread(target=process, daemon=True, name=f"local-job-{job_id}")
        self.threads.append(thread)
        snapshot = dict(job)
        thread.start()
        return snapshot

    def complete(self, job_id, result):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            job.update({key: value for key, value in result.items() if key not in {"outputs", "settings"}})
            job["output_files"] = result["outputs"]
            job["status"] = "completed"
            job["completed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self.progress[job_id] = {"status": "completed", "progress": 100, "stage": "Complete"}
            return dict(job)

    def get_job(self, job_id):
        if not validate_job_id(job_id):
            raise ValueError("Invalid job ID")
        with self.lock:
            if job_id in self.deleted:
                raise FileNotFoundError("Job was removed from this worker")
            if job_id in self.jobs:
                return dict(self.jobs[job_id])
        manifest = self.engine.load(job_id)
        with self.lock:
            self.jobs[job_id] = {"id": job_id, "created_at": manifest.get("created_at", ""), "filename": manifest["filename"], **manifest["settings"]}
        return self.complete(job_id, manifest)

    def cancel(self, job_id):
        if not validate_job_id(job_id):
            raise ValueError("Invalid job ID")
        with self.lock:
            if job_id not in self.jobs:
                raise FileNotFoundError("Job not found")
            if job_id in self.active:
                self.active[job_id].set()
            self.jobs.pop(job_id)
            self.deleted.add(job_id)

    def close(self):
        self.closed.set()
        with self.lock:
            for cancelled in self.active.values():
                cancelled.set()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server_thread.join(timeout=2)
        deadline = time.monotonic() + 3
        for thread in self.threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in self.threads):
            logger.warning("An in-flight model operation is still stopping; the native host enforces its teardown deadline")


def main():
    parser = argparse.ArgumentParser(description="Track2stem local native worker")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--models", type=Path)
    parser.add_argument("--ui", type=Path)
    parser.add_argument("--install", type=Path)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    parent = os.getppid()
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    if args.install:
        if sys.platform != "darwin":
            parser.error("The native installer supports macOS only")
        from .installation import install_package
        for target in install_package(args.install, Path.home()):
            print(f"Installed {target}")
        print("Open your DAW and scan for Track2stem. Audio and model caches were preserved.")
        return
    if args.root is None or args.models is None:
        parser.error("--root and --models are required for worker mode")
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    resources = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    for filename, variable in (("ffmpeg", "TRACK2STEM_FFMPEG"), ("node", "TRACK2STEM_NODE")):
        bundled = resources / filename
        if bundled.is_file():
            os.environ[variable] = str(bundled)
        elif getattr(sys, "frozen", False):
            raise RuntimeError(f"Bundled {filename} is missing; reinstall the Track2stem runtime")
    if args.self_test:
        import torch
        import torchaudio
        import torchcodec
        import onnxruntime
        import faster_whisper
        import yt_dlp
        import beat_this.inference
        import safetensors.torch
        import sklearn.decomposition
        import asteroid_filterbanks
        if torch.version.cuda is not None:
            raise RuntimeError("The native runtime must be CPU-only")
        run_command([ffmpeg(), "-version"], timeout=10)
        run_command([os.environ.get("TRACK2STEM_NODE", "node"), "--version"], timeout=10)
        print(json.dumps({"version": CONTRACT_VERSION, "status": "ok", "cpu_only": True,
                          "python_version": sys.version.split()[0], "torch": torch.__version__,
                          "openssl_version": ssl.OPENSSL_VERSION, "flask_loaded": "flask" in sys.modules}))
        return
    service = WorkerService(args.root, args.models, ui_dir=args.ui)
    api_base = service.start()
    output = sys.stdout
    output.write(json.dumps({"version": CONTRACT_VERSION, "type": "ready", "api_base": api_base,
                             "ui_url": api_base.removesuffix("/api") + "/ui/"}) + "\n")
    output.flush()
    stopping = threading.Event()
    for number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(number, lambda *_args: stopping.set())
    try:
        if args.serve:
            while not stopping.wait(timeout=1):
                if os.getppid() != parent:
                    logger.warning("The owning native host stopped; shutting down its worker")
                    break
        else:
            for line in sys.stdin:
                value = json.loads(line)
                if value.get("version") != CONTRACT_VERSION:
                    raise ValueError("Unsupported worker contract version")
                if value.get("command") == "shutdown":
                    break
    finally:
        service.close()


if __name__ == "__main__":
    main()
