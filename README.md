# Track2stem 🎵

Turn any track into multi-stem with track2stem - a powerful music separator that splits audio files into individual stems (vocals, drums, bass, guitar, piano, and other instruments).

## Features

- **Multi-format Support**: Upload MP3, WAV, FLAC, OGG, M4A, and AAC files
- **AI-Powered Separation**: Uses Demucs for high-quality audio separation
- **6-Stem Output**: Get separate tracks for vocals, drums, bass, guitar, piano, and other instruments
- **Isolate Mode**: Extract a single stem (e.g., vocals) + combined backing track
- **Modern Architecture**: Docker Compose app with Go backend and React frontend
- **Real-time Progress**: Track your jobs with live status updates and elapsed time
- **Spectrogram Visualization**: View audio spectrograms for input and output files
- **Persistent Job History**: Recent jobs survive page refreshes (stored in localStorage)
- **Processing Time Tracking**: See how long each job took to complete
- **Download Individual Stems**: Download each separated track independently

## Architecture

- **Frontend**: React + modern UI
- **Backend**: Golang REST API
- **Processor**: Python + Demucs (Facebook Research)
- **Deployment**: Docker Compose

## Quick Start

### Prerequisites

- Docker and Docker Compose
- At least 8GB RAM recommended
- 5GB free disk space for models

### Running the Application

1. Clone the repository:
```bash
git clone https://github.com/mbianchidev/track2stem.git
cd track2stem
```

2. Start all services with Docker Compose:
```bash
docker-compose up --build
```

3. Access the application:
   - Frontend: http://localhost:3000
   - Backend API: http://localhost:8080

### First Run Note

On the first run, Demucs will download pre-trained models (~2GB). This is a one-time operation that may take several minutes depending on your internet connection.

## Usage

1. Open your browser to http://localhost:3000
2. Click "Choose File" and select an audio file (mp3, wav, flac, etc.)
3. Click "Upload & Process"
4. Wait for the processing to complete (typically 1-5 minutes per song)
5. Download individual stems (vocals, drums, bass, guitar, piano, other)

## API Endpoints

### Upload Audio File
```bash
POST /api/upload
Content-Type: multipart/form-data
Body: file (audio file)

Response: {
  "id": "job-uuid",
  "status": "pending",
  "filename": "song.mp3",
  "created_at": "2024-01-01T00:00:00Z"
}
```

### Get Job Status
```bash
GET /api/jobs/{id}

Response: {
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

### Download Stem
```bash
GET /api/download/{job_id}/{stem}
stem: vocals | drums | bass | guitar | piano | other

Response: Audio file (WAV format)
```

### List All Jobs
```bash
GET /api/jobs

Response: [
  { "id": "...", "status": "...", ... }
]
```

## Development

### Backend (Golang)

```bash
cd backend
go mod download
go run main.go
```

### Frontend (React)

```bash
cd frontend
npm install
npm start
```

### Processor (Python)

```bash
cd processor
pip install -r requirements.txt
python app.py
```

## Technology Stack

- **Frontend**: React 18, Axios, CSS3
- **Backend**: Go 1.21, Gorilla Mux
- **Audio Processing**: Python 3.10, Demucs 4.0, Flask
- **Containerization**: Docker, Docker Compose
- **Audio Library**: FFmpeg

## References

This project leverages state-of-the-art audio separation technology:

1. [Demucs](https://github.com/facebookresearch/demucs) - Facebook Research's music source separation model
2. [Spleeter](https://github.com/deezer/spleeter) - Deezer's source separation library
3. [Audio Separation Research](https://github.com/set-soft/AudioSeparation)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

See LICENSE file for details.

## Acknowledgments

- Demucs by Facebook Research for the audio separation model
- The open-source audio processing community

## Troubleshooting

### Services won't start

**Problem**: Docker containers fail to start

**Solutions**:
- Ensure Docker is running: `docker info`
- Check port availability: `lsof -i :3000,8080,5000` (on Unix)
- Review logs: `docker compose logs`
- Try rebuilding: `docker compose build --no-cache`

### First run is slow

**Problem**: Initial processing takes a very long time

**Solution**: This is normal! On first run, Demucs downloads ~2GB of pre-trained models. Subsequent runs will be much faster.

### Out of memory errors

**Problem**: Container crashes with memory errors

**Solutions**:
- Increase Docker memory limit (8GB recommended)
- Process shorter audio files
- Reduce concurrent jobs

### Audio quality issues

**Problem**: Separated stems have artifacts or poor quality

**Solutions**:
- Use high-quality input files (WAV/FLAC preferred over MP3)
- Ensure input file isn't corrupted
- Try different Demucs models by modifying `processor/app.py`

### Upload fails

**Problem**: File upload returns an error

**Solutions**:
- Check file format is supported (mp3, wav, flac, ogg, m4a, aac)
- Verify file size is under 100MB
- Check disk space on host machine
- Review backend logs: `docker compose logs backend`

### Can't access frontend

**Problem**: Browser can't connect to http://localhost:3000

**Solutions**:
- Verify frontend container is running: `docker compose ps`
- Check for port conflicts: `lsof -i :3000`
- Review frontend logs: `docker compose logs frontend`
- Wait a minute - frontend may still be building

### Backend API errors

**Problem**: API requests fail

**Solutions**:
- Verify backend is healthy: `curl http://localhost:8080/api/health`
- Check backend logs: `docker compose logs backend`
- Ensure processor is running: `docker compose ps processor`

For more issues, please check our [GitHub Issues](https://github.com/mbianchidev/track2stem/issues) page.
