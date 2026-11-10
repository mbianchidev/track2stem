# Development

[Documentation index](README.md) | [Contributing](../CONTRIBUTING.md) | [Agent instructions](../AGENTS.md)

## Toolchains

Containers and [CI](../.github/workflows/ci.yml) use Node.js 26.12.1, Go 1.27.3, and Python 3.14.9. Match those versions for native development. The processor also needs FFmpeg and libsndfile, installed in its Dockerfile.

The frontend already uses stable React and React DOM 19.3.1. Processor interpreter changes must satisfy the [Python upgrade gate](#python-upgrade-gate); a new stable Python release alone is not sufficient.

The processor Dockerfile installs PyTorch, Torchaudio, and TorchCodec together from PyTorch's CPU wheel index before the remaining requirements. Do not replace TorchCodec with its default PyPI wheel, which can require CUDA libraries. The image build checks dependency consistency and imports the audio stack, failing immediately if CPU-only imports are broken.

Use the [Compose quickstart](../README.md#quickstart) for the full web stack. Native web execution requires matching writable `UPLOAD_FOLDER` and `OUTPUT_FOLDER` values in Go and Flask, plus `MODEL_FOLDER` for cached weights. The headless engine does not import Flask or depend on `/app`, pseudo-terminals, or a browser.

## Python upgrade gate

### Why Python 3.15.1 is blocked

As checked on **2026-10-25**, Python 3.15.1 is stable, but stable **Torchaudio 2.11.0** has no compatible CPython 3.15 wheels in the [PyTorch CPU index](https://download.pytorch.org/whl/cpu/torchaudio/) for Linux amd64 or arm64. Its available wheels stop at CPython 3.14. The processor requires Torchaudio through Demucs; installing PyTorch alone or passing Flask tests cannot replace it.

This is a native wheel/ABI availability constraint, not a Python syntax or Flask compatibility problem. `cp315` is the regular CPython 3.15 ABI, including Python 3.15.1; a `cp314` wheel cannot satisfy it. CPU PyTorch and [CPU TorchCodec](https://download.pytorch.org/whl/cpu/torchcodec/) already have `cp315` wheels, so neither is the current blocker.

Reproduce the Torchaudio wheel-resolution failure without installing packages:

```bash
python3 -m pip install --dry-run --ignore-installed --no-deps \
  --only-binary=:all: \
  --python-version 3.15 --implementation cp --abi cp315 \
  --platform manylinux_2_28_x86_64 \
  --target /tmp/track2stem-python315-wheel-check \
  --index-url https://download.pytorch.org/whl/cpu \
  torchaudio
```

Repeat with `--platform manylinux_2_28_aarch64` for arm64. Both probes currently fail with `No matching distribution found for torchaudio`. This command checks only wheel availability, not installation, shared-library loading, or inference; do not use its `--no-deps` option to bypass dependency resolution in a real installation.

The last validated CPU stack is **Python 3.14.9, Demucs 4.0.1, PyTorch 2.14.1+cpu, Torchaudio 2.11.0+cpu, and TorchCodec 0.17.0+cpu**. Full installation and real separation succeeded with that combination. These are dated compatibility results, not a permanent ban on Python 3.15 or a replacement for checking newer mutually compatible releases.

### Requirements before upgrading

Agents and contributors must complete all of the following before advancing the processor's Python version:

1. Recheck the latest stable Python release and stable, mutually compatible PyTorch, Torchaudio, and TorchCodec CPU wheels for the candidate ABI and target Linux architectures. Cover amd64 (CI) and arm64 (Apple Silicon container development). Package `Requires-Python` metadata, a wheel for another ABI, or a macOS-only installation is not proof of Linux container support.
2. Build the complete [processor image](../processor/Dockerfile) with the candidate interpreter and all [requirements](../processor/requirements.txt), retaining the CPU wheel index for all three audio packages. Require successful dependency resolution, `python -m pip check`, imports of `torch`, `torchaudio`, and `torchcodec`, `torch.version.cuda is None`, and `python -m demucs --help`. FFmpeg, libsndfile, and the codec shared libraries must load without CUDA dependencies. Do not hide installation/import failures or substitute an untested source build or prerelease wheel.
3. Require the [processor validation tests](#processor-tests), an uncached [Compose build and startup checks](#container-and-integration-checks), and the existing CI checks to pass with the selected runtime. Validation tests and health endpoints deliberately do not load a separation model, so these checks alone do not authorize an upgrade.
4. Run real `htdemucs_6s` inference on a generated 44.1-kHz stereo WAV fixture. Verify all six WAV stems; FLAC vocals plus instrumental; and 320-kbps MP3 isolation of a non-vocal stem plus backing. Check that each file is non-empty, decode it with FFmpeg, and use FFprobe to confirm the requested codecs/MP3 bitrate, 16-bit PCM WAV output, sample rate, channels, and expected duration. Exercise upload, completed progress, and stem downloads through Nginx -> Go -> Python. Preserve CPU-only execution, six/four-stem model behavior, and all existing output formats.
5. Update the Python selection in [Docker](../processor/Dockerfile), [CI](../.github/workflows/ci.yml), this guide, and [AGENTS.md](../AGENTS.md) together; change coupled dependency constraints only when needed for proven compatibility. Record exact interpreter/dependency versions, architectures, commands, results, and any remaining upstream warnings in the PR. Keep the blocker explanation dated and revise it when wheel availability changes.
6. If stable CPU wheels, full installation, imports, or real inference fail, retain the latest maintained patch of the last proven-compatible Python series and document the specific failure. Do not remove Demucs/Torchaudio/TorchCodec, drop audio features, add CUDA, or redesign the ML architecture just to claim a newer interpreter version.

## Frontend development

Keep the Compose backend/processor running, then start Vite from the repository root:

```bash
cd frontend
npm ci
npm start
```

The version-pinned `allowScripts` entry in `frontend/package.json` approves only `fsevents@2.3.3`, Vite's optional macOS file-watching dependency. After reviewing a future version's install scripts, run `npm install-scripts approve fsevents` from `frontend/` to refresh that approval; do not blanket-approve dependency scripts.

Open Vite's printed URL, normally http://localhost:5173. [vite.config.mjs](../frontend/vite.config.mjs) proxies `/api` to `http://localhost:8080`.

From `frontend/`, run:

```bash
CI=true npm test
npm run build
```

The build writes `frontend/dist/`. There is no separate lint script in the current package manifest. API URL behavior is documented in [configuration](configuration.md#service-configuration).

Frontend tests use mocked API responses and synthetic audio only. `App.test.jsx` covers upload options, validation, job states, persistence, progress, and history actions; `Spectrogram.test.jsx` covers waveform source changes, responsive canvas sizing, decoding failures, and audio-context cleanup.

The UI fonts are bundled locally through Fontsource. Builds retain their original OFL notices under `font-licenses/`; rendering does not contact Google Fonts.

### Real browser integration

Install the frontend dependencies and Chromium, and provide a Python environment containing the full processor requirements:

```bash
cd frontend
npm ci
npx playwright install chromium
TRACK2STEM_TEST_PYTHON=/absolute/path/to/processor-venv/bin/python npm run test:e2e
```

By default, Playwright starts owned Flask/Go/Vite processes on loopback ports 20500, 20080 and 20173 and stops them afterward. Set `TRACK2STEM_TEST_MODELS` to an existing model cache to avoid repeated downloads. Tests generate their own audio and verify actual separation, PCM16 WAV/FLAC/320-kbps MP3 downloads, backing-instrument levels, boosted remix output, browser refresh, and rejected remote URLs.

For an already-running Compose stack, use `TRACK2STEM_TEST_URL=http://127.0.0.1:3000 npm run test:e2e`. CI runs this path through Nginx after building and starting all services. FFprobe must be available to inspect downloads. Native builds have a [separate worker/editor workflow](native-plugin.md#build-independently-of-the-web-stack).

### CPU measurements

The [controlled CPU report](benchmarks/cpu-separation.json) uses original 60-second MIDI/SoundFont mixtures, native Apple Silicon, Python 3.14.10, CPU PyTorch 2.15.0 and 18 available logical CPUs. Each case ran in a fresh process, with one cold model load/inference followed by three warm inferences. Weights were already cached; download time is excluded. No competing evaluations were launched by the measuring session.

Cells show **median warm seconds / peak process RSS in MiB**. RSS is the high-water mark across inference repetitions, measured before loading reference stems for scoring, not a GPU allocation or a per-segment estimate.

| Fixture / profile | 1 worker | 2 workers | 4 workers |
|-------------------|----------|-----------|-----------|
| Clean / six-stem defaults | 11.26 / 2113 | 7.68 / 3145 | 6.31 / 3606 |
| Distorted / six-stem defaults | 11.59 / 2177 | 7.86 / 3218 | 6.64 / 3690 |
| Clean / bounded fast profile | 6.09 / 1884 | 4.12 / 2674 | 3.89 / 3188 |
| Distorted / bounded fast profile | 6.73 / 1883 | 3.95 / 2637 | 3.93 / 3103 |

Two/four six-stem workers achieved about 1.47x/1.75-1.79x speedup, with maximum sample differences below 1.84e-6. Bounded fast workers differ by at most 1.63e-6. More workers increase memory and are not always faster.

The old fast setting left Hybrid v3's long default segment unbounded and peaked at 7082-8546 MiB. The actual fast preset now uses seven-second windows: its one-worker peak is about 1884 MiB, while remaining 1.72-1.85x faster than six-stem defaults on these fixtures. Shorter windows cost some one-worker time compared with the old fast setting. Common-four-stem SI-SDR changed by at most 0.146 dB relative to that setting; the raw report includes every stem, repetition, cold time, CPU time and legacy comparison. Six-stem guitar/piano outputs are summed into `other` for the common-four comparison.

These are synthetic-corpus measurements, not natural-song quality scores, physical deadline qualification, minimum hardware requirements or general speed guarantees. The default model remains six-stem.

### Musical measurements and reproduction

[Musical reference results](benchmarks/musical-quality.json) retain failures as well as improvements. The fixtures are original MIDI rendered headlessly with the checksum-pinned GeneralUser GS 2.0.3 SoundFont. Its license permits generated music; the font remains a test download, not a bundled runtime/model asset.

| Scope | Measured result |
|-------|-----------------|
| 128-second structural form, unchanged reference stems | Boundary F1 improved from 0.111 to 1.0 at one-second tolerance; time-weighted labels improved from 0.676 to 1.0. |
| Same form after actual six-stem separation | Boundary F1 1.0, time-weighted labels 0.875. The bridge was labeled solo. |
| Different 90-second clean-guitar form | Boundary F1 1.0, labels 0.889 with either reference or inferred stems. The solo was labeled bridge. |
| Standard / room / power drum kits | Nine-class onset/pitch F1 at 50 ms: 0.952 / 0.545 / 1.0, versus 0.556 / 0.600 / 0.571 before the decoder/acoustic changes. The room kit still misclassifies toms; do not hide that regression. |
| Clean / distorted guitar reference stems | Exact-pitch onset F1 at 50 ms: 0.918 / 0.928, versus 0.918 / 0.539 for raw neural activations. Bounded acoustic backtracking corrects delayed activations without degrading this clean reference. |
| Bass reference stems | Fundamental-guided monophonic selection improves F1 from 0.606 to 0.967 at 50 ms. All raw candidates remain recoverable; these are reference-stem scores, not separation-plus-transcription accuracy. |
| Original synthetic sung lyrics | Large-v3-turbo without speech VAD achieved 0 word errors on fixed 15-word and 14-word references through the production wrapper. This does not establish accuracy on natural singing. |
| Fixed-pan two-group synthetic singing | Spatial lead/backing SI-SDR 51.39/43.23 dB versus mixture 7.98/-7.94 dB; maximum reconstruction error 2.98e-8. This does not qualify mono, changing-pan, reverberant or larger ensembles. |

The licensed mono neural vocal model did not improve the robot-voice reference. Its provenance is resolved, but that is not an accuracy claim. Section scores and tuning rankings remain heuristic estimates. Drum evidence covers nine common classes, not every one of the model's 26 mapped classes.

To reproduce the public MIDI corpus, provide the full processor environment, FFmpeg and the headless `fluidsynth` executable. Choose new output paths and a writable model cache:

```bash
python scripts/benchmark-audio.py \
  --models /path/to/models --output /path/to/new-audio-benchmark \
  --duration 60 --repeats 3
```

`--tasks separation`, `pitched`, `drums` or `sections` selects a subset. Separation cases run sequentially in isolated child processes and retain input specifications; musical checks retain their MIDI/reference data. Do not run competing model evaluations while measuring CPU time. Quality-run elapsed times are not substitutes for that isolated performance report.

For private synthetic-singing evaluation on macOS, the existing Good News/Cellos system voices can generate the original reference texts:

```bash
python scripts/benchmark-lyrics.py \
  --fixtures /private/path/to/new-singing-fixtures --models /path/to/models \
  --model base small large-v3-turbo --vad both --generate-macos \
  --output /private/path/to/new-lyrics-results.json
```

System-voice outputs have separate redistribution/use restrictions. Keep those audio fixtures private and outside the repository; the generator refuses a repository output path. Never publish them as benchmark assets. Neither corpus establishes broad musical accuracy; all automatic notation and labels require review.

## Backend checks

From the repository root, with the matching Go toolchain:

```bash
cd backend
go mod download
go mod verify
go build ./...
go test -race -timeout=5m ./...
```

Follow Go formatting (`gofmt`) and existing handler/helper conventions. The API uses Gorilla Mux and stores jobs in a mutex-protected in-memory map.

## Processor tests

For deterministic engine/web tests, install the same dependency set used by CI. FFmpeg and libsndfile are required. Demucs, Whisper, ONNX Runtime and model downloads are not needed for this suite; model boundaries are injected in unit tests:

```bash
cd processor
python3.14 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-test.txt
python -m pytest -q
```

The tests cover validation/path safety, real FFmpeg exports and per-instrument remixes, variable-tempo synthetic clicks, complementary vocal windows, note re-attacks, MusicXML/MIDI timing, lyrics/subtitles, safe video imports and the Flask adapter. `conftest.py` redirects web storage to temporary directories. Mocked model outputs do not establish separation/transcription quality or native runtime compatibility; real inference remains a separate requirement.

CI promotes numeric `RuntimeWarning` diagnostics to errors. Pitch evidence uses bounded float64 YIN input so Librosa's lazily specialized Numba complex-magnitude loop cannot introduce an order-dependent float64-to-float32 output cast. To verify a cold JIT cache without removing any shared/user cache, set `NUMBA_CACHE_DIR` to a new temporary directory and run `python -m pytest -q -W error::RuntimeWarning`. Native release identity/checksum tests run with `python -m unittest discover -s plugin/tests -p test_release.py` from the repository root.

## Container and integration checks

From the repository root:

```bash
docker compose config --quiet
docker compose build --no-cache
docker compose up -d --wait --wait-timeout 300
./scripts/health-check.sh
```

CI builds all images, checks startup health, and runs the real browser separation suite through Nginx. Health checks alone do not prove model inference. For processing changes, use generated audio or a synthetic fixture, verify separation completes, download the expected stems, and inspect logs and audio before opening a PR. Never use private or customer data in tests, logs, screenshots, or examples.

Compose builds local images and has no container-publication entrypoint; do not treat those images as a published container release. The independent [native release workflow](native-plugin.md#release-workflow) can publish verified VST3/AU packages after explicit activation/manual authorization. Its automatic tag trigger is intentionally disabled.

### CI image caching

CI generates a Buildx Bake definition with `docker compose build --print`, preserving Compose's service settings and image tags. Bake loads all three images into the runner, then `docker compose up --no-build` runs the same startup health checks against those images.

Each service has a separate GitHub Actions v2 layer cache scoped by runner OS and architecture. `mode=max` retains intermediate build stages, including dependency installation. Base images are pulled on every run; missing or evicted caches still build normally. Cache access follows GitHub's existing branch and PR permissions, without additional token permissions. Build-record artifact uploads are disabled to avoid extra storage and transfer overhead.

The component `.dockerignore` files exclude local dependencies, build outputs, and Python test caches from build contexts. Existing web job names and CodeQL coverage are unchanged. The separate path-filtered native workflow builds the packaged runtime, exercises its real worker/editor on macOS, and verifies ZIP installation in an isolated home. Artifact upload requires an explicit manual run. Local container validation should continue using `docker compose build --no-cache` as shown above.

## Architecture

| Path | Implementation | Responsibility |
|------|----------------|----------------|
| [frontend/](../frontend/) | React 19, Vite, Nginx | Upload settings, status polling, localStorage history, waveforms, and download controls |
| [backend/](../backend/) | Go, Gorilla Mux | Job records, multipart uploads, processor requests, and streaming downloads |
| [processor/](../processor/) | Python 3.14, Flask adapter, shared headless engine, Demucs 4.0.1, FFmpeg | Cached CPU inference, overlap-add workers, progress/cancellation, mixes, analysis and transcription |
| [plugin/](../plugin/) | iPlug2, VST3/AUv2, native WebView, bundled Python worker | Offline DAW import/export, process isolation, project-state adapter, independent build/package |
| [scripts/](../scripts/) | Shell | Stack health check |
| [.github/workflows/](../.github/workflows/) | GitHub Actions | CI and CodeQL |

The upload flow is browser -> backend -> Flask adapter -> `track2stem_engine.Engine`. The backend assigns a job ID and streams audio to the processor while processing continues in a goroutine. The engine owns settings validation, storage, cached CPU inference, progress/cancellation, exports, mixes and optional practice tools. The Go adapter retains its public API and serves audio/artifacts using allowlisted job mappings.

The headless settings/job/result contract is version 1. Engine construction injects output/model locations; callers retain ownership of source files. Each job keeps a manifest and float WAV source stems for remixes. A bounded worker pool shares one loaded model and reassembles overlapping windows using normalized triangular weights. Zero shifts is explicit rather than the Demucs CLI's implicit augmentation default.

Backend and processor share `uploads` and `outputs` volumes at `/app/uploads` and `/app/outputs`. Only audio files persist there; backend jobs and processor progress live in memory. The frontend polls every two seconds and separately persists UI metadata in localStorage.

Nginx serves the production frontend and proxies `/api` to the backend. Vite uses its development proxy for the same path. The processor is not exposed on a host port.

## Documentation screenshot

[The README screenshot](images/track2stem.png) is captured from the real frontend in headless Chromium. It shows a generated WAV, its source waveform, six actual Demucs outputs, instrument controls, real analysis/notation exports and recent-job metadata. The browser test uploads and processes the generated fixture through Go and Flask; no completed jobs or separation results are fabricated.

To refresh it, set `TRACK2STEM_CAPTURE_README=1` when running the browser integration suite. It uses a fresh 1440 px context, reselects the same generated source after actual processing, waits for waveforms/fonts, and captures the full unmodified interface. `TRACK2STEM_CAPTURE_FIXTURE` can select an original synthetic stereo 44.1-kHz, exactly ten-second WAV instead of the default generated tone fixture; the same processing, duration and export assertions still apply. Do not use personal audio or production jobs.
