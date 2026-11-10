import logging
import os
import sys
import threading
import time
import shutil
from pathlib import Path

from flask import Flask, jsonify, request
from werkzeug.utils import secure_filename

from track2stem_engine.audio import CancelledError
from track2stem_engine.engine import Engine
from track2stem_engine.settings import (
    ALLOWED_CLIP_MODES, ALLOWED_EXTENSIONS, ALLOWED_MODELS, ALLOWED_OUTPUT_FORMATS,
    ALLOWED_OVERLAPS, ALLOWED_SEGMENTS, ALLOWED_SHIFTS, ALLOWED_STEMS,
    ALLOWED_STEM_MODES, SIX_STEM_MODELS, Settings, safe_join, validate_job_id,
)

DEMUCS_MODEL_ARG_MAP = {name: name for name in ALLOWED_MODELS}
ALLOWED_DEMUCS_MODELS = ALLOWED_MODELS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 101 * 1024 * 1024
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "/app/uploads")
OUTPUT_FOLDER = os.environ.get("OUTPUT_FOLDER", "/app/outputs")
MODEL_FOLDER = os.environ.get("MODEL_FOLDER", "/app/models")
processing_status = {}
active_jobs = {}
process_lock = threading.Lock()
_engine = None


def get_engine():
    global _engine
    with process_lock:
        if _engine is None:
            _engine = Engine(OUTPUT_FOLDER, MODEL_FOLDER)
        return _engine


def allowed_file(filename):
    return Path(filename).suffix.lower().lstrip(".") in ALLOWED_EXTENSIONS


def error_response(message, status):
    logger.warning("HTTP %s: %s", status, message)
    body = {"error": message}
    if message == "Invalid model":
        body["allowed_models"] = sorted(ALLOWED_DEMUCS_MODELS)
    return jsonify(body), status


@app.errorhandler(413)
def oversized_upload(_error):
    return error_response("File is too large. Maximum allowed size is 100 MiB.", 413)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/status/<job_id>")
def get_status(job_id):
    if not validate_job_id(job_id):
        return error_response("Invalid job ID", 400)
    with process_lock:
        return jsonify(processing_status.get(job_id, {"status": "unknown", "progress": 0}))


@app.route("/cancel/<job_id>", methods=["POST"])
def cancel_job(job_id):
    if not validate_job_id(job_id):
        return error_response("Invalid job ID", 400)
    with process_lock:
        cancelled = active_jobs.get(job_id)
        if cancelled is None:
            return error_response("No active job found", 404)
        cancelled.set()
        processing_status[job_id] = {"status": "processing", "progress": 0, "stage": "Cancelling"}
    return jsonify({"status": "cancelling", "job_id": job_id})


def execute(job_id, settings, prepare_source):
    cancelled = threading.Event()
    started = time.monotonic()
    with process_lock:
        if job_id in active_jobs:
            return error_response("Job is already processing", 409)
        active_jobs[job_id] = cancelled

    def report(progress, stage):
        elapsed = int(time.monotonic() - started)
        with process_lock:
            processing_status[job_id] = {
                "status": "completed" if progress == 100 else "processing",
                "progress": progress, "stage": stage, "elapsed": f"{elapsed}s",
            }

    source = None
    try:
        source = prepare_source(cancelled)
        result = get_engine().run(source, job_id, settings, report, cancelled)
        result["format"] = settings.output_format
        return jsonify(result)
    except CancelledError as error:
        with process_lock:
            processing_status[job_id] = {"status": "cancelled", "progress": 0, "stage": str(error)}
        return error_response(str(error), 409)
    except ValueError as error:
        with process_lock:
            processing_status[job_id] = {"status": "failed", "progress": 0, "stage": str(error)}
        return error_response(str(error), 400)
    except FileExistsError:
        return error_response("This job already has output; submit a new job ID", 409)
    except (OSError, RuntimeError, TimeoutError, ImportError) as error:
        logger.exception("Processing failed for %s", job_id)
        with process_lock:
            processing_status[job_id] = {"status": "failed", "progress": 0, "stage": "Processing failed"}
        return error_response(f"Local processing failed: {error}", 500)
    finally:
        with process_lock:
            active_jobs.pop(job_id, None)
        if source is not None:
            Path(source).unlink(missing_ok=True)
            directory = Path(source).parent
            if directory.parent.resolve() == Path(UPLOAD_FOLDER).resolve() and directory.name == job_id:
                shutil.rmtree(directory)


@app.route("/process", methods=["POST"])
def process_audio():
    if "file" not in request.files:
        return error_response("No file provided", 400)
    job_id = request.form.get("job_id", "")
    if not validate_job_id(job_id):
        return error_response("Invalid job ID", 400)
    try:
        settings = Settings.from_mapping(request.form)
    except ValueError as error:
        return error_response(str(error), 400)
    file = request.files["file"]
    filename = secure_filename(file.filename or "")
    if not filename:
        return error_response("No file selected", 400)
    if not allowed_file(filename):
        return error_response("File type not allowed", 400)

    def prepare_source(_cancelled):
        directory = Path(safe_join(UPLOAD_FOLDER, job_id))
        directory.mkdir(parents=True, exist_ok=True)
        path = Path(safe_join(directory, filename.removeprefix(f"{job_id}_")))
        owned = False
        try:
            with path.open("xb") as target:
                owned = True
                file.save(target)
            if path.stat().st_size > 100 * 1024 * 1024:
                raise ValueError("File is too large. Maximum allowed size is 100 MiB.")
            return path
        except BaseException:
            if owned:
                path.unlink(missing_ok=True)
            raise

    return execute(job_id, settings, prepare_source)


@app.route("/import", methods=["POST"])
def import_audio():
    from track2stem_engine.sources import canonical_youtube_url, download_youtube

    values = request.get_json(silent=True)
    if not isinstance(values, dict) or not validate_job_id(values.get("job_id")):
        return error_response("Provide a valid job ID and YouTube URL", 400)
    try:
        url = canonical_youtube_url(values.get("url"))
        raw_settings = values.get("settings", {})
        if not isinstance(raw_settings, dict):
            raise ValueError("Settings must be a JSON object")
        settings = Settings.from_mapping(raw_settings)
    except ValueError as error:
        return error_response(str(error), 400)
    job_id = values["job_id"]

    def prepare_source(cancelled):
        directory = Path(safe_join(UPLOAD_FOLDER, job_id))
        directory.mkdir(parents=True, exist_ok=False)
        try:
            return download_youtube(url, directory, cancelled)
        except BaseException:
            shutil.rmtree(directory)
            raise

    return execute(job_id, settings, prepare_source)


@app.route("/mix/<job_id>", methods=["POST"])
def remix_job(job_id):
    if not validate_job_id(job_id):
        return error_response("Invalid job ID", 400)
    values = request.get_json(silent=True)
    if not isinstance(values, dict) or "gains" not in values:
        return error_response("Provide a JSON object with per-instrument gains", 400)
    try:
        return jsonify(get_engine().remix(job_id, values["gains"]))
    except FileNotFoundError:
        return error_response("Stored stems are missing; separate the source again", 404)
    except ValueError as error:
        return error_response(str(error), 400)
    except (OSError, RuntimeError, TimeoutError):
        logger.exception("Remix failed for %s", job_id)
        return error_response("Mix export failed; the previous outputs are still available", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)),
            debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
