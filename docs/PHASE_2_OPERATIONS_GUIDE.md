# Phase 2 Operations & Deployment Guide

This guide details deployment, environment variable configuration, storage conventions, rendering optimization, and troubleshooting for the YouTube Clipping Intelligence Platform.

---

## 1. Quickstart & Deployment

### 1.1 Local Development Server
To launch the interactive studio locally:

```powershell
# Activate your Python virtual environment
python -m yt_clipping.web.server
```

Or via CLI:
```powershell
yt-clipping studio --host 0.0.0.0 --port 8000
```

The Web Studio is immediately accessible at: `http://localhost:8000/`

### 1.2 Docker Container Deployment
The application is pre-configured to run as a single container serving port 8000:

```bash
docker build -t yt-clipping-intelligence:latest .
docker run -p 8000:8000 -v $(pwd)/data:/app/data --env-file .env yt-clipping-intelligence:latest
```

Using Docker Compose:
```bash
docker compose up -d studio
```

---

## 2. Environment Configuration

Copy `.env.example` to `.env` and configure your credentials:

```bash
# YouTube Data API v3 (Primary metadata extraction engine)
YOUTUBE_API_KEY=your_youtube_api_key_here

# Google Gemini Flash (Primary multimodal & social caption engine)
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_PRIMARY_MODEL=gemini-3.5-flash-lite
GEMINI_FALLBACK_MODEL=gemini-flash-latest

# Storage & Directory Roots
DATA_DIR=data
ASSETS_DIR=data/assets
OUTPUT_DIR=data/rendered_clips
TEMP_DIR=data/temp
DB_PATH=data/jobs.db

# Processing Defaults
DEFAULT_LAYOUT_MODE=active_speaker
DEFAULT_SUBTITLE_PRESET=hormozi
CRF_QUALITY=22
```

---

## 3. Persistent Storage Conventions

Data is organized under `data/`:

```
data/
  cache/
    metadata/           # Cached YouTube video metadata (<video_id>.json)
  heatmaps/             # Audience retention curves & replay peak cache
  projects/
    project_<video_id>/ # Persistent project root
      project.json      # Project descriptor
      clips/
        clip_<id>.json  # Clip sidecar with intelligence & captions
  rendered_clips/       # Vertical MP4 output files & mirrored sidecars
  transcripts/          # Cached speech transcripts
  jobs.db               # SQLite database (WAL mode) tracking jobs & rights
```

### Crash Recovery
If the server is restarted while rendering:
1. `JobManager` inspects `render_jobs` in SQLite.
2. Interrupted jobs are marked failed with an informative message.
3. Previously rendered clips and project sidecars remain intact.

---

## 4. Hardware Acceleration & Rendering Presets

The studio provides two video encoding pipelines:
- **NVIDIA NVENC (`h264_nvenc`):** Requires an NVIDIA GPU with drivers and CUDA support. Offers ultra-fast hardware-accelerated encoding (~10x real-time).
- **libx264 (CPU Fallback):** Used automatically when GPU acceleration is unavailable or disabled. Provides maximum codec compatibility and consistent visual quality.

Framing Presets:
1. `active_speaker`: YuNet facial gimbal tracking following the speaker with smooth exponential easing.
2. `blur_background`: Centers the 16:9 frame on a 9:16 blurred, darkened canvas.
3. `split_screen`: Stacks two participants vertically (ideal for podcast conversations).

---

## 5. Troubleshooting & FAQ

**Q: What happens if YouTube Data API quota is exceeded?**  
The platform automatically detects the quota error (`403 quotaExceeded`) and seamlessly cascades to `yt-dlp` metadata-only extraction without interrupting the user.

**Q: What happens if the Gemini API key is missing or invalid?**  
The synthesizer automatically cascades to the deterministic offline generator, producing structured creator attribution, hashtags, summaries, and platform variants from transcript excerpts.

**Q: Why does the video player support instant scrubbing/seeking?**  
The `/api/v1/clips/{clip_id}/media` endpoint implements HTTP Range requests (`206 Partial Content`), allowing browsers to request specific byte ranges on-the-fly.
