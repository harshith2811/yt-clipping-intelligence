# Phase 2 Architecture: Production-Grade YouTube Clipping Intelligence Platform

## 1. System Overview

Phase 2 transforms the platform into an end-to-end, commercial-quality SaaS Web Studio. The system ingests YouTube videos via a dual-engine architecture, discovers high-yield highlights using `SolidShortsDecider`, generates grounded "Why This Short Works" explainability metrics, synthesizes multi-platform captions with model cascading, renders vertical 9:16 videos with FFmpeg and active speaker face tracking, performs automated media QA verification, and atomically persists sidecar records that survive server restarts.

```
                      +---------------------------------------+
                      |       Operator / SaaS Web Studio       |
                      | (Dark Mode, Range Streaming, Captions) |
                      +-------------------+-------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |         FastAPI Web Studio Server     |
                      |   (/api/v1/metadata, /preview, etc.)  |
                      +-------------------+-------------------+
                                          |
                +-------------------------+-------------------------+
                |                                                   |
                v                                                   v
+-------------------------------+                   +-------------------------------+
|    VideoMetadataService       |                   |       JobManager              |
|  (Data API v3 + yt-dlp)       |                   | (SQLite WAL + Thread Tokens)  |
+---------------+---------------+                   +---------------+---------------+
                |                                                   |
                v                                                   v
+-------------------------------+                   +-------------------------------+
|    SolidShortsDecider         |                   |      Pipeline Worker          |
| (Dynamic Capacity & Spacing)  |                   |  - Candidate Extraction       |
+---------------+---------------+                   |  - Caption & Intelligence     |
                |                                   |  - FFmpeg 9:16 Render         |
                v                                   |  - QA Verification            |
+-------------------------------+                   +---------------+---------------+
|    CaptionSynthesizer         |                                   |
| (Gemini Primary -> Fallback   |                                   v
|  -> Deterministic Offline)    |                   +-------------------------------+
+-------------------------------+                   |      ProjectStore             |
                                                    | (Atomic Sidecars, projects/)  |
                                                    +-------------------------------+
```

---

## 2. Core Subsystems

### 2.1 Dual-Engine Metadata Ingestion (`yt_clipping.discovery.video_metadata`)
- **URL Normalizer:** Supports bare 11-char IDs, `watch?v=`, `youtu.be/`, `shorts/`, `live/`, `embed/`, tracking parameters, and subdomains (`m.youtube.com`). Enforces SSRF defense by rejecting private IPs and non-YouTube hosts.
- **Primary Engine:** YouTube Data API v3 (`videos?part=snippet,contentDetails,statistics`). Extracts title, description, channel title, channel handle, views, likes, comments, duration, category, and tags.
- **Cascading Fallback:** `yt-dlp` metadata-only extraction (`--skip-download`). Automatically engages when API quota is exhausted, key is absent, or connectivity errors occur.
- **Caching:** Atomic disk cache (`data/cache/metadata/<video_id>.json`).

### 2.2 Short Intelligence & Explainability Engine (`yt_clipping.scoring.caption_synthesizer`)
- **Explainable Metrics:**
  - `hook_strength`: First 3-5 seconds capture ability (0-10).
  - `context_completeness`: Standalone story completeness without prior context (0-10).
  - `narrative_quality`: Presence of an identifiable premise, build-up, and payoff (0-10).
  - `information_density`: Words and conceptual progression per second (0-10).
  - `ending_quality`: Clean sentence closure without dangling connectors (0-10).
  - `estimated_engagement_potential`: Calibrated score (0-100) combining composite scorecard with acoustic inflection and replay heatmap peaks.
- **Grounded Selection Reasoning:** Explicitly references specific clip timestamps and transcript excerpt.

### 2.3 AI Caption & Social Content Synthesizer (`yt_clipping.scoring.caption_synthesizer`)
- **Model Cascading:**
  1. `GEMINI_PRIMARY_MODEL` (e.g., `gemini-3.5-flash-lite`)
  2. `GEMINI_FALLBACK_MODEL` (e.g., `gemini-flash-latest`)
  3. `offline_deterministic` (Rule-based synthesis using transcript snippets and tags)
- **Content Package:**
  - `hook_title`: Viral, curiosity-inducing headline without exaggerated clickbait.
  - `core_summary`: 2-3 sentence value explanation.
  - `creator_credit`: Structured attribution with real channel name and canonical URL.
  - `legal_disclaimer`: Copyright awareness notice.
  - `platform_variants`: Formatted outputs tailored for YouTube Shorts, Instagram Reels, and TikTok.

### 2.4 Persistent Storage & Project Store (`yt_clipping.orchestration.project_store`)
- **Hierarchy:**
  ```
  data/projects/project_<video_id>/
      project.json
      clips/
          clip_<job_id>.json (Sidecar metadata)
  data/rendered_clips/
      clip_<job_id>.mp4
      clip_<job_id>.json
  ```
- **Crash Resilience:** All writes use `.tmp.<pid>` and atomic rename (`os.replace`).
- **Reconciliation:** Scans both project directories and legacy clips on application restart.

### 2.5 Background Job Manager (`yt_clipping.orchestration.job_manager`)
- **State Machine:** SQLite table `render_jobs` with WAL mode.
- **Statuses:** `queued` -> `discovering` -> `analyzing` -> `generating_caption` -> `rendering` -> `validating` -> `completed` (or `failed`, `cancelled`).
- **Cancellation:** Supports immediate graceful cancellation via `threading.Event` tokens.

### 2.6 Automated Video Quality Assurance (`yt_clipping.qa.verifier`)
- Evaluates:
  1. Physical existence and file size threshold (>1KB).
  2. SHA-256 integrity hash.
  3. Media container readability via `ffprobe` / `ffmpeg` / `OpenCV`.
  4. Video stream existence.
  5. Audio stream existence.
  6. 9:16 vertical aspect ratio (target ~0.5625).
  7. Duration tolerance matching.
  8. Valid frame rate (15-120 fps).
  9. Frame decodability.
