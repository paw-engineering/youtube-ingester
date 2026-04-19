# YouTube Ingester Ship Service — Design

## Overview
API service that downloads YouTube videos/audio and transcribes them using faster-whisper.

## Endpoints

### POST /transcribe
**Request:**
```json
{
  "url": "https://youtube.com/watch?v=...",
  "language": "en",
  "word_timestamps": false
}
```
**Response (202):**
```json
{
  "job_id": "uuid",
  "status": "pending",
  "url": "..."
}
```

### GET /job/{job_id}
**Response (200):**
```json
{
  "job_id": "uuid",
  "status": "completed",
  "url": "...",
  "title": "Video Title",
  "description": "...",
  "duration_seconds": 3600,
  "transcript": "Full text transcript...",
  "word_timestamps": [...],
  "speakers": ["Speaker 1", "Speaker 2"]
}
```
Statuses: `pending` | `processing` | `completed` | `failed`

## Architecture
- **FastAPI** async service
- **yt-dlp** for media download (audio-only, mp3)
- **faster-whisper** for transcription (GPU-accelerated)
- **In-memory job store** (dict, singleton)
- Docker volume mounts: `~/.openclaw/credentials/` for any future auth needs

## Port
- Default: **7861**
- Registered via `SHIP_SERVICE_YOUTUBE_URL` in ship-services registry

## Docker
- Python 3.11 slim base
- Installs yt-dlp + faster-whisper from PyPI
- Volume: workspace scripts (read-only)
- Non-root user for security

## CI/CD
- GitHub Actions: lint (ruff) → test → build → push to `ghcr.io/paw-engineering/youtube-ingester`
- Trigger: push to `main`
