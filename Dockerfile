# YouTube Clipping Intelligence Platform - Container Definition
FROM python:3.12-slim-bookworm

# Set operational environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system runtime dependencies: FFmpeg, ffprobe, and OpenCV requirements
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set up application workspace
WORKDIR /app

# Copy dependency specifications first to leverage Docker layer caching
COPY requirements.txt pyproject.toml ./

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy platform source and documentation
COPY src/ src/
COPY docs/ docs/
COPY channel_watcher.py pinger_daemon.py trend_scorer.py attribution_engine.py ./
COPY LICENSE README.md THIRD_PARTY_NOTICES.md ./

# Install package in editable mode for global CLI binary registration
RUN pip install -e .

# Create volume mount directory for durable media, database, and logs
RUN mkdir -p /app/data && chown -R 1000:1000 /app/data
VOLUME ["/app/data"]

# Expose port for optional WebSub push alert listener
EXPOSE 8088

# Default command: Run autonomous discovery pinger daemon
CMD ["python", "pinger_daemon.py", "--interval", "300"]
