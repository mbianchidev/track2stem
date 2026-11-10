# SPDX-License-Identifier: CC-BY-SA-4.0
# Standalone inference interface for the adapted ADT_STR component; see LICENSE.
import argparse
import hashlib
import json
import logging
import math
import os
from pathlib import Path


def main(arguments=None):
    parser = argparse.ArgumentParser(description="Isolated ADT_STR CPU drum transcription; CC-BY-SA-4.0")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args(arguments)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    def check_owner():
        if args.parent_pid is not None and os.getppid() != args.parent_pid:
            raise RuntimeError("The owning process stopped; refusing orphaned drum inference")

    try:
        check_owner()
        import numpy as np
        import soundfile as sf
        import torch
        import torchaudio
        from safetensors.torch import load_file
        from .events import attack_envelope, decode_tokens
        from .network import DrumModel

        check_owner()
        if args.output.exists():
            raise FileExistsError("Drum output already exists; choose an owned, empty destination")
        torch.set_num_threads(max(1, min(4, os.process_cpu_count() or 1)))
        model = DrumModel()
        with args.weights.open("rb") as source:
            weight_hash = hashlib.file_digest(source, "sha256").hexdigest()
        model.load_state_dict(load_file(args.weights, device="cpu"), strict=True, assign=True)
        model.eval()
        check_owner()
        notes = []
        with sf.SoundFile(args.input) as source:
            if not 0 < source.frames / source.samplerate <= 3600:
                raise ValueError("Drum audio must be non-empty and no longer than 60 minutes")
            step = max(1, round(source.samplerate * 2))
            frames = max(1, round(source.samplerate * 2.56))
            total = math.ceil(source.frames / step)
            resample = torchaudio.transforms.Resample(source.samplerate, 24000)
            source_peak = 0.
            while len(block := source.read(frames, dtype="float32", always_2d=True)):
                check_owner()
                source_peak = max(source_peak, float(np.max(np.abs(block.mean(axis=1)))))
            attack_threshold = max(1e-5, source_peak * .002)
            for index in range(total):
                check_owner()
                center = index * step
                first = max(0, center - round(source.samplerate * .28))
                source.seek(first)
                audio = source.read(frames, dtype="float32", always_2d=True)
                if not np.isfinite(audio).all():
                    raise ValueError("Drum audio contains non-finite samples")
                waveform = resample(torch.from_numpy(audio.mean(axis=1)))
                peak = float(waveform.abs().max())
                attacks = attack_envelope(waveform.numpy(), include_initial=first == 0)
                central_first = round((center - first) / source.samplerate * 100)
                central_last = min(len(attacks), round((center + step - first) / source.samplerate * 100))
                if peak < 1e-4 or attacks[central_first:central_last].max(initial=0) < attack_threshold:
                    print("T2S_DRUM_PROGRESS " + json.dumps({"completed": index + 1, "total": total}), flush=True)
                    continue
                gain = min(16., .8 / peak)
                padded = torch.zeros((1, 61440))
                padded[0, :min(61440, len(waveform))] = waveform[:61440] * gain
                tokens = model.sample(padded, check_owner)
                offset, end = first / source.samplerate, source.frames / source.samplerate
                for note in decode_tokens(tokens):
                    start = note["start"] + offset
                    if not center / source.samplerate <= start < min(end, (center + step) / source.samplerate):
                        continue
                    notes.append({**note, "start": round(start, 5),
                                  "end": round(min(note["end"] + offset, end), 5),
                                  "velocity": max(1, min(127, round(note["velocity"] / math.sqrt(gain))))})
                print("T2S_DRUM_PROGRESS " + json.dumps({"completed": index + 1, "total": total}), flush=True)
        check_owner()
        notes.sort(key=lambda note: (note["start"], note["pitch"]))
        temporary = args.output.with_suffix(".part")
        try:
            temporary.write_text(json.dumps({"version": 1, "model": "ADT_STR", "weights_sha256": weight_hash,
                                             "license": "CC-BY-SA-4.0",
                                             "preprocessing": "bounded peak normalization; overlapping context; release-only window suppression; input-gain velocity compensation",
                                             "notes": notes}, allow_nan=False),
                                 encoding="utf-8")
            temporary.replace(args.output)
        finally:
            temporary.unlink(missing_ok=True)
    except (OSError, RuntimeError, ValueError, ImportError) as error:
        logging.exception("Drum transcription failed: %s", error)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
