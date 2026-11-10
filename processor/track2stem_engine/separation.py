import logging
import math
import os
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import numpy as np

from .audio import check_cancelled, read_audio

logger = logging.getLogger(__name__)


class Separator:
    def __init__(self, model_dir):
        self.model_dir = Path(model_dir)
        self._model = None
        self._model_name = None

    def __call__(self, source, settings, report, cancelled):
        import torch
        from demucs.apply import apply_model
        from demucs.pretrained import get_model

        torch.set_num_threads(max(1, min(8, (os.process_cpu_count() or 1) // settings.workers)))
        torch.hub.set_dir(str(self.model_dir / "torch"))
        audio, sample_rate = read_audio(source, cancelled)
        check_cancelled(cancelled)
        if self._model_name != settings.model:
            report(8, f"Loading {settings.model}; first use downloads model weights")
            self._model = None
            self._model = get_model(settings.model).cpu().eval()
            self._model_name = settings.model
        model = self._model
        if model.samplerate != sample_rate or model.audio_channels != 2:
            raise RuntimeError("The selected model requires unsupported audio dimensions")
        maximum = getattr(model, "max_allowed_segment", float("inf"))
        default = getattr(model, "segment", None)
        if default is None:
            default = model.models[0].segment
        segment = settings.segment or min(default, maximum)
        if segment > maximum:
            raise ValueError(f"{settings.model} supports segments up to {maximum:g}s; use Default, 5s or 7s")
        length = max(1, int(segment * sample_rate))
        overlap = settings.overlap if settings.overlap is not None else .25
        stride = max(1, int(length * (1 - overlap)))
        offsets = iter(range(0, len(audio), stride))
        total = math.ceil(len(audio) / stride)
        weights = np.minimum(np.arange(1, length + 1), np.arange(length, 0, -1)).astype(np.float32)
        weights /= weights.max()
        reference = audio.mean(axis=1)
        deviation = float(reference.std())
        mean = float(reference.mean())
        if deviation < 1e-8:
            raise ValueError("Source audio is silent; select audible audio")
        normalized = torch.from_numpy(((audio - mean) / deviation).T.copy())
        combined = np.zeros((len(model.sources), len(audio), 2), dtype=np.float32)
        total_weights = np.zeros(len(audio), dtype=np.float32)

        def predict(offset):
            check_cancelled(cancelled)
            chunk = normalized[:, offset:offset + length]
            with torch.inference_mode():
                prediction = apply_model(
                    model, chunk[None], shifts=settings.shifts, split=False,
                    device="cpu", segment=segment, num_workers=0,
                )[0].permute(0, 2, 1).numpy()
            check_cancelled(cancelled)
            return prediction

        report(12, f"Separating with {settings.workers} CPU worker(s), {segment:g}s segments")
        finished = 0
        with ThreadPoolExecutor(max_workers=settings.workers, thread_name_prefix="separation") as pool:
            pending = {}
            try:
                for _ in range(settings.workers):
                    offset = next(offsets, None)
                    if offset is not None:
                        pending[pool.submit(predict, offset)] = offset
                while pending:
                    check_cancelled(cancelled)
                    ready, _ = wait(pending, timeout=.1, return_when=FIRST_COMPLETED)
                    for future in ready:
                        offset = pending.pop(future)
                        prediction = future.result()
                        count = prediction.shape[1]
                        combined[:, offset:offset + count] += prediction * weights[:count, None]
                        total_weights[offset:offset + count] += weights[:count]
                        finished += 1
                        report(12 + int(60 * finished / total), f"Separated segment {finished}/{total}")
                        next_offset = next(offsets, None)
                        if next_offset is not None:
                            pending[pool.submit(predict, next_offset)] = next_offset
            except BaseException:
                for future in pending:
                    future.cancel()
                raise
        check_cancelled(cancelled)
        if np.any(total_weights <= 0):
            raise RuntimeError("Separation left uncovered audio samples")
        combined = combined / total_weights[None, :, None] * deviation + mean
        result = dict(zip(model.sources, combined, strict=True))
        if set(result) != set(settings.stems):
            raise RuntimeError("The selected model returned an unexpected set of instruments")
        return result, sample_rate
