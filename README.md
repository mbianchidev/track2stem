# Track2stem 🎵

A powerful music separator that splits audio files into individual stems (vocals, drums, bass, guitar, piano, and other instruments) using AI-powered source separation.

## Features

- **Multi-format Support**: MP3, WAV, FLAC, OGG, M4A, and AAC
- **AI-Powered Separation**: Uses Facebook Research's Demucs model
- **6-Stem Output**: Vocals, drums, bass, guitar, piano, and other instruments
- **Isolate Mode**: Extract a single stem + combined backing track
- **Real-time Progress**: Live status updates with elapsed time tracking
- **Spectrogram Visualization**: View audio spectrograms for input and output
- **Persistent Job History**: Recent jobs survive page refreshes (localStorage)
- **Individual Downloads**: Download each separated track independently

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
| Frontend | React 18 + Nginx | Modern UI with drag-and-drop upload |
| Backend | Go 1.21 + Gorilla Mux | REST API and job management |
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
| `GET` | `/api/download/{id}/{stem}` | Download separated stem |
| `GET` | `/api/health` | Health check |

### Examples

```bash
# Upload a file
curl -X POST http://localhost:8080/api/upload -F "file=@song.mp3"

# Check job status
curl http://localhost:8080/api/jobs/{job-id}

# Download vocals stem
curl -O http://localhost:8080/api/download/{job-id}/vocals
```

### Response Format

```json
{
  "id": "job-uuid",
  "status": "completed",
  "filename": "song.mp3",
  "created_at": "2024-01-01T00:00:00Z",
  "completed_at": "2024-01-01T00:05:00Z",
  "output_files": {
    "vocals": "/path/to/vocals.wav",
    "drums": "/path/to/drums.wav",
    "bass": "/path/to/bass.wav",
    "guitar": "/path/to/guitar.wav",
    "piano": "/path/to/piano.wav",
    "other": "/path/to/other.wav"
  }
}
```

## Development

### Using Make Commands

```bash
make up        # Start all services
make down      # Stop services
make logs      # View logs
make build     # Rebuild containers
./health-check.sh  # Check service health
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
│   └── main.go
├── frontend/               # React UI
│   ├── src/
│   ├── Dockerfile
│   ├── nginx.conf
│   └── package.json
├── processor/              # Python + Demucs
│   ├── Dockerfile
│   ├── app.py
│   └── requirements.txt
├── docker-compose.yml
├── docker-compose.dev.yml
├── Makefile
└── health-check.sh
```

## Performance

| Metric | Value |
|--------|-------|
| Processing Time | 1-5 min per song |
| Memory Usage | 2-4GB during processing |
| Model Size | ~2GB (downloaded once) |
| Output Format | High-quality WAV |
| Max File Size | 100MB |

## Security

- Filename sanitization (path traversal prevention)
- CORS configuration for controlled access
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