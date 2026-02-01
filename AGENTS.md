# Track2stem Development Guidelines

## Project Overview
Track2stem is a web application that separates audio tracks into individual stems (vocals, drums, bass, guitar, piano, other) using the Demucs AI model.

## Architecture

### Frontend (React)
- Located in `frontend/`
- Built with Vite + React
- Uses localStorage for job persistence across page refreshes
- Features:
  - Audio file upload with format validation
  - Real-time processing progress with elapsed time
  - Spectrogram visualization for input and output audio
  - Stem download functionality
  - Job history with processing times

### Backend (Go)
- Located in `backend/`
- Built with Go + Gorilla Mux
- Handles file uploads, job management, and proxies to processor
- Jobs are stored in-memory (lost on restart)

### Processor (Python/Flask)
- Located in `processor/`
- Runs Demucs AI model for audio separation
- Uses htdemucs_6s model for 6-stem separation
- Supports MP3 (320kbps) and WAV output formats

## Development Setup
```bash
# Build and run with Docker Compose
make docker-build
make docker-run

# Or use dev compose
docker-compose -f docker-compose.dev.yml up --build
```

## Key Features

### localStorage Persistence
- Jobs, current job, and timer are persisted in localStorage
- Timer continues correctly after page refresh
- Users can manually delete jobs from history

### Spectrogram Visualization
- Input audio shows spectrogram on file selection
- Output stems show spectrograms after processing
- Uses Web Audio API for frequency analysis

### Stem Modes
1. **All 6 Stems**: Outputs vocals, drums, bass, guitar, piano, other
2. **Isolate Mode**: Outputs selected stem + combined backing track

## Future Enhancements

### Parallel Processing (TODO)
For longer audio files (>3 minutes), parallel processing could significantly reduce processing time:

1. Split audio into segments (e.g., 2 minutes each)
2. Process segments in parallel using ThreadPoolExecutor
3. Combine processed segments using ffmpeg concat

Implementation considerations:
- Segment boundaries may cause audio artifacts
- Need crossfade or overlap-add for smooth transitions
- Memory usage increases with parallel workers
- CPU-bound operation limits parallelism benefit without GPU

### Potential Configuration
```python
PARALLEL_ENABLED = os.environ.get('PARALLEL_PROCESSING', 'true')
SEGMENT_DURATION = 120  # seconds
MAX_PARALLEL_WORKERS = 2
```

## Environment Variables

### Backend
- `PORT`: Server port (default: 8080)
- `PROCESSOR_URL`: Processor service URL

### Processor
- `PORT`: Server port (default: 5000)
- `FLASK_DEBUG`: Enable debug mode

## API Endpoints

### Backend
- `POST /api/upload`: Upload audio file for processing
- `GET /api/jobs`: List all jobs
- `GET /api/jobs/{id}`: Get job status
- `GET /api/download/{id}/{stem}`: Download processed stem
- `GET /api/processing-status/{id}`: Get real-time processing progress

### Processor
- `POST /process`: Process audio file
- `GET /status/{job_id}`: Get processing status
- `GET /health`: Health check
