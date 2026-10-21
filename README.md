# Track2stem 🎵

A self-hosted web application that separates music into downloadable instrument and vocal tracks using [Demucs](https://github.com/facebookresearch/demucs). Run the React interface, Go API, and Python processor together with Docker Compose, then upload audio and choose either all available stems or one isolated stem with a backing track.

## Features

- **Six- or four-stem separation** with a choice of eight Demucs models.
- **All stems or isolate mode**: extract vocals, drums, bass, guitar, or piano where supported, plus the remaining instruments mixed into a backing track.
- **Flexible formats**: upload MP3, WAV, FLAC, OGG, M4A, or AAC; download MP3 at 320 kbps, WAV, or FLAC.
- **Progress and previews**: processing status, elapsed time, and browser-generated audio waveforms for inputs and outputs.
- **Recent jobs and individual downloads**: browser-local history and timer recovery after refresh, plus an API for job status, downloads, and cancellation.

Browser history is not durable server storage. See [limitations and data lifecycle](#limitations-and-data-lifecycle) before relying on saved jobs.

## Quick Start

### Prerequisites

- Git, a Docker-compatible container runtime, and Docker Compose v2 (`docker compose`). The images run Linux containers; macOS and Windows need a runtime that supports them.
- Start with at least 8 GB of RAM available to the container runtime and several GB of free disk space for images, model weights, and audio. Actual requirements depend on the model, track length, and output format.
- Internet access for the image builds and for model downloads on first use. Host ports **3000** and **8080** must be available.

No host Node.js, Go, Python, or GPU installation is required for the Compose setup. The supplied processor uses CPU-only PyTorch and disables CUDA.

### Installation

```bash
git clone https://github.com/mbianchidev/track2stem.git
cd track2stem
docker compose build --no-cache
docker compose up -d --wait --wait-timeout 300
```

Open the [web interface](http://localhost:3000). The [backend health endpoint](http://localhost:8080/api/health) returns `{"status":"ok"}` when the API is available:

```bash
curl --fail http://localhost:8080/api/health
./scripts/health-check.sh
```

The processor's port 5000 is internal to the Compose network, not published to the host. Health checks confirm service availability, not that a model has been downloaded or that audio separation has succeeded.

**First job:** Demucs downloads the selected model when it is first used, not when the containers become healthy. Download size and processing time vary by model and hardware. The model cache is not mounted in a volume, so recreating the processor container can require downloading weights again.

To stop the stack without deleting its audio volumes:

```bash
docker compose down
```

## Usage

1. Open http://localhost:3000 and select an audio file with the file picker.
2. Choose **All 6 Stems / All 4 Stems** or **Isolate One**, then select the output format and model.
3. Click **Upload & Process**. Watch the current job's status and elapsed time until it completes or reports an error.
4. Download individual stems from the current job or **Recent Jobs**. Output filenames include the original track name and stem, such as `song_t2s_vocals.mp3`.

| Model | Available stems |
|-------|-----------------|
| `htdemucs_6s` (default) | Vocals, drums, bass, guitar, piano, other |
| `htdemucs`, `htdemucs_ft`, `hdemucs_mmi`, `mdx`, `mdx_extra`, `mdx_q`, `mdx_extra_q` | Vocals, drums, bass, other |

In isolate mode, isolating vocals produces `vocals` and `instrumental`; isolating another instrument produces that stem and `backing`. Guitar and piano require `htdemucs_6s`. Isolation still separates the full track before mixing the remaining stems, so it is not a faster two-stem inference path.

**Advanced Tuning** exposes segment size, overlap, shifts, and clip mode. Leave segment size at **Default** initially: accepted settings are not necessarily compatible with every model. Larger overlap, additional shifts, and fine-tuned models can increase processing time.

The visualization component is named `Spectrogram`, but it draws amplitude waveforms, not frequency spectrograms. Browser audio decoding support determines which formats can be previewed.

## Architecture

| Service | Implementation | Responsibility |
|---------|----------------|----------------|
| Frontend | [frontend/](frontend/): React 19, Vite, Nginx | Upload UI, status polling, localStorage history, waveforms; Nginx proxies `/api` to the backend |
| Backend | [backend/](backend/): Go, Gorilla Mux | Stores job metadata in memory, forwards processing requests, and serves downloads |
| Processor | [processor/](processor/): Python 3.13, Flask, Demucs 4.0.1, FFmpeg | Runs CPU separation subprocesses, reports progress, converts FLAC, and mixes backing tracks |

The backend and processor share the `uploads` and `outputs` named volumes at `/app/uploads` and `/app/outputs`. The browser polls the backend, which queries processor progress and records the completed output paths.

## Configuration

| Setting | Service | Default / supplied Compose value |
|---------|---------|----------------------------------|
| `PORT` | Backend | `8080` |
| `PROCESSOR_URL` | Backend | Compose sets `http://processor:5000`; set it explicitly for non-Compose runs so processing, progress, and cancellation use the same processor |
| `ALLOWED_ORIGINS` | Backend | `*` when unset; accepts a comma-separated list of browser origins |
| `PORT` | Processor | `5000` |
| `FLASK_DEBUG` | Processor | `false` when unset, but **`true` in the supplied Compose file** |
| `VITE_API_URL` | Frontend | `/api`; read by Vite at development-server startup or build time |

The Compose file hardcodes its service environment and port mappings; it does not interpolate the values in [.env.example](.env.example). Copying that example to `.env` alone does **not** reconfigure the stack. Change the relevant `environment` entries and port mappings in [docker-compose.yml](docker-compose.yml), then recreate the affected services.

For local Vite development, set `VITE_API_URL` in the frontend environment before starting or building it. `REACT_APP_API_URL` in the example file is a legacy name and is not read by the current frontend. Setting `VITE_API_URL` on the running Nginx container will not change an already-built UI.

## API Reference

Use `http://localhost:8080/api` directly, or `/api` through the web interface's Nginx proxy.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/upload` | Upload audio file for processing |
| `GET` | `/api/jobs` | List all jobs |
| `GET` | `/api/jobs/{id}` | Get specific job status |
| `DELETE` | `/api/jobs/{id}` | Cancel/delete a job |
| `GET` | `/api/download/{id}/{stem}` | Download separated stem |
| `GET` | `/api/processing-status/{id}` | Get real-time processing progress |
| `GET` | `/api/health` | Health check |

Upload a file with defaults (`htdemucs_6s`, all stems, MP3):

```bash
curl --fail -F "file=@song.mp3" http://localhost:8080/api/upload
```

Or request isolated vocals and an instrumental backing track in FLAC:

```bash
curl --fail http://localhost:8080/api/upload \
  -F "file=@song.mp3" \
  -F "output_format=flac" \
  -F "model=htdemucs_6s" \
  -F "stem_mode=isolate" \
  -F "isolate_stem=vocals"
```

The upload returns a job record before processing finishes. Copy its `id` into the commands below:

```bash
JOB_ID='replace-with-the-id-from-the-upload-response'

curl --fail "http://localhost:8080/api/jobs/$JOB_ID"
curl --fail "http://localhost:8080/api/processing-status/$JOB_ID"

# After status becomes "completed", save the server-provided filename.
curl --fail --remote-name --remote-header-name \
  "http://localhost:8080/api/download/$JOB_ID/vocals"

# Request cancellation if active, then remove the backend job record.
curl --fail -X DELETE "http://localhost:8080/api/jobs/$JOB_ID"
```

Job statuses are `pending`, `processing`, `completed`, or `failed`. Completed records include `processing_time` and an `output_files` map keyed by stem name. Those map values are internal filesystem paths, not public URLs; use the download endpoint with the job ID and stem key.

Optional multipart fields also include `segment`, `overlap`, `shifts`, and `clip_mode`. The accepted values are defined in [processor/app.py](processor/app.py); model-specific restrictions still apply.

## Development

The containers and CI use **Node.js 24**, **Go 1.27.3**, and **Python 3.13**. Use those versions for native development. The processor also requires FFmpeg and libsndfile, installed by its Dockerfile.

For frontend development, keep the Compose stack running and start Vite in another terminal:

```bash
cd frontend
npm ci
npm start
```

Open the URL printed by Vite, normally http://localhost:5173. [vite.config.mjs](frontend/vite.config.mjs) proxies `/api` to `http://localhost:8080`.

From `frontend/`, run the same frontend checks as CI:

```bash
CI=true npm test
npm run build
```

The build writes `frontend/dist/`. Backend and processor test commands, dependency setup, and container checks are defined in the [CI workflow](.github/workflows/ci.yml). Processor unit tests mock separation subprocesses; they do not validate model downloads or real audio quality.

Full native backend/processor runs are not turnkey: both services use hardcoded `/app/uploads` and `/app/outputs` paths that must be writable and shared. The processor also uses POSIX pseudo-terminals, so use Linux containers rather than a native Windows Python process.

### Make shortcuts

Run these from the repository root after building the images:

| Command | Action |
|---------|--------|
| `make help` | List available targets |
| `make up` / `make down` | Start in the background / stop the stack |
| `make logs` | Follow service logs |
| `make restart` / `make status` | Restart services / show container status |
| `make clean` | Stop services and **delete the audio volumes**; this is destructive |

## Limitations and Data Lifecycle

- **Local, trusted use only.** There is no authentication, TLS termination, or rate limiting. Compose publishes ports 3000 and 8080 on all host interfaces by default and enables Flask debug mode. Do not expose the supplied stack directly to the public internet; restricting CORS is not access control.
- **History is not a backup.** The browser saves metadata in localStorage, while the backend keeps its job map only in memory. A backend restart loses job records and download mappings even if audio files remain in the named volumes. Refresh recovery cannot restore that server state.
- **Files outlive job records.** Successful processing removes the input file, but completed outputs have no automatic expiration. Removing a completed job from browser history or deleting its API record does not delete its audio from disk. Failed jobs can also leave files behind. Monitor disk use; `docker compose down --volumes` or `make clean` permanently deletes the stack's named volumes.
- **Upload limits differ by entry point.** The browser accepts files up to 100 MiB; the Nginx proxy limits the whole multipart request to 100 MiB, including form overhead. Keep files below that boundary. The directly exposed backend does not enforce the same hard request-size cap.
- **CPU processing is workload-dependent.** There is no fixed per-song timing guarantee or managed worker queue. The Demucs subprocess has a 30-minute timeout, and the backend also times out processor requests after 30 minutes. Progress combines parsed model output with a time-based estimate, not a reliable completion forecast.
- **Cancellation is best-effort.** The API requests termination of an active separation subprocess and removes the job record. Cancellation may not stop work before that subprocess is registered or during later FFmpeg conversion/mixing stages.

## Troubleshooting

Inspect status and recent logs first:

```bash
docker compose ps
docker compose logs --tail=100 backend processor
```

| Symptom | What to check |
|---------|---------------|
| Containers fail to start or become healthy | Confirm the container runtime is running (`docker info`), ports 3000/8080 are free, and the build completed. Review service logs before increasing the startup wait timeout. |
| First job is slow | Check processor logs for model downloads and available internet access. Healthy containers do not mean the model is cached. |
| Processing fails or runs out of memory | Try a shorter input, allocate more memory to the container runtime, and leave segment size at Default to avoid model-specific incompatibilities. |
| Upload is rejected | Check the extension, request size, free disk space, and backend logs. A proxy `413` response includes multipart overhead in the limit. |
| Waveform preview fails | The browser may not decode that audio format even when the processor can handle it. Try WAV or MP3. |
| Separation quality is poor | Start from a high-quality source and try another model in the UI. AI separation can leave artifacts or bleed between stems. |
| Old jobs are visible but downloads fail after restart | Browser metadata survived, but the backend's in-memory job map did not. Download results before restarting the backend. |

## Roadmap

These are future directions, **not implemented features**:

- Durable job persistence with PostgreSQL and Valkey.
- User authentication, rate limiting, and a RabbitMQ worker queue.
- Automatic file expiration and cleanup.
- OpenTelemetry/Prometheus/Grafana observability and SeaweedFS object storage.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines and the [CI workflow](.github/workflows/ci.yml) for the current checks. For setup or processing problems, [open an issue](https://github.com/mbianchidev/track2stem/issues) with reproduction steps, runtime/platform details, and relevant logs without private audio or credentials.

## License

Track2stem is licensed under the [MIT License](LICENSE).

## Acknowledgments

Built on [Demucs](https://github.com/facebookresearch/demucs), originally developed by Facebook Research. The upstream repository is archived; refer to its documentation for model details and upstream usage guidance.
