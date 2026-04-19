"""YouTube Ingester Ship Service — FastAPI + yt-dlp + faster-whisper"""

import asyncio
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
import tempfile
import os

# Job store (in-memory, singleton per process)
_jobs: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TranscribeRequest(BaseModel):
    url: str = Field(..., description="YouTube video URL")
    language: str = Field(default="en", description="Transcript language code")
    word_timestamps: bool = Field(default=False, description="Include word-level timestamps")


class JobResponse(BaseModel):
    job_id: str
    status: str  # pending | processing | completed | failed
    url: str
    title: str | None = None
    description: str | None = None
    duration_seconds: float | None = None
    transcript: str | None = None
    word_timestamps: list[dict] | None = None
    speakers: list[str] | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="YouTube Ingester", version="0.1.0")

WORKSPACE = Path(os.environ.get("WORKSPACE", "/workspace"))


# ---------------------------------------------------------------------------
# Background processing
# ---------------------------------------------------------------------------


def _get_faster_whisper():
    """Lazy import to keep startup fast."""
    # pylint: disable=import-outside-toplevel,global-statement
    global _faster_whisper_model
    if _faster_whisper_model is None:
        from faster_whisper import WhisperModel

        _faster_whisper_model = WhisperModel("base", device="auto", compute_type="auto")
    return _faster_whisper_model


_faster_whisper_model = None


async def _run_transcription(job_id: str, url: str, language: str, word_timestamps: bool) -> None:
    """Download audio and transcribe. Updates _jobs in place."""
    job = _jobs[job_id]
    job["status"] = "processing"

    try:
        # --- yt-dlp: download audio-only ---
        import yt_dlp

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "audio.mp3"

            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": str(audio_path.with_suffix(".%(ext)s")),
                "quiet": True,
                "no_warnings": True,
                "extract_audio": True,
                "audio_format": "mp3",
                "noplaylist": True,
            }
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(url, download=True))
            if info is None:
                raise RuntimeError("yt-dlp failed to extract video info")

            # yt-dlp returns a dict; find the actual file
            downloaded = list(Path(tmpdir).glob("audio.*"))
            if not downloaded:
                raise RuntimeError("yt-dlp did not produce an audio file")
            audio_file = downloaded[0]

            job["title"] = info.get("title")
            job["description"] = info.get("description", "")[:500]
            job["duration_seconds"] = info.get("duration") or 0.0

            # --- faster-whisper transcription ---
            model = await asyncio.get_event_loop().run_in_executor(None, _get_faster_whisper)

            if word_timestamps:
                segments, info = model.transcribe(
                    str(audio_file),
                    language=language,
                    word_timestamps=True,
                )
                words = []
                for seg in segments:
                    for w in seg.words:
                        words.append({
                            "word": w.word,
                            "start": w.start,
                            "end": w.end,
                            "probability": w.probability,
                        })
                job["word_timestamps"] = words
                job["transcript"] = " ".join(w["word"] for w in words)
            else:
                result, _ = await loop.run_in_executor(
                    None,
                    lambda: model.transcribe(str(audio_file), language=language)
                )
                job["transcript"] = "\n".join(f"[{seg.start:.1f}s] {seg.text}" for seg in result)

            # Basic speaker count (naive: count distinct turns in word timestamps)
            job["speakers"] = ["Speaker 1"]  # placeholder — diarization is Phase 2

        job["status"] = "completed"

    except Exception as exc:  # pylint: disable=broad-except
        job["status"] = "failed"
        job["error"] = str(exc)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/transcribe", response_model=JobResponse, status_code=202)
async def transcribe(req: TranscribeRequest, background: BackgroundTasks) -> JobResponse:
    job_id = str(uuid.uuid4())
    job: dict[str, Any] = {
        "job_id": job_id,
        "status": "pending",
        "url": req.url,
        "title": None,
        "description": None,
        "duration_seconds": None,
        "transcript": None,
        "word_timestamps": None,
        "speakers": None,
        "error": None,
    }
    _jobs[job_id] = job
    background.add_task(_run_transcription, job_id, req.url, req.language, req.word_timestamps)
    return JobResponse(**job)


@app.get("/job/{job_id}", response_model=JobResponse)
async def get_job(job_id: str) -> JobResponse:
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse(**_jobs[job_id])
