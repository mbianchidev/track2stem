# Track2stem 🎵

A powerful music separator that splits audio files into individual stems (vocals, drums, bass, guitar, piano, and other instruments) using AI-powered source separation.

## Features

- **Multi-format Support**: MP3, WAV, FLAC, OGG, M4A, and AAC input
- **Multiple Output Formats**: MP3 (default), WAV, and FLAC
- **AI-Powered Separation**: Uses Facebook Research's Demucs with multiple model options
- **6-Stem Output**: Vocals, drums, bass, guitar, piano, and other instruments (with htdemucs_6s)
- **4-Stem Output**: Vocals, drums, bass, and other (with htdemucs, mdx, and other models)
- **Isolate Mode**: Extract a single stem + combined backing track
- **Advanced Options**: Configurable model, shifts, segment size, overlap, and clip mode
- **Real-time Progress**: Live status updates with elapsed time tracking
- **Spectrogram Visualization**: View audio spectrograms for input and output
- **Persistent Job History**: Recent jobs survive page refreshes (localStorage)
- **Individual Downloads**: Download each separated track independently
- **Job Cancellation**: Cancel in-progress jobs and delete completed ones

## Quick Start

### Prerequisites

- Docker and Docker Compose
- At least 8GB RAM recommended
- 5GB free disk space for models

### Installation

```bash
git clone https://github.com/mbianchidev/track2stem.git
cd track2stem
docker-compose up --build
```

Access the application:
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8080

> **Note**: On first run, Demucs downloads ~2GB of pre-trained models. This is a one-time operation.

### Usage

1. Open http://localhost:3000
2. Upload an audio file (drag-and-drop or click to select)
3. Wait for processing (1-5 minutes depending on song length)
4. Download individual stems

## Architecture

A 3-tier Docker Compose application:

| Service | Technology | Purpose |
|---------|------------|---------|
| Frontend | React 19 + Nginx | Modern UI with drag-and-drop upload |
| Backend | Go 1.25 + Gorilla Mux | REST API and job management |
| Processor | Python 3.13 + Demucs 4.0.1 | AI-powered audio separation |

### How It Works

1. User uploads audio file → Frontend
2. Frontend sends file → Backend API
3. Backend creates job, forwards to → Processor
4. Processor runs Demucs separation
5. Backend updates job status to "completed"
6. User downloads individual stems

## API Reference

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/upload` | Upload audio file for processing |
| `GET` | `/api/jobs` | List all jobs |
| `GET` | `/api/jobs/{id}` | Get specific job status |
| `DELETE` | `/api/jobs/{id}` | Cancel/delete a job |
| `GET` | `/api/download/{id}/{stem}` | Download separated stem |
| `GET` | `/api/processing-status/{id}` | Get real-time processing progress |
| `GET` | `/api/health` | Health check |

### Examples

```bash
# Upload a file (with default options)
curl -X POST http://localhost:8080/api/upload -F "file=@song.mp3"

# Upload with advanced options
curl -X POST http://localhost:8080/api/upload \
  -F "file=@song.mp3" \
  -F "output_format=flac" \
  -F "model=htdemucs_6s" \
  -F "stem_mode=isolate" \
  -F "isolate_stem=vocals"

# Check job status
curl http://localhost:8080/api/jobs/{job-id}

# Get real-time processing progress
curl http://localhost:8080/api/processing-status/{job-id}

# Download vocals stem
curl -O http://localhost:8080/api/download/{job-id}/vocals

# Cancel/delete a job
curl -X DELETE http://localhost:8080/api/jobs/{job-id}
```

### Response Format

```json
{
  "id": "job-uuid",
  "status": "completed",
  "filename": "song.mp3",
  "created_at": "2024-01-01T00:00:00Z",
  "completed_at": "2024-01-01T00:05:00Z",
  "processing_time": "3m 24s",
  "output_format": "mp3",
  "model": "htdemucs_6s",
  "stem_mode": "all",
  "output_files": {
    "vocals": "/app/outputs/job-uuid/vocals.mp3",
    "drums": "/app/outputs/job-uuid/drums.mp3",
    "bass": "/app/outputs/job-uuid/bass.mp3",
    "guitar": "/app/outputs/job-uuid/guitar.mp3",
    "piano": "/app/outputs/job-uuid/piano.mp3",
    "other": "/app/outputs/job-uuid/other.mp3"
  }
}
```

## Development

### Using Make Commands

```bash
make help      # Show all available commands
make build     # Build all Docker images
make up        # Start all services (detached)
make down      # Stop services
make dev       # Start services with logs (foreground)
make logs      # View logs
make restart   # Restart all services
make status    # Show container status
make clean     # Remove containers, volumes, and images
```

### Health Check

```bash
./scripts/health-check.sh  # Check service health
```

### Running Services Individually

**Backend (Go)**
```bash
cd backend && go mod download && go run main.go
```

**Frontend (React)**
```bash
cd frontend && npm install && npm start
```

**Processor (Python)**
```bash
cd processor && pip install -r requirements.txt && python app.py
```

## Project Structure

```
track2stem/
├── backend/                # Go API service
│   ├── Dockerfile
│   ├── go.mod
│   ├── main.go
│   └── main_test.go
├── frontend/               # React UI
│   ├── src/
│   ├── public/
│   ├── Dockerfile
│   ├── nginx.conf
│   └── package.json
├── processor/              # Python + Demucs
│   ├── Dockerfile
│   ├── app.py
│   ├── requirements.txt
│   ├── conftest.py
│   └── test_app.py
├── scripts/
│   └── health-check.sh
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── codeql.yml
├── docker-compose.yml
├── Makefile
├── .env.example
├── CONTRIBUTING.md
└── LICENSE
```

## Performance

| Metric | Value |
|--------|-------|
| Processing Time | 1-5 min per song |
| Memory Usage | 2-4GB during processing |
| Model Size | ~2GB (downloaded once) |
| Output Formats | MP3 (default), WAV, FLAC |
| Max File Size | 100MB |

## Security

- Filename sanitization (path traversal prevention)
- Job ID validation (regex pattern enforcement)
- Input validation against allowlists (output format, stem mode, model, clip mode)
- Safe path joining to prevent directory traversal
- CORS configuration for controlled access (configurable via `ALLOWED_ORIGINS`)
- Client and server-side file type validation
- 30-minute processing timeout
- Secure file handling via werkzeug

## Troubleshooting

### Services won't start
```bash
docker info              # Ensure Docker is running
lsof -i :3000,8080,5000  # Check port availability
docker compose logs      # Review logs
docker compose build --no-cache  # Rebuild
```

### First run is slow
Normal behavior—Demucs downloads ~2GB of models on first run.

### Out of memory
- Increase Docker memory limit to 8GB+
- Process shorter audio files

### Poor audio quality
- Use high-quality input (WAV/FLAC > MP3)
- Try different Demucs models in `processor/app.py`

### Upload fails
- Verify format: mp3, wav, flac, ogg, m4a, aac
- Check file size < 100MB
- Check disk space and backend logs

## Roadmap

- [ ] PostgreSQL/Redis for job persistence
- [ ] User authentication (JWT)
- [ ] Job queue with workers (RabbitMQ)
- [ ] Rate limiting
- [ ] File expiration and cleanup
- [ ] Metrics (Prometheus/Grafana)
- [ ] Object storage (S3/MinIO)
- [ ] Desktop app (Tauri)

## References

- [Demucs](https://github.com/facebookresearch/demucs) - Facebook Research's music source separation
- [Spleeter](https://github.com/deezer/spleeter) - Deezer's source separation library

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

See [LICENSE](LICENSE) file for details.

## Acknowledgments

- Facebook Research for the Demucs audio separation model