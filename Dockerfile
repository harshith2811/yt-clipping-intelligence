# ==============================================================================
# YouTube Clipping Intelligence Platform - 24/7 Production GPU Cloud Worker
# Base: NVIDIA CUDA 12.4.1 Runtime on Ubuntu 22.04
# Supports: NVIDIA NVENC Hardware Video Encoding, CUDA PyTorch 12.4, Faster-Whisper,
#           OpenCV YuNet Face Tracking, and Ultralytics YOLOv8 Segmentation
# ==============================================================================

FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

# Operational environment variables
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    WHISPER_DOWNLOAD_ROOT=/app/models/whisper \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility,video

# Install system runtime dependencies: Python 3, FFmpeg with libass, fonts, and OpenCV libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-dev \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libfontconfig1 \
    fonts-dejavu-core \
    fonts-liberation \
    fontconfig \
    curl \
    ca-certificates \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Symlink python3 to python
RUN ln -sf /usr/bin/python3 /usr/bin/python

# Workspace setup
WORKDIR /app

# Upgrade pip and install build tools
RUN pip install --upgrade pip setuptools wheel

# Copy dependency specifications first to leverage Docker layer caching
COPY requirements.txt pyproject.toml ./

# Install PyTorch with CUDA 12.4, followed by platform requirements
RUN pip install --index-url https://download.pytorch.org/whl/cu124 \
    torch torchvision torchaudio && \
    pip install -r requirements.txt

# Copy source code, documentation, models, and CLI scripts
COPY src/ src/
COPY models/ models/
COPY docs/ docs/
COPY channel_watcher.py pinger_daemon.py trend_scorer.py attribution_engine.py ./
COPY LICENSE README.md THIRD_PARTY_NOTICES.md ./

# Install package in editable mode for global CLI binary registration
RUN pip install -e .

# Pre-bake & verify all AI models (Faster-Whisper base & small, YuNet, YOLOv8)
RUN python -m yt_clipping.scripts.prebake_models

# Copy and configure multi-mode 24/7 entrypoint
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN sed -i 's/\r$//' /app/docker-entrypoint.sh && chmod +x /app/docker-entrypoint.sh

# Create durable storage volume mount points and bidirectional symlink
RUN mkdir -p /app/data /app/data/rendered_clips /app/data/assets /app/data/assets/flux /app/data/transcripts /app/data/heatmaps /app/data/handoffs /app/data/temp
RUN ln -sfn /app/data/rendered_clips /app/clips
VOLUME ["/app/data", "/app/clips"]

# Expose ports: 8000 (Interactive Live Web Studio Dashboard & REST API), 8088 (WebSub push alert listener)
EXPOSE 8000 8088

# Healthcheck probe verifying platform integrity
HEALTHCHECK --interval=60s --timeout=15s --start-period=30s --retries=3 \
    CMD python -m yt_clipping doctor || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Default command: Turnkey Live Web Studio Dashboard ready to play on live
CMD ["studio"]
