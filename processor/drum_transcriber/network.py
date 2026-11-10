# SPDX-License-Identifier: CC-BY-SA-4.0
# Inference-only adaptation of ADT_STR 77dbef225e7029478ebfb916f20c7a00274f0f12.
# Training/Hugging Face dependencies removed; see LICENSE.
import math

import torch
from torch import nn
from torchaudio.transforms import MelSpectrogram

from .events import allowed_tokens


class PositionalEncoding(nn.Module):
    def __init__(self):
        super().__init__()
        scale = torch.exp(-torch.arange(0, 768, 2) * math.log(10000) / 768)
        position = torch.arange(2048).reshape(2048, 1)
        values = torch.zeros((2048, 768))
        values[:, 0::2] = torch.sin(position * scale)
        values[:, 1::2] = torch.cos(position * scale)
        self.register_buffer("pos_embedding", values.unsqueeze(0))

    def forward(self, tokens):
        return tokens + self.pos_embedding[:, :tokens.size(1), :]


class TokenEmbedding(nn.Module):
    def __init__(self):
        super().__init__()
        self.embedding = nn.Embedding(1400, 768)

    def forward(self, tokens):
        return self.embedding(tokens.long()) * math.sqrt(768)


class Encoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.dense_layer = nn.Linear(768, 768, bias=False)
        self.positional_encoding = PositionalEncoding()
        self.layer_norm = nn.LayerNorm(768)
        self.dropout_layer = nn.Dropout(.1)
        layer = nn.TransformerEncoderLayer(768, 6, 3072, .1, activation="gelu", batch_first=True)
        self.encoder = nn.TransformerEncoder(layer, 4)

    def forward(self, source):
        source = self.dropout_layer(self.positional_encoding(self.dense_layer(source)))
        return self.dropout_layer(self.layer_norm(self.encoder(source)))


class Decoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.tgt_tok_emb = TokenEmbedding()
        self.positional_encoding = PositionalEncoding()
        self.dropout_layer = nn.Dropout(.1)
        self.generator = nn.Linear(768, 1400)
        layer = nn.TransformerDecoderLayer(768, 6, 3072, .1, activation="gelu", batch_first=True)
        self.decoder = nn.TransformerDecoder(layer, 4)

    def forward(self, tokens, memory):
        embedded = self.dropout_layer(self.positional_encoding(self.tgt_tok_emb(tokens)))
        future = torch.triu(torch.ones((tokens.shape[1], tokens.shape[1]), dtype=torch.bool), diagonal=1)
        mask = torch.zeros_like(future, dtype=embedded.dtype).masked_fill_(future, -1e4)
        return self.generator(self.decoder(embedded, memory, tgt_mask=mask))


class Spectrogram(nn.Module):
    def __init__(self):
        super().__init__()
        self.compute_spec = MelSpectrogram(sample_rate=24000, n_fft=2048, hop_length=240,
                                          n_mels=128, f_min=20., power=2)

    def forward(self, audio):
        spectrum = self.compute_spec(audio.float())
        normalized = (torch.log(spectrum + 1e-10).clamp(-23, 12) + 23) / 35
        return normalized.permute(0, 2, 1)[:, 5:-6, :]


class DrumModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder = Encoder()
        self.decoder = Decoder()
        self.compute_spectrogram = Spectrogram()
        self.project_to_mel = nn.Linear(128, 768)

    def sample(self, audio, check_owner, maximum_tokens=512, beam_size=5):
        check_owner()
        with torch.inference_mode():
            memory = self.encoder(self.project_to_mel(self.compute_spectrogram(audio)))
            beams = [{"tokens": [2], "score": 0., "finished": False}]
            for _ in range(maximum_tokens - 1):
                check_owner()
                active = [beam for beam in beams if not beam["finished"]]
                if not active:
                    break
                generated = torch.tensor([beam["tokens"] for beam in active], dtype=torch.long)
                logits = self.decoder(generated, memory.expand(len(active), -1, -1))[:, -1, :]
                if not torch.isfinite(logits).all():
                    raise RuntimeError("Drum inference produced non-finite event scores")
                probabilities = logits.log_softmax(dim=-1)
                candidates = [beam for beam in beams if beam["finished"]]
                for index, beam in enumerate(active):
                    valid = allowed_tokens(beam["tokens"])
                    if probabilities[index, valid].exp().sum().item() < .05:
                        continue
                    scores, positions = probabilities[index, valid].topk(min(beam_size, len(valid)))
                    for score, position in zip(scores.tolist(), positions.tolist()):
                        token = valid[position]
                        candidates.append({"tokens": [*beam["tokens"], token],
                                           "score": beam["score"] + score, "finished": token == 3})
                if not candidates:
                    raise RuntimeError("Drum model cannot reliably decode this audio window; no fabricated events were returned")
                candidates.sort(key=lambda beam: beam["score"] / max(1, len(beam["tokens"]) - 1), reverse=True)
                beams = candidates[:beam_size]
            complete = [beam for beam in beams if beam["finished"]]
            if complete:
                best = max(complete, key=lambda beam: beam["score"] / max(1, len(beam["tokens"]) - 1))
                if best["score"] / max(1, len(best["tokens"]) - 1) < -3:
                    raise RuntimeError("Drum prediction confidence is insufficient for a reliable event sequence")
                return best["tokens"]
        raise RuntimeError("Drum inference reached its token limit before completing an audio window")
