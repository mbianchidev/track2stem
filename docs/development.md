# Development

[Documentation index](README.md) | [Contributing](../CONTRIBUTING.md) | [Agent instructions](../AGENTS.md)

## Toolchains

Containers and [CI](../.github/workflows/ci.yml) use Node.js 24, Go 1.27.3, and Python 3.13. Match those versions for native development. The processor also needs FFmpeg and libsndfile, installed in its Dockerfile.

Use the [Compose quickstart](../README.md#quickstart) for the full stack. Full native backend/processor execution is not turnkey: both use writable, shared `/app/uploads` and `/app/outputs` paths, and the processor uses POSIX pseudo-terminals. Use Linux containers rather than native Windows Python.

## Frontend development

Keep the Compose backend/processor running, then start Vite from the repository root:

```bash
cd frontend
npm ci
npm start
```

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
python3.13 -m venv .venv
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

## Architecture

| Path | Implementation | Responsibility |
|------|----------------|----------------|
| [frontend/](../frontend/) | React 19, Vite, Nginx | Upload settings, status polling, localStorage history, waveforms, and download controls |
| [backend/](../backend/) | Go, Gorilla Mux | Job records, multipart uploads, processor requests, and streaming downloads |
| [processor/](../processor/) | Python 3.13, Flask, Demucs 4.0.1, FFmpeg | Separation subprocesses, progress parsing, cancellation, FLAC conversion, and backing mixes |
| [scripts/](../scripts/) | Shell | Stack health check |
| [.github/workflows/](../.github/workflows/) | GitHub Actions | CI and CodeQL |

The upload flow is browser -> backend -> processor. The backend assigns a job ID and returns a job record while processing continues in a goroutine. The processor runs Demucs, arranges outputs by job, and returns their paths; the backend records completion and serves downloads.

Backend and processor share `uploads` and `outputs` volumes at `/app/uploads` and `/app/outputs`. Only audio files persist there; backend jobs and processor progress live in memory. The frontend polls every two seconds and separately persists UI metadata in localStorage.

Nginx serves the production frontend and proxies `/api` to the backend. Vite uses its development proxy for the same path. The processor is not exposed on a host port.

## Documentation screenshot

[The README screenshot](images/track2stem.png) is captured from the real frontend in headless Chromium. It shows a generated WAV selected in the upload form with its browser-rendered waveform. The jobs-list response was mocked as empty to isolate the UI capture from backend state; no upload or model inference was performed.

To refresh it, run the frontend locally, use a fresh browser context, select generated audio with a neutral filename, wait for the waveform and fonts to finish rendering, and capture the unmodified interface. Do not use personal audio, production jobs, or fabricated completed-job results.
