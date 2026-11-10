import hashlib
import logging
import os
import urllib.error
import urllib.request
import uuid
from functools import lru_cache
from pathlib import Path

from .audio import check_cancelled

logger = logging.getLogger(__name__)
MODELS = {
    "basic-pitch": (
        "https://raw.githubusercontent.com/spotify/basic-pitch/fa5997af0a8210982619003269994a1be25eddf3/basic_pitch/saved_models/icassp_2022/nmp.onnx",
        "2c3c1d144bfa61ad236e92e169c13535c880469a12a047d4e73451f2c059a0ec",
    ),
    "karaoke": (
        "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/UVR_MDXNET_KARA_2.onnx",
        "bf32e15105a09c0f7dddd2b67346146334d6f3ecb399ed7638eba2ab07cbf5f4",
    ),
}


def ensure_model(name, model_dir, report, cancelled):
    url, expected = MODELS[name]
    directory = Path(model_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{name}.onnx"
    if target.is_file():
        with target.open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if actual != expected:
            raise RuntimeError(f"Cached {name} model is corrupt. Remove {target.name} from the model cache and retry.")
        return target
    if os.environ.get("TRACK2STEM_OFFLINE") == "1":
        raise RuntimeError(f"{name} is not cached. Connect once to download its weights before using offline mode.")
    report(74, f"Downloading {name} model for local CPU processing")
    temporary = directory / f".{name}-{uuid.uuid4()}.part"
    digest = hashlib.sha256()
    try:
        try:
            with urllib.request.urlopen(url, timeout=30) as response, temporary.open("xb") as output:
                total = 0
                while chunk := response.read(1024 * 1024):
                    check_cancelled(cancelled)
                    total += len(chunk)
                    if total > 200 * 1024 * 1024:
                        raise RuntimeError(f"{name} model exceeded its download size limit")
                    digest.update(chunk)
                    output.write(chunk)
        except (urllib.error.URLError, TimeoutError) as error:
            logger.error("Model download failed for %s: %s", name, error)
            raise RuntimeError(f"Could not download {name}. Check internet access and retry; audio stays local.") from error
        if digest.hexdigest() != expected:
            raise RuntimeError(f"{name} model checksum verification failed")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


@lru_cache(maxsize=2)
def _session(path):
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = min(4, os.process_cpu_count() or 1)
    options.inter_op_num_threads = 1
    return ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])


def get_session(name, model_dir, report, cancelled):
    return _session(ensure_model(name, model_dir, report, cancelled))
