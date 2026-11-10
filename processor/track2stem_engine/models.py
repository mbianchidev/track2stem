import hashlib
import logging
import os
import urllib.error
import urllib.request
import uuid
from functools import lru_cache
from pathlib import Path
from dataclasses import dataclass

from .audio import check_cancelled

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelSpec:
    url: str
    sha256: str
    filename: str
    max_bytes: int = 200 * 1024 * 1024


MODELS = {
    "basic-pitch": ModelSpec(
        "https://raw.githubusercontent.com/spotify/basic-pitch/fa5997af0a8210982619003269994a1be25eddf3/basic_pitch/saved_models/icassp_2022/nmp.onnx",
        "2c3c1d144bfa61ad236e92e169c13535c880469a12a047d4e73451f2c059a0ec",
        "basic-pitch.onnx",
    ),
    "karaoke": ModelSpec(
        "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/UVR_MDXNET_KARA_2.onnx",
        "bf32e15105a09c0f7dddd2b67346146334d6f3ecb399ed7638eba2ab07cbf5f4",
        "karaoke.onnx",
    ),
    "beat-small": ModelSpec(
        "https://cloud.cp.jku.at/public.php/dav/files/7ik4RrBKTS273gp/small0.ckpt",
        "6074be2c4d490c5f6101fcc374a1ec72ae93456e23bb6019783b849f5dc7d47b",
        "beat-small.ckpt",
    ),
    "drum-str": ModelSpec(
        "https://huggingface.co/Pierfrancesco/adt-str/resolve/a33c5c6b191a4ca1e0f6dc22140947485eb36ce8/setting-tau-0.8/model.safetensors",
        "f94d1773d929166e0a3f63d305975aa6667512f8a71d7706872e1f8b23ca930b",
        "drum-str.safetensors", max_bytes=350 * 1024 * 1024,
    ),
}


def ensure_model(name, model_dir, report, cancelled):
    specification = MODELS[name]
    directory = Path(model_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / specification.filename
    if target.is_file():
        with target.open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if actual != specification.sha256:
            raise RuntimeError(f"Cached {name} model is corrupt. Remove {target.name} from the model cache and retry.")
        return target
    if os.environ.get("TRACK2STEM_OFFLINE") == "1":
        raise RuntimeError(f"{name} is not cached. Connect once to download its weights before using offline mode.")
    report(74, f"Downloading {name} model for local CPU processing")
    temporary = directory / f".{name}-{uuid.uuid4()}.part"
    digest = hashlib.sha256()
    try:
        try:
            with urllib.request.urlopen(specification.url, timeout=30) as response, temporary.open("xb") as output:
                total = 0
                while chunk := response.read(1024 * 1024):
                    check_cancelled(cancelled)
                    total += len(chunk)
                    if total > specification.max_bytes:
                        raise RuntimeError(f"{name} model exceeded its download size limit")
                    digest.update(chunk)
                    output.write(chunk)
        except (urllib.error.URLError, TimeoutError) as error:
            logger.error("Model download failed for %s: %s", name, error)
            raise RuntimeError(f"Could not download {name}. Check internet access and retry; audio stays local.") from error
        if digest.hexdigest() != specification.sha256:
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
