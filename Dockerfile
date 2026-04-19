FROM python:3.11-slim

WORKDIR /app

# Install system deps for yt-dlp / faster-whisper
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Non-root user
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1
EXPOSE 7861

CMD ["uvicorn", "src.service:app", "--host", "0.0.0.0", "--port", "7861"]
