#!/usr/bin/env bash
set -e

# ==============================================================================
# YouTube Clipping Intelligence Platform - Container Entrypoint
# Initializes storage directories, handles OS signals, and dispatches service modes
# ==============================================================================

# Ensure durable volume storage directories exist
mkdir -p /app/data/assets \
         /app/data/assets/flux \
         /app/data/heatmaps \
         /app/data/transcripts \
         /app/data/rendered_clips \
         /app/data/handoffs \
         /app/data/temp

# Handle volume mount synchronization for /app/clips and /app/data/rendered_clips
if [ -d /app/clips ] && [ ! -L /app/clips ] && grep -q " /app/clips " /proc/mounts 2>/dev/null; then
  # Dedicated volume mounted at /app/clips; link rendered_clips into it
  if [ ! -L /app/data/rendered_clips ]; then
    rmdir /app/data/rendered_clips 2>/dev/null || true
    if [ ! -d /app/data/rendered_clips ]; then
      ln -sfn /app/clips /app/data/rendered_clips
    fi
  fi
elif [ ! -e /app/clips ] || [ ! -L /app/clips ]; then
  # Ensure /app/clips symlinks directly to /app/data/rendered_clips
  rmdir /app/clips 2>/dev/null || true
  if [ ! -d /app/clips ]; then
    ln -sfn /app/data/rendered_clips /app/clips
  fi
fi

MODE="${1:-studio}"

echo "================================================================================"
echo " YouTube Clipping Intelligence Platform - Turnkey Live Production Container"
echo " Time: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo " Mode: ${MODE}"
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n1 || echo "NVIDIA CUDA GPU")
  echo " Hardware: ${GPU_NAME} (NVENC & CUDA acceleration enabled)"
  export USE_GPU="${USE_GPU:-1}"
else
  echo " Hardware: Standard Multi-Threaded CPU (Int8 Whisper & libx264 fallback)"
  export USE_GPU="${USE_GPU:-0}"
fi
echo "================================================================================"

# Trap termination signals for graceful container shutdown
trap 'echo "Received termination signal. Shutting down worker gracefully..."; exit 0' SIGTERM SIGINT

case "$MODE" in
  studio|live)
    echo "[*] Launching Turnkey Web Studio Dashboard & REST API on http://0.0.0.0:${PORT:-8000}..."
    exec python -m yt_clipping studio --host 0.0.0.0 --port "${PORT:-8000}"
    ;;
  daemon)
    echo "[*] Launching 24/7 Autonomous Discovery & Clipping Daemon..."
    POLL_INTERVAL="${POLL_INTERVAL:-300}"
    exec python -m yt_clipping daemon --interval "${POLL_INTERVAL}"
    ;;
  worker)
    echo "[*] Launching 24/7 Durable Job Queue Worker..."
    DB_PATH="${DB_PATH:-/app/data/jobs.db}"
    POLL_INTERVAL="${POLL_INTERVAL:-5.0}"
    exec python -m yt_clipping queue worker --db "${DB_PATH}" --poll-interval "${POLL_INTERVAL}"
    ;;
  mcp)
    echo "[*] Launching Model Context Protocol (MCP) Server..."
    exec python -m yt_clipping mcp-server
    ;;
  doctor|config|cleanup|channels|quota|ingest|rights|autoprobe|run|tts|jobs|preview|discovery|heatmap|trends|podcast|batch)
    echo "[*] Executing CLI command: yt-clip $@"
    exec python -m yt_clipping "$@"
    ;;
  *)
    # Arbitrary command (e.g. bash, sh, pytest, python script)
    exec "$@"
    ;;
esac
