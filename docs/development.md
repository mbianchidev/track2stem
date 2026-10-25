# Development

[Documentation index](README.md) | [Contributing](../CONTRIBUTING.md) | [Agent instructions](../AGENTS.md)

## Toolchains

Containers and [CI](../.github/workflows/ci.yml) use Node.js 26.12.1, Go 1.27.3, and Python 3.14.9. Match those versions for native development. The processor also needs FFmpeg and libsndfile, installed in its Dockerfile.

The frontend already uses stable React and React DOM 19.3.1. Processor interpreter changes must satisfy the [Python upgrade gate](#python-upgrade-gate); a new stable Python release alone is not sufficient.

The processor Dockerfile installs PyTorch, Torchaudio, and TorchCodec together from PyTorch's CPU wheel index before the remaining requirements. Do not replace TorchCodec with its default PyPI wheel, which can require CUDA libraries. The image build checks dependency consistency and imports the audio stack, failing immediately if CPU-only imports are broken.

Use the [Compose quickstart](../README.md#quickstart) for the full stack. Full native backend/processor execution is not turnkey: both use writable, shared `/app/uploads` and `/app/outputs` paths, and the processor uses POSIX pseudo-terminals. Use Linux containers rather than native Windows Python.

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

For validation tests only, install the same small dependency set used by CI. Demucs and model downloads are not needed for these tests:

```bash
cd processor
python3.14 -m venv .venv
. .venv/bin/activate
python -m pip install flask werkzeug pytest
python -m pytest test_app.py -v
```

The processor tests cover input validation, path safety, and model/stem allowlists. `conftest.py` patches directory creation during import and redirects test folders to temporary storage. The tests do not mock or exercise separation subprocesses, downloads, conversion, or output audio quality.

## Container and integration checks

From the repository root:

```bash
docker compose config --quiet
docker compose build --no-cache
docker compose up -d --wait --wait-timeout 300
./scripts/health-check.sh
```

CI builds all images and checks startup health. Those checks do not run real model inference. For processing changes, use generated audio or a synthetic fixture, verify separation completes, download the expected stems, and inspect logs and audio before opening a PR. Never use private or customer data in tests, logs, screenshots, or examples.

There is no release/publish entrypoint in the current repository. Compose builds local images; do not treat those development images as a published container release.

### CI image caching

CI generates a Buildx Bake definition with `docker compose build --print`, preserving Compose's service settings and image tags. Bake loads all three images into the runner, then `docker compose up --no-build` runs the same startup health checks against those images.

Each service has a separate GitHub Actions v2 layer cache scoped by runner OS and architecture. `mode=max` retains intermediate build stages, including dependency installation. Base images are pulled on every run; missing or evicted caches still build normally. Cache access follows GitHub's existing branch and PR permissions, without additional token permissions. Build-record artifact uploads are disabled to avoid extra storage and transfer overhead.

The component `.dockerignore` files exclude local dependencies, build outputs, and Python test caches from build contexts. CI events, job names, tests, and CodeQL coverage are unchanged. Local container validation should continue using `docker compose build --no-cache` as shown above.

## Architecture

| Path | Implementation | Responsibility |
|------|----------------|----------------|
| [frontend/](../frontend/) | React 19, Vite, Nginx | Upload settings, status polling, localStorage history, waveforms, and download controls |
| [backend/](../backend/) | Go, Gorilla Mux | Job records, multipart uploads, processor requests, and streaming downloads |
| [processor/](../processor/) | Python 3.14, Flask, Demucs 4.0.1, FFmpeg | Separation subprocesses, progress parsing, cancellation, FLAC conversion, and backing mixes |
| [scripts/](../scripts/) | Shell | Stack health check |
| [.github/workflows/](../.github/workflows/) | GitHub Actions | CI and CodeQL |

The upload flow is browser -> backend -> processor. The backend assigns a job ID and returns a job record while processing continues in a goroutine. The processor runs Demucs, arranges outputs by job, and returns their paths; the backend records completion and serves downloads.

Backend and processor share `uploads` and `outputs` volumes at `/app/uploads` and `/app/outputs`. Only audio files persist there; backend jobs and processor progress live in memory. The frontend polls every two seconds and separately persists UI metadata in localStorage.

Nginx serves the production frontend and proxies `/api` to the backend. Vite uses its development proxy for the same path. The processor is not exposed on a host port.

## Documentation screenshot

[The README screenshot](images/track2stem.png) is captured from the real frontend in headless Chromium. It shows a generated WAV selected in the upload form with its browser-rendered waveform. The jobs-list response was mocked as empty to isolate the UI capture from backend state; no upload or model inference was performed.

To refresh it, run the frontend locally, use a fresh browser context, select generated audio with a neutral filename, wait for the waveform and fonts to finish rendering, and capture the unmodified interface. Do not use personal audio, production jobs, or fabricated completed-job results.
