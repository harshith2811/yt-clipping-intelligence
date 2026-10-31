# YouTube Clipping Intelligence Platform

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-blue?logo=python)](https://python.org)
[![Pytest](https://img.shields.io/badge/Tests-84%20Passed%20(100%25)-brightgreen?logo=pytest)](https://pytest.org)
[![Zero Quota](https://img.shields.io/badge/YouTube%20Discovery-Zero%20API%20Quota-red?logo=youtube)](docs/VIRALITY_AND_ATTRIBUTION.md)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-Hardware%20Accelerated-007808?logo=ffmpeg)](https://ffmpeg.org)
[![NVIDIA](https://img.shields.io/badge/GPU-CUDA%20%7C%20NVENC-76B900?logo=nvidia)](https://developer.nvidia.com/video-codec-sdk)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

An enterprise-grade, research-driven autonomous video discovery, audience retention intelligence, and vertical 9:16 clip production engine. Designed for automated multi-platform publishing workflows across YouTube Shorts, TikTok, and Instagram Reels.

---

## 📖 Table of Contents
- [1. System Architecture](#1-system-architecture)
- [2. Key Capabilities & Innovations](#2-key-capabilities--innovations)
- [3. Quickstart & Installation](#3-quickstart--installation)
- [4. CLI Operator Guide](#4-cli-operator-guide)
- [5. Subtitle Presets & Video Layouts](#5-subtitle-presets--video-layouts)
- [6. Project Directory Structure](#6-project-directory-structure)
- [7. Testing & Quality Assurance](#7-testing--quality-assurance)
- [8. Documentation & Technical Specifications](#8-documentation--technical-specifications)
- [9. License & Attribution](#9-license--attribution)

---

## 1. System Architecture

```text
                             [ YouTube Ingestion Layer ]
                                          │
            ┌─────────────────────────────┼─────────────────────────────┐
            ▼                             ▼                             ▼
  [ Creator RSS Feeds ]        [ YouTube Data API v3 ]      [ yt-dlp Video / Audio ]
   (Zero-Quota Polling)       (Trending Charts, Comments)      (1080p60 Source Ingest)
            │                             │                             │
            ▼                             ▼                             │
  ┌───────────────────┐         ┌───────────────────┐                   │
  │   PingerDaemon    │         │  HeatmapAnalyzer  │                   │
  │  Hourly Velocity  │         │ 100-Point Replay  │                   │
  │  Baseline Multi   │         │ Prominence Peaks  │                   │
  │  Resonance Gate   │         │ Sentence Snapping │                   │
  └─────────┬─────────┘         └─────────┬─────────┘                   │
            │                             │                             │
            └──────────────────────┬──────┘                             │
                                   ▼                                    │
                        ┌─────────────────────┐                         │
                        │   RightsPolicyGate  │                         │
                        │ (Hard Access Gate)  │                         │
                        └──────────┬──────────┘                         │
                                   │ [VERIFIED Status Only]             │
                                   ▼                                    │
                        ┌─────────────────────┐                         │
                        │   LocalTranscriber  │                         │
                        │   (Faster-Whisper)  │                         │
                        └──────────┬──────────┘                         │
                                   │ Word Timestamps                    │
                                   ▼                                    │
                        ┌─────────────────────┐                         │
                        │ Highlight Detector  │                         │
                        │ & IoU Deduplicator  │                         │
                        └──────────┬──────────┘                         │
                                   │ Candidate Moments                  │
                                   ▼                                    │
                        ┌─────────────────────┐                         │
                        │ Explainable Scorer  │                         │
                        │ Hook (25%)          │                         │
                        │ Heatmap Peak (25%)  │                         │
                        │ Payoff & Cadence    │                         │
                        └──────────┬──────────┘                         │
                                   │ Ranked Highlight                   │
                                   ▼                                    │
                        ┌─────────────────────┐                         │
                        │ ActiveSpeakerFramer │                         │
                        │ (YuNet Face Tracker)│                         │
                        └──────────┬──────────┘                         │
                                   │ Smoothed 9:16 Coordinates          │
                                   ▼                                    │
                        ┌─────────────────────┐                         │
                        │   FFmpeg Renderer   │ ◄───────────────────────┘
                        │  blur_background    │
                        │  active_speaker     │
                        │  Animated Subtitles │
                        │  NVIDIA NVENC GPU   │
                        └──────────┬──────────┘
                                   │ Rendered 1080x1920 MP4
                                   ▼
                        ┌─────────────────────┐
                        │ QualityVerifier(QA) │
                        │ Streams, SAR 1:1    │
                        │ Bitrate & Checksum  │
                        └──────────┬──────────┘
                                   │ PASSED
                                   ▼
                        ┌─────────────────────┐
                        │  Autopost Publisher │
                        │  Watched Folder     │
                        │  REST Webhook       │
                        └─────────────────────┘
```

---

## 2. Key Capabilities & Innovations

### A. Autonomous Zero-Quota Pinger & Scraper Daemon ([`docs/VIRALITY_AND_ATTRIBUTION.md`](docs/VIRALITY_AND_ATTRIBUTION.md))
- **Zero API Quota Depletion:** Monitors creator channels using public XML Atom feeds (`/feeds/videos.xml?channel_id={id}`) with HTTP conditional GET (`ETag` and `If-Modified-Since` 304 caching).
- **WebSub Push Notifications:** Embedded W3C WebSub HTTP push listener receiving sub-second upload alerts directly from YouTube hubs.
- **Early-Hour Velocity Multiplier ($M_v$):**
  $$V_{\text{hourly}} = \frac{\text{Current Views}}{\max(\text{Age in Hours}, 0.25)}, \quad M_v = \frac{V_{\text{hourly}}}{\max(\text{Baseline}/48.0, 10.0)}$$
- **Audience Resonance Gate:** Rejects clickbait and bot views by enforcing Like-to-View Ratio (LVR $\ge 1.2\%$) and Comment-to-View Ratio (CVR $\ge 0.03\%$).

### B. Creator Attribution & Legal Compliance Engine
- **Automated Caption Attribution:** Generates platform-compliant primary credit (`Original Content by: @handle`), canonical source links (`https://youtu.be/...`), and educational fair-use disclosures.
- **Sponsor & Ad Copy Purge:** Detects and removes paid sponsor endorsements (NordVPN, Displate, BetterHelp, AG1) from transcripts and descriptions.
- **Creator Rights Governance:** Manages licensing policies (`OPEN_AFFILIATE`, `CREATIVE_COMMONS`, `PARTNER_PROGRAM`, `STRICT_COPYRIGHT`) and quarantines strict copyright holders.

### C. AI Active Speaker Face Tracking ([`docs/ACTIVE_SPEAKER_AND_CAPTIONS.md`](docs/ACTIVE_SPEAKER_AND_CAPTIONS.md))
- **Deep CNN Face Detection:** OpenCV YuNet with Haar cascade fallback dynamically centers subjects in vertical 9:16 portrait video.
- **Exponential Moving Average (EMA, $\alpha=0.20$):** Smooths natural body motion while instantly resetting on camera angle cuts to prevent drifting.

### D. Audience Retention Heatmap Intelligence ([`src/yt_clipping/discovery/heatmap.py`](src/yt_clipping/discovery/heatmap.py))
- **Tiered Telemetry Ingestion:** Extracts raw 100-segment YouTube replay curves, with fallback to comment-timestamp Gaussian Kernel Density Estimation (KDE).
- **Topological Prominence Peak Detection:** Eliminates flat plateau false positives by walking valley boundaries ($P_i = y_i - \max(m_{\text{left}}, m_{\text{right}})$).

### E. Hardware-Accelerated 9:16 Video Rendering ([`src/yt_clipping/rendering/renderer.py`](src/yt_clipping/rendering/renderer.py))
- **Layouts:** `blur_background` (OpusClip/TikTok style), `active_speaker` (dynamic face tracking), `crop_center`, and `split_screen` (podcasts).
- **GPU Acceleration:** NVIDIA NVENC (`h264_nvenc`) with constant quality rate control (`-cq 22`), seamlessly falling back to CPU `libx264`.

---

## 3. Quickstart & Installation

### Prerequisites
- **Python 3.10+** (Tested on Python 3.12)
- **FFmpeg & ffprobe** on system PATH

### Installation
```bash
# 1. Clone repository
git clone https://github.com/your-org/yt-clipping-intelligence.git
cd yt-clipping-intelligence

# 2. Set up virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
pip install -e .
```

### Environment Configuration
```bash
cp .env.example .env
```
Edit `.env` to configure your API keys (optional for zero-quota RSS polling):
```dotenv
YOUTUBE_API_KEY=AIzaSy...YourKeyHere
DEFAULT_LAYOUT_MODE=blur_background
CRF_QUALITY=22
AUTO_APPROVE_THRESHOLD=65.0
```

---

## 4. CLI Operator Guide

Detailed instructions are available in [`docs/CLI_REFERENCE.md`](docs/CLI_REFERENCE.md).

### 1. Monitor Channels & Detect New Uploads
```bash
# Add creators by handle or channel ID
python channel_watcher.py add @hubermanlab --baseline 150000 --policy OPEN_AFFILIATE
python channel_watcher.py add @GoogleDevelopers --baseline 20000 --policy OPEN_AFFILIATE

# List tracked creators
python channel_watcher.py list

# Run immediate live zero-quota discovery sweep
python channel_watcher.py scan
```

### 2. Run Autonomous Background Pinger Daemon
```bash
# Run continuous polling daemon (checks every 5 minutes)
python pinger_daemon.py --interval 300

# Run single sweep for cron execution
python pinger_daemon.py --cycles 1
```

### 3. Render 9:16 Vertical Video (Master CLI)
```bash
# Full pipeline run with Active Speaker face tracking & animated Hormozi subtitles
yt-clip run --video-id rsOiZE19RVo --layout active_speaker --preset hormozi --gpu

# Fast preview candidate highlights without rendering
yt-clip preview --video-id rsOiZE19RVo

# Visualize crowd-sourced retention replay curve
yt-clip heatmap --video-id rsOiZE19RVo --visual
```

---

## 5. Subtitle Presets & Video Layouts

### Subtitle Styles ([`docs/ACTIVE_SPEAKER_AND_CAPTIONS.md`](docs/ACTIVE_SPEAKER_AND_CAPTIONS.md))
- **`hormozi`** *(Default)*: Bold yellow uppercase text with heavy black borders and pop active-word highlights.
- **`beast_bounce`**: High-contrast lime green with subtle active word bounce.
- **`neon_cyber`**: Cyan glow with magenta drop shadow.
- **`karaoke_gold`**: Elegant golden progressive fill for podcast narratives.
- **`bold_social`**: Clean, high-legibility minimalist white with dark shadow.

### Video Layouts
| Layout Mode | Description |
| :--- | :--- |
| `blur_background` | Fits complete 16:9 widescreen frame with a matching Gaussian-blurred backdrop. Zero cropping. |
| `active_speaker` | YuNet face tracking centers the speaker smoothly across the 9:16 vertical viewport. |
| `crop_center` | Proportional 9:16 center crop (`607.5x1080` scaled to `1080x1920`). |
| `split_screen` | Dual 9:8 vertical stack for multi-guest podcast conversations. |

---

## 6. Project Directory Structure

```text
yt-clipping-intelligence/
├── .env.example                    # Environment variable template
├── .gitignore                      # Git ignore rules for media, databases, caches
├── pyproject.toml                  # Packaging specification & CLI entrypoints
├── pytest.ini                      # Pytest runner configuration
├── requirements.txt                # Pinned production dependencies
├── LICENSE                         # MIT License
├── README.md                       # Platform documentation
├── THIRD_PARTY_NOTICES.md          # Upstream research attribution
│
├── channel_watcher.py              # CLI: Creator registry & live scan sweeps
├── pinger_daemon.py                # Daemon: Autonomous RSS & WebSub pinger
├── trend_scorer.py                 # Engine: Virality velocity & resonance scorer
├── attribution_engine.py           # Engine: Creator attribution & sponsor purge
│
├── docs/                           # Architecture, CLI guides, and research
│   ├── ARCHITECTURE.md             # High-level architecture & SQLite schema
│   ├── CLI_REFERENCE.md            # Complete CLI operator handbook
│   ├── VIRALITY_AND_ATTRIBUTION.md # Virality math, resonance gate, and policies
│   ├── ACTIVE_SPEAKER_AND_CAPTIONS.md # Face tracking & ASS subtitle engine
│   ├── adr/                        # Architecture Decision Records (ADRs)
│   └── research/                   # Provenance logs & master research briefs
│
├── src/yt_clipping/                # Core modular Python package
│   ├── audio/                      # Edge-TTS voice generation & audio mastering
│   ├── cli/                        # Master CLI (`yt-clip`) entrypoints
│   ├── contracts/                  # Data models, dataclasses, and interfaces
│   ├── detection/                  # Sentence snapping & IoU deduplication
│   ├── discovery/                  # Pinger, TrendScorer, Heatmap, Attribution
│   ├── ingestion/                  # Asset ingestion & ffprobe container analysis
│   ├── orchestration/              # State machine, JobQueue, and SQLite WAL ledger
│   ├── publisher/                  # Autopost webhook & watched-folder adapters
│   ├── qa/                         # Stream decodability & SAR 1:1 validation
│   ├── rendering/                  # FFmpegRenderer, ActiveSpeakerFramer, Captions
│   ├── rights/                     # Hard RightsPolicyGate & license audit ledger
│   ├── scoring/                    # ExplainableScorecardScorer & Hook Analyzer
│   └── transcription/              # LocalTranscriber with Faster-Whisper
│
└── tests/                          # Comprehensive Pytest Suite (84 tests)
    ├── test_active_speaker_framer.py
    ├── test_autopost_adapter.py
    ├── test_cli_and_preview.py
    ├── test_contracts.py
    ├── test_daemon_and_registry.py
    ├── test_deduplication.py
    ├── test_discovery_ranker.py
    ├── test_end_to_end_vertical_slice.py
    ├── test_heatmap_analysis.py
    ├── test_metadata_generator.py
    ├── test_pinger_and_virality_scraper.py
    ├── test_qa_verifier.py
    ├── test_queue.py
    ├── test_real_media_pipeline.py
    ├── test_rendering_and_captions.py
    ├── test_rights_gate.py
    ├── test_scoring.py
    ├── test_state_machine_recovery.py
    ├── test_storage_manager.py
    ├── test_timestamp_math.py
    ├── test_trend_analysis.py
    └── test_tts_and_subject_tracking.py
```

---

## 7. Testing & Quality Assurance

Run the complete 84-test test suite:
```bash
pytest -v
```

All 84 tests pass with a 100% pass rate:
- ✅ **Decodability & Quality Assurance:** Stream container decodability, SAR 1:1, and DAR 9:16.
- ✅ **Timestamp Arithmetic:** 100% deterministic ASS centisecond carry calculations.
- ✅ **Temporal IoU Suppression:** Rejection of overlapping highlight candidates.
- ✅ **Zero-Quota Polling:** Atom XML feed parsing and HTTP 304 ETag caching.
- ✅ **Velocity Multipliers:** Statistical early-hour view velocity and classification math.
- ✅ **Attribution & Compliance:** Creator rights governance and sponsor ad copy purging.
- ✅ **State Machine Resilience:** SQLite WAL crash recovery and idempotency locks.

---

## 8. Documentation & Technical Specifications
- [**System Architecture & Schema**](docs/ARCHITECTURE.md)
- [**CLI Operator Reference Guide**](docs/CLI_REFERENCE.md)
- [**Virality Scorer, Early-Hour Velocity & Attribution**](docs/VIRALITY_AND_ATTRIBUTION.md)
- [**Active Speaker Face Tracking & Subtitles**](docs/ACTIVE_SPEAKER_AND_CAPTIONS.md)
- [**Architecture Decision Records (ADRs)**](docs/adr/)
- [**Upstream Research & Provenance**](docs/research/)

---

## 9. License & Attribution

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for terms.
All upstream algorithm inspirations, research foundations, and external references are formally credited in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
