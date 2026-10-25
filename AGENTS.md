# Track2stem development guidelines

Read the [development guide](docs/development.md) for architecture, toolchains, native-development constraints, and test scope. User-facing behavior and configuration are documented in [docs/](docs/README.md).

## Repository map

- `frontend/`: React with Vite, browser localStorage metadata, upload settings, progress polling, waveforms, and stem downloads.
- `backend/`: Go with Gorilla Mux, in-memory job management, uploads, processor requests, and downloads.
- `processor/`: Python/Flask with Demucs and FFmpeg. The default `htdemucs_6s` model produces vocals, drums, bass, guitar, piano, and other.
- `scripts/health-check.sh`: Compose service availability check.

## Setup and checks

Use Node.js 26.12.1, Go 1.27.3, and Python 3.14.9, matching containers and CI.

From the repository root:

```bash
docker compose config --quiet
docker compose build --no-cache
docker compose up -d --wait --wait-timeout 300
./scripts/health-check.sh
```

From `frontend/`:

```bash
npm ci
CI=true npm test
npm run build
```

From `backend/`:

```bash
go mod download
go mod verify
go build ./...
go test -race -timeout=5m ./...
```

For processor validation tests, use the isolated setup and command in the [processor test guide](docs/development.md#processor-tests). Native processor execution requires POSIX pseudo-terminals and shared writable `/app` paths.

## Behavioral invariants

- Browser localStorage preserves job metadata and timer state after refresh, not server jobs or audio. Backend jobs are lost on restart.
- The component named `Spectrogram` draws amplitude waveforms through the Web Audio API.
- All-stems mode produces six stems with `htdemucs_6s` or four with the other supported models. Isolate mode mixes the remaining stems into `instrumental` for vocals, or `backing` otherwise.
- Output formats are MP3 at 320 kbps, WAV, and FLAC.
- The supplied processor is CPU-only. Application-level segment splitting and parallel workers remain [future work](docs/roadmap.md#parallel-separation).

## Change guidelines

- Follow existing components, handlers, validation allowlists, filename sanitization, and safe-path helpers.
- Before upgrading processor Python, complete the [Python upgrade gate](docs/development.md#python-upgrade-gate). Require compatible stable CPU wheels, full installation, and real inference evidence; Flask tests and startup health alone are insufficient.
- Preserve type safety where applicable; report errors clearly and clean up owned resources.
- Use synthetic fixtures only. Never include private audio, credentials, or customer data in tests or screenshots.
- Run focused checks and update affected docs. Health checks and current processor validation tests do not prove model inference succeeds.
- Avoid destructive volume cleanup: `make clean` and `docker compose down --volumes` delete stored audio.
- Respect the existing MIT license and contribution workflow in [CONTRIBUTING.md](CONTRIBUTING.md).
