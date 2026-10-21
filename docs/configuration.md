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

The model cache is not mounted in a named volume. It can survive a stop/start of the same container, but recreating the processor container can require another download. Health endpoints confirm availability, not that a model is cached or inference works.

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
- **Files outlive job records.** Successful processing removes its input, but completed outputs have no automatic expiration. Removing a completed job from browser history or deleting its API record does not remove output audio. Failed jobs can also leave files behind.
- **Upload limits differ.** The browser accepts files up to 100 MiB; Nginx caps the whole multipart request at 100 MiB, including overhead. The directly exposed backend does not enforce the same hard request-size cap.
- **CPU time varies.** There is no fixed per-song timing guarantee or managed worker queue. The Demucs subprocess has a 30-minute timeout, and the backend also times out processor requests after 30 minutes.
- **Cancellation is best-effort.** The API requests subprocess termination and removes the job record. Work may continue before subprocess registration or during later FFmpeg conversion/mixing.

Download needed stems before restarting the backend. Monitor disk use and back up audio separately if it must be retained.

**Destructive reset:** `docker compose down --volumes` and `make clean` permanently remove the stack's `uploads` and `outputs` named volumes. Use them only after saving any required files. They are not routine shutdown commands.
