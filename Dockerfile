# VerbaShake production image (Hetzner VPS, 2026-10-28). Built and run by
# docker-compose.yml next to this file; Caddy in front terminates HTTPS.
FROM python:3.11-slim

# packages.txt (ffmpeg) is what Streamlit Cloud installs via apt -- same here.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch first: sentence-transformers would otherwise pull the CUDA
# build (several GB) that a GPU-less VPS can't use anyway.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Model downloads (Whisper, MiniLM, NLTK) and runtime caches land under
# /app/.cache, /app/audio_cache, /app/logs -- mounted as volumes in
# docker-compose.yml so they survive rebuilds instead of re-downloading.
ENV HF_HOME=/app/.cache/hf \
    NLTK_DATA=/app/.cache/nltk_data \
    PYTHONUNBUFFERED=1

EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
