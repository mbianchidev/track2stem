import os
from functools import lru_cache

import numpy as np

from .models import ensure_model


@lru_cache(maxsize=1)
def _separator(path):
    import torch
    from torch import nn
    from asteroid_filterbanks import make_enc_dec
    from .third_party.asteroid_tcn import TemporalMasker

    class VocalModel(nn.Module):
        def __init__(self):
            super().__init__()
            self.encoder, self.decoder = make_enc_dec(
                "torch_stft", n_filters=2048, kernel_size=2048, stride=512, sample_rate=24000)
            self.masker = TemporalMasker()

        def forward(self, audio):
            encoded = self.encoder(audio)
            masked = self.masker(encoded) * encoded[:, None]
            decoded = self.decoder(masked.reshape(-1, encoded.shape[1], encoded.shape[2]))
            return decoded.reshape(audio.shape[0], 2, -1)

    torch.set_num_threads(max(1, min(4, os.process_cpu_count() or 1)))
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    prefix = "ema_model.module."
    weights = {name[len(prefix):]: tensor for name, tensor in checkpoint.items() if name.startswith(prefix)}
    if not weights:
        raise RuntimeError("The licensed vocal checkpoint has no supported EMA inference weights")
    model = VocalModel()
    model.load_state_dict(weights, strict=True, assign=True)
    model.eval()

    def separate(audio):
        with torch.inference_mode():
            result = model(torch.from_numpy(np.asarray(audio, dtype=np.float32))[None, None])[0]
            return result.cpu().numpy()

    return separate


def get_vocal_separator(model_dir, report, cancelled):
    path = ensure_model("vocal-duet", model_dir, report, cancelled)
    return _separator(path)
