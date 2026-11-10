# Configuration and operations

[Documentation index](README.md) | [Usage](usage.md) | [Troubleshooting](troubleshooting.md)

## Runtime requirements

Follow the [quickstart](../README.md#quickstart) for the source-based Compose installation. It runs Linux containers, including on macOS or Windows hosts with a compatible runtime. No GPU is required or configured: the processor installs CPU-only PyTorch and disables CUDA.

Start with at least 8 GB of RAM available to the container runtime and several GB of free disk space for images, weights, inputs, and outputs. Requirements vary by model, track length, output format, and concurrent work; these are starting recommendations, not measured minimums or performance guarantees.

## Service configuration

| Setting | Service | Default / supplied Compose value |
|---------|---------|----------------------------------|
| `PORT` | Backend | `8080` |
| `PROCESSOR_URL` | Backend | Compose sets `http://processor:5000` |
| `ALLOWED_ORIGINS` | Backend | `*` when unset; accepts a comma-separated list of browser origins |
| `PORT` | Processor | `5000` |
| `FLASK_DEBUG` | Processor | `false` when unset, but **`true` in the supplied Compose file** |
| `VITE_API_URL` | Frontend | `/api`; read by Vite at development-server startup or build time |
| `UPLOAD_FOLDER` | Backend / processor | `/app/uploads`; shared writable upload root |
| `OUTPUT_FOLDER` | Backend / processor | `/app/outputs`; shared writable output root |
| `MODEL_FOLDER` | Processor | `/app/models`; named `model-cache` volume in Compose |
| `TRACK2STEM_OFFLINE` | Engine | Set to `1` to require already-cached auxiliary models |
| `TRACK2STEM_FFMPEG` | Engine | `ffmpeg`; an absolute executable can be injected by a packaged host |
| `TRACK2STEM_NODE` | YouTube importer | Node.js executable override; otherwise yt-dlp discovers `node` |
| `TRACK2STEM_LYRICS_MODEL` | Lyrics | `large-v3-turbo`; `small` and `base` select lighter, less accurate local CPU alternatives |

The Compose file hardcodes service environment values and port mappings. It does not interpolate [.env.example](../.env.example), so copying that example to `.env` alone does **not** reconfigure the stack. Change the relevant `environment` entries and port mappings in [docker-compose.yml](../docker-compose.yml), then recreate affected services.

Keep internal ports and the configured service URLs consistent if changing them. For non-Compose runs, set `PROCESSOR_URL` explicitly: processing otherwise defaults to `http://localhost:5000`, while progress and cancellation default to `http://processor:5000`.

The frontend reads `VITE_API_URL`, not the legacy `REACT_APP_API_URL` in the example file. Set it before starting Vite or building the frontend. Setting it on an already-running Nginx container does not change compiled assets. The supplied frontend Dockerfile does not expose a build argument for this setting.

## Network exposure

| Service | Compose host access | Purpose |
|---------|---------------------|---------|
| Frontend | `http://localhost:3000` | Web UI; Nginx forwards `/api` to the backend |
| Backend | `http://localhost:8080/api` | Direct API access |
| Processor | No published host port | Internal Compose service on port 5000 |

Compose publishes the web and API ports on all host interfaces by default. To restrict them to IPv4 loopback, change the corresponding mappings to `"127.0.0.1:3000:80"` and `"127.0.0.1:8080:8080"`, then recreate those services.

The stack has no authentication, TLS termination, or rate limiting, and its Compose configuration enables Flask debug mode. It is intended for trusted local use, not direct public-internet exposure. Restricting CORS is not access control.

## Model downloads

Demucs downloads the selected model when it is first used, not when containers become healthy. Internet access is required for uncached weights; download size and processing time depend on the model.

Compose persists model downloads in the `model-cache` volume. The engine retains one selected Demucs model in memory; switching models releases that cache entry. Auxiliary CPU models are downloaded only for enabled features: Spotify Basic Pitch for pitched transcription, Beat This small0 for beat/downbeat tracking, Whisper large-v3-turbo for lyrics, ADT_STR for full-kit drum transcription, and UVR MDX-NET KARA 2 for lead/backing vocal splitting. ONNX, beat and drum downloads have pinned SHA-256 checksums. Download failures are explicit errors; local audio is never uploaded to a model service.

Beat This small0 is about 8 MB and its authors explicitly license code and published weights under MIT. ADT_STR's checkpoint is about 289 MB. Its adapted CPU implementation runs as a separate process over a JSON/file interface and retains **CC-BY-SA-4.0**, including attribution and ShareAlike obligations for distributed adaptations. It does not import the Flask service or require the original training stack. Its source and notices accompany native packages. See [Beat This](https://github.com/CPJKU/beat_this#license) and the [drum component's terms and provenance](../processor/drum_transcriber/LICENSE).

The default lyrics model needs a substantially larger first-use download (about 1.6 GB) and more CPU/RAM than Whisper base. `TRACK2STEM_LYRICS_MODEL=small` or `base` retains a lighter option. Singing is not passed through speech-only VAD, which can discard sustained words. Very low-confidence/no-speech segments are explicitly excluded; transcriptions still need review.

Weights are not committed or redistributed with Track2stem and remain subject to their upstream terms. Basic Pitch is Apache-2.0; Whisper and Demucs have their own upstream licenses. The public UVR model download does not provide a clear model-specific redistribution license. Verify permission before redistributing or commercially deploying those weights; this repository's MIT license does not relicense third-party models. See the [Basic Pitch source](https://github.com/spotify/basic-pitch), [Whisper source](https://github.com/openai/whisper), and [UVR model source](https://github.com/TRvlvr/model_repo).

Health endpoints confirm availability, not that a model is cached or inference works. Offline operation requires provisioning every selected model beforehand; uncached YouTube videos still require network access.

## Start, inspect, and stop

Run from the repository root:

```bash
docker compose up -d --wait --wait-timeout 300
docker compose ps
curl --fail http://localhost:8080/api/health
./scripts/health-check.sh
docker compose logs --tail=100 backend processor
docker compose down
```

Stopping with `docker compose down` preserves the named audio volumes. It still stops the backend and loses its in-memory job records.

| Make shortcut | Action |
|---------------|--------|
| `make help` | List available targets |
| `make up` / `make down` | Start in the background / stop the stack |
| `make logs` | Follow service logs |
| `make restart` / `make status` | Restart services / show container status |
| `make clean` | Stop services and **delete the named audio volumes** |

## Limitations and data lifecycle

- **History is not a backup.** Browser localStorage contains metadata, not the audio or a durable server job database. Backend restarts lose job records and download mappings even if files remain in volumes.
- **Files outlive job records.** Successful processing removes its owned input. Internal lossless stems and completed outputs have no automatic expiration. Removing history or deleting an API record does not remove output audio. Failed/cancelled engine jobs clean their owned output directory.
- **Uploads are bounded.** Individual files are limited to 100 MiB. Nginx, Go and Flask allow 101 MiB for the multipart request, including overhead. Decoded audio is limited to 60 minutes.
- **CPU time varies.** A process-local engine serializes jobs so they do not compete for model memory. Each job can use 1-4 segment workers. This is not a durable/distributed queue. The Go adapter times out a processing request after 30 minutes.
- **Cancellation is cooperative.** Events are checked while queued, between separation/model windows, and during FFmpeg operations. An in-flight neural-network segment must finish before the engine can clean up; download/model-loading operations can delay cancellation.

Download needed stems before restarting the backend. Monitor disk use and back up audio separately if it must be retained.

**Destructive reset:** `docker compose down --volumes` and `make clean` permanently remove the stack's `uploads`, `outputs` and `model-cache` named volumes. Use them only after saving any required files. They are not routine shutdown commands.
