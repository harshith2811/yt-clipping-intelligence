# YouTube Clipping Intelligence Platform

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-blue?logo=python)](https://python.org)
[![Pytest](https://img.shields.io/badge/Tests-439%20Passed-brightgreen?logo=pytest)](docs/COMPREHENSIVE_TEST_REPORT.md)
[![Docker](https://img.shields.io/badge/Docker-24%2F7%20GPU%20Worker-blue?logo=docker)](Dockerfile)
[![Social Publishing](https://img.shields.io/badge/Publishing-OmniPost%20Multi--Channel-purple)](src/yt_clipping/publisher/omnipost.py)
[![MCP](https://img.shields.io/badge/MCP-2024--11--05%20Stdio%20JSON--RPC-purple)](docs/mcp.md)
[![Hardware](https://img.shields.io/badge/Hardware-%E2%89%A44GB%20VRAM%20%7C%20CPU%20Fallback-orange)](docs/RELEASE_READINESS_REPORT.md)
[![Zero Quota](https://img.shields.io/badge/YouTube%20Discovery-Zero%20API%20Quota-red?logo=youtube)](docs/VIRALITY_AND_ATTRIBUTION.md)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-Hardware%20Accelerated-007808?logo=ffmpeg)](https://ffmpeg.org)
[![NVIDIA](https://img.shields.io/badge/GPU-CUDA%20%7C%20NVENC-76B900?logo=nvidia)](https://developer.nvidia.com/video-codec-sdk)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

An enterprise-grade, research-driven autonomous video discovery, audience retention intelligence, and vertical 9:16 clip production engine. Designed for automated multi-platform publishing workflows across YouTube Shorts, TikTok, and Instagram Reels, complete with a native Model Context Protocol (MCP) server for agentic LLM orchestration.

---

## 📖 Table of Contents
- [1. System Architecture](#1-system-architecture)
- [2. Key Capabilities & Innovations](#2-key-capabilities--innovations)
- [3. Hardware Requirements & OS Certification](#3-hardware-requirements--os-certification)
- [4. Quickstart & Installation](#4-quickstart--installation)
- [5. Model Context Protocol (MCP) Server](#5-model-context-protocol-mcp-server)
- [6. CLI Operator Guide](#6-cli-operator-guide)
- [7. Subtitle Presets & Video Layouts](#7-subtitle-presets--video-layouts)
- [8. Project Directory Structure](#8-project-directory-structure)
- [9. Testing & Quality Assurance](#9-testing--quality-assurance)
- [10. Documentation & Technical Specifications](#10-documentation--technical-specifications)
- [11. License & Attribution](#11-license--attribution)

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
                        │ Multi-Engine Speech │                         │
                        │ Faster-Whisper int8 │                         │
                        │ WhisperX Alignment  │                         │
                        │ Pyannote/Acoustic   │                         │
                        │ Speaker Diarization │                         │
                        └──────────┬──────────┘                         │
                                   │ Word Timestamps & Speaker Turns    │
                                   ▼                                    │
                        ┌─────────────────────┐                         │
                        │ Highlight Detection │                         │
                        │ Local Scorecard OR  │                         │
                        │ Gemini Flash Cloud  │                         │
                        │ IoU Deduplicator    │                         │
                        └──────────┬──────────┘                         │
                                   │ Ranked Highlight Candidates        │
                                   ▼                                    │
                        ┌─────────────────────┐                         │
                        │ Dead-Air & Pacing   │                         │
                        │ Pruner (Micro-Cuts) │                         │
                        │ Hook Pacing Polish  │                         │
                        └──────────┬──────────┘                         │
                                   │ Tightened Audio & Remapped Words   │
                                   ▼                                    │
                        ┌─────────────────────┐                         │
                        │ Framing & Smoothing │                         │
                        │ YuNet Face Tracker  │                         │
                        │ AutoFlip Kinematic  │                         │
                        │ Trajectory (SciPy)  │                         │
                        └──────────┬──────────┘                         │
                                   │ Smoothed 9:16 Viewport Path        │
                                   ▼                                    │
                        ┌─────────────────────┐                         │
                        │   FFmpeg Renderer   │ ◄───────────────────────┘
                        │  blur_background    │
                        │  active_speaker     │
                        │  split_screen 9:8   │
                        │  Animated Subtitles │
                        │  Audio Anti-Pop     │
                        │  NVIDIA NVENC / CPU │
                        └──────────┬──────────┘
                                   │ Rendered 1080x1920 MP4
                                   ▼
                        ┌─────────────────────┐
                        │ B-Roll & CTA Engine │
                        │ Monologue Overlays  │
                        │ Animated CTA Pill   │
                        │ Audio Ducking       │
                        └──────────┬──────────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │  Outro Card Engine  │
                        │ (Opt-In Outro MP4)  │
                        │ Animated Subscribe  │
                        │ Soft Zen Bell Chime │
                        └──────────┬──────────┘
                                   │ Final Composited MP4
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

In addition to autonomous pipeline execution, the platform provides a native **Model Context Protocol (MCP)** JSON-RPC 2.0 stdio server, allowing desktop LLMs (Claude Desktop, Cursor) and multi-agent frameworks to directly control ingestion, rights verification, heatmap analysis, candidate scoring, and video rendering.

---

## 2. Key Capabilities & Innovations

### A. Sub-Second Forced Alignment (WhisperX + Faster-Whisper Fallback)
- **High-Precision Monotonic Sync:** Aligns raw transcription words against audio waveforms down to sub-second precision using acoustic wav2vec2 cross-correlation or monotonic interpolation.
- **Fail-Safe Cascading:** Runs phoneme-level forced-alignment when GPU/dependencies exist; gracefully falls back to deterministic monotonic word clamping on resource-constrained CPU environments.

### B. Dual-Mode Speaker Diarization (Pyannote + Acoustic Energy)
- **Zero-VRAM Acoustic Energy Diarizer:** Offline, pure-NumPy/SciPy speaker turn clustering analyzing 16kHz audio frame RMS energy, frequency centroid transitions, and silence gaps—consuming 0MB VRAM.
- **Neural Diarizer Adapter:** Automatic adapter wrapping `pyannote.audio` pipeline with Hugging Face authentication tokens and instant degradation to acoustic energy heuristics.
- **Automated Word Attribution:** Maps word timestamps to speaker turns with temporal overlap thresholds and speaker turn continuity buffers.

### C. Multimodal Cloud Highlight Discovery (Google Gemini Flash)
- **Gemini 1.5 Flash Provider:** Zero local VRAM consumption highlight discovery analyzing transcripts, visual hooks, and heatmap signals via Google's lightweight multimodal model.
- **Strict Guardrail Enforcement:** Enforces minimum/maximum clip durations, complete sentence boundaries, ban on dangling connectors ("and", "so", "but"), and automatic purging of sponsored ad segments.
- **Offline Scorecard Fallback:** Seamless fallback to the local `ExplainableScorecardScorer` when `GEMINI_API_KEY` is not configured or network quotas are exceeded.

### D. Kinematic Camera Trajectory Smoothing (AutoFlip-Inspired)
- **Constrained 1D Trajectory Optimizer:** Eliminates erratic camera panning and micro-jitter in vertical face tracking using a banded SciPy linear system solver ($O(N)$ complexity) or pure-Python kinematic velocity/acceleration limiter.
- **Kinematic Limits:** Enforces configurable maximum pan velocities ($\le 450 \text{ px/s}$), maximum accelerations ($\le 750 \text{ px/s}^2$), and a $24\text{ px}$ deadband threshold to maintain rock-solid holds on stationary subjects.
- **Scene Cut Stabilization:** Detects visual jump cuts ($>35\%$ viewport shifts) and instantly resets camera tracking coordinates to prevent visual whip-pans across edits.

### E. Automated B-Roll Overlay Engine (ShortGPT-Inspired)
- **Monologue Speech Detection:** Identifies continuous speaker monologues exceeding configurable thresholds ($\ge 4.0\text{ s}$) where audience drop-off risk is highest.
- **Fuzzy Stock Asset Matching:** Extracts high-relevance semantic nouns and topic keywords (ignoring conversational filler words) and matches against local stock footage libraries.
- **Dynamic FFmpeg Compositing:** Generates complex filtergraphs featuring smooth $0.25\text{ s}$ alpha cross-fades, vertical 9:16 proportional scaling, and automated primary dialogue audio ducking ($0.4\times$ volume).

### F. Animated Call-to-Action (CTA) Overlay Engine
- **Libass Vector Pill & Banner Animations:** Renders smooth vector rounded-corner call-to-action badges (`m ... b ... c ...`) with `\move` sliding keyframes and `\fad` transparency effects directly in ASS subtitles.
- **Native FFmpeg Fallback:** Builds parameterized `drawbox` and `drawtext` filter chains with duration gating when rendering without subtitles.
- **Mobile Platform Safe-Zones:** Avoids right-hand interaction icons and bottom navigation UI elements across TikTok, Reels, and YouTube Shorts, with dynamic clearance around podcast center dividers.

### G. Broadcast Hook Pacing & Audio Anti-Pop Polish
- **Hook Dead-Air Trimming:** Trims leading silence $>0.15\text{s}$ down to exactly $\text{first\_word.start} - 0.10\text{s}$, eliminating dead pauses while preserving natural breath headroom and opening plosives.
- **Boundary Word Protection:** Prevents clipping spoken syllables mid-word by verifying alignment boundary confidence.
- **Micro-Fade Audio Anti-Pop:** Applies microscopic $20\text{ms}$ half-sine fade-in and $250\text{ms}$ outro fade-out (`afade`) to eliminate digital clicks and audio pops across cuts.
- **Loop Continuity Scoring:** Evaluates semantic similarity between the final payoff and opening hook, providing a $0.0 - 10.0$ loop affinity score.

### H. Pipeline Dead-Air & Filler Pruning
- **Micro-Jump Cut Integration:** Excises silent pauses ($\ge 0.5\text{ s}$) and conversational filler words ("um", "uh", "like") directly during pipeline execution.
- **Deterministic Timestamp Remapping:** Rewrites transcript and subtitle word timestamps to perfectly synchronize with pruned media timelines.

### I. Native Model Context Protocol (MCP) Server
- **Standard-Compliant JSON-RPC 2.0:** Exposes pipeline subsystems over standard I/O (stdio) adhering to the `2024-11-05` MCP protocol specification.
- **7 Discrete Tools:** Exposes `discover_channel_uploads`, `verify_source_rights`, `analyze_replay_heatmap`, `evaluate_highlight_candidates`, `render_vertical_clip`, `inspect_job_status`, and `list_available_tools`.
- **Pure Stderr Isolation:** Restricts diagnostic logging exclusively to `stderr`, guaranteeing clean, machine-parseable JSON-RPC frames on `stdout`.

### J. Autonomous Zero-Quota Pinger & Scraper Daemon
- **Zero API Quota Depletion:** Monitors creator channels using public XML Atom feeds (`/feeds/videos.xml?channel_id={id}`) with HTTP conditional GET (`ETag` and `If-Modified-Since` 304 caching).
- **Early-Hour Velocity Multiplier ($M_v$):**
  $$V_{\text{hourly}} = \frac{\text{Current Views}}{\max(\text{Age in Hours}, 0.25)}, \quad M_v = \frac{V_{\text{hourly}}}{\max(\text{Baseline}/48.0, 10.0)}$$
- **Audience Resonance Gate:** Rejects clickbait and bot views by enforcing Like-to-View Ratio (LVR $\ge 1.2\%$) and Comment-to-View Ratio (CVR $\ge 0.03\%$).

### K. Dedicated Animated Outro Card & Local Sound Synthesis
- **Strictly Opt-In Toggle:** Managed via `RenderProfile(enable_outro_card=False)` and `--enable-outro-card` flag. Default is `False` to maintain existing rendering contracts.
- **Local Mathematical Audio Synthesis:** Generates a mellow, broadcast-grade notification sound using pure Python standard library (`wave`, `struct`, `math`) without external sound packs or cloud audio APIs.
- **`soft_zen` Acoustic Profile:** Pure fundamental C5 (523.25 Hz) with gentle fifth harmonic (G5) and octave decay, 30ms raised-cosine soft attack, targeting approximately -12.5 dB peak amplitude.
- **Broadcast Call-to-Action Animation:** Animated ASS vector subscribe pill with rocking bell icon and optional blurred backdrop sampled from the main video's final frame.

### L. Strategic Gemini Visual Director & Cloudflare FLUX.1 Engine
- **Narrative Pacing & Tension Evaluation:** The Gemini visual director evaluates speech energy, semantic shifts, and subtitle timestamps before intervening—preventing arbitrary prompt injections that disrupt speaker continuity.
- **Stock Footage Re-Use Gate:** Verifies local assets and existing footage to avoid gratuitous AI generations when context is already visually supported.
- **Dynamic 9:16 Ken Burns Cutaways:** Direct composition of photorealistic vertical visual assets generated via `@cf/black-forest-labs/flux-1-schnell` with smooth pan/zoom motion transitions.

### M. Top Trending >10M Channels Autonomous Streamer & 1-Click Publishing
- **Autonomous StreamToClipper:** 1-click execution (`⚡ Stream #1 & Publish`) directly from the Top Trending carousel.
- **End-to-End Clipping & Distribution:** Streams high-velocity trending videos, tracks active speakers with YuNet, generates kinetic captions, and publishes finished 9:16 Shorts directly to YouTube, TikTok, and Instagram Reels.
- **Overnight Multi-Video Batch Scheduler:** Background worker capable of selecting and consecutively processing multi-video batches while maintaining strict memory and GPU locks.

### N. Turnkey Docker Containerization & Render.com Blueprint (`render.yaml`)
- **Single-Container Architecture:** Completely containerized runtime with automated model prebaking (Faster-Whisper, YuNet, YOLOv8) and zero cold-start latency.
- **Render.com Free-Tier Deployment:** Turnkey `render.yaml` specification supporting free cloud hosting with dynamic `$PORT` binding and `/api/v1/health` probes.
- **Automatic Compute Detection:** Dispatches NVIDIA NVENC on CUDA environments with transparent fallback to multi-threaded CPU `libx264` and Int8 Faster-Whisper.

### O. Linear/Figma-Grade Obsidian Web Studio Dashboard
- **Luxury UI/UX Aesthetics:** Floating glass dock navigation with standardized 32px baseline, custom SVG glyphs, and real-time hardware telemetry radar (`Online • GPU Active`).
- **Creator Tooling Suite:** Toggleable Social Media Safe Zones (TikTok, Shorts, Reels), interactive audio waveform canvas, video frame-stepping (±0.05s), virality radar metrics, and poster frame capture.

---

## 3. Hardware Requirements & OS Certification

The platform has been engineered, benchmarked, and certified for rock-solid local execution on resource-constrained consumer hardware:

| Specification | Minimum Requirement | Recommended Production |
| :--- | :--- | :--- |
| **Operating System** | Windows 10 / 11 (64-bit), Linux, macOS | Windows 11 / Ubuntu 22.04 LTS |
| **Python Runtime** | Python 3.10 | Python 3.12 (Fully Certified) |
| **GPU / VRAM** | No GPU required (CPU fallback) | NVIDIA GPU $\le 4\text{GB}$ VRAM (GTX 1650 / RTX 3050) |
| **Video Hardware Acceleration** | Intel QSV / CPU `libx264` | NVIDIA NVENC (`h264_nvenc`) |
| **RAM** | 8 GB RAM | 16 GB RAM |
| **Storage** | 5 GB free disk space | Fast NVMe SSD with WAL SQLite |
| **External API Quota** | Zero required (100% offline autonomy) | Optional Google Gemini API key |

**Hardware & Offline Guarantee:**
Every component requiring deep learning (Whisper transcription, YuNet face tracking, diarization, trajectory smoothing) features an automated fallback to lightweight, offline CPU-based heuristics ensuring zero out-of-memory (OOM) crashes on 4GB VRAM hardware.

---

## 4. Quickstart & Installation

### Prerequisites
- **Python 3.12** (or 3.10+)
- **FFmpeg & ffprobe** installed and accessible on system PATH

### Installation
```bash
# 1. Clone repository
git clone https://github.com/your-org/yt-clipping-intelligence.git
cd yt-clipping-intelligence

# 2. Create virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\Activate.ps1
# On Linux/macOS:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
pip install -e .
```

### Environment Configuration
```bash
cp .env.example .env
```
Edit `.env` to configure your settings (optional):
```dotenv
YOUTUBE_API_KEY=AIzaSy...YourKeyHere      # Optional (RSS polling uses 0 quota)
GEMINI_API_KEY=AIzaSy...YourKeyHere       # Optional (Enables Gemini multimodal scoring)
DEFAULT_LAYOUT_MODE=active_speaker
CRF_QUALITY=22
AUTO_APPROVE_THRESHOLD=65.0
```

### ⚡ Single-Container Turnkey Live Launch (Ready to Play Live)
Run the entire platform inside a single GPU/CPU-accelerated Docker container. The live Web Studio dashboard, REST API, pre-baked AI models, and background rendering engine start immediately on port 8000:

```bash
# Option 1: Docker Compose (Recommended)
docker compose up

# Option 2: Standalone Docker Run
docker build -t yt-clipping-intelligence .
docker run -d --name yt-studio -p 8000:8000 -v ./data:/app/data --gpus all yt-clipping-intelligence

# Access the Live Studio Dashboard in your browser:
# http://localhost:8000
```

### ☁️ Render.com 1-Click Cloud Deployment (Free Tier)
Deploy the single-container Web Studio to Render's free tier with zero manual configuration using the included `render.yaml` blueprint:
1. Connect your repository to [Render.com](https://render.com).
2. Click **New +** → **Blueprint** and select this repo.
3. Render automatically binds the dynamic `$PORT`, applies Int8/libx264 CPU fallback, and connects to `/api/v1/health` probes.

### 🖥️ Native CLI Web Studio Launch
You can also launch the Web Studio directly via the CLI:
```bash
yt-clip studio --host 0.0.0.0 --port 8000
```

---

## 5. Model Context Protocol (MCP) Server

Launch the native stdio JSON-RPC MCP server to interface with AI desktop clients (Claude Desktop, Cursor, local agents):

```bash
# Standard MCP server invocation
python -m yt_clipping.cli.master_cli mcp-server

# Or using the subcommand alias:
python -m yt_clipping.cli.master_cli mcp serve

# Custom storage directories and debug logging:
python -m yt_clipping.cli.master_cli mcp-server --db data/jobs.db --log-level DEBUG
```

### Claude Desktop Integration (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "yt-clipping": {
      "command": "python",
      "args": [
        "-m",
        "yt_clipping.cli.master_cli",
        "mcp-server"
      ],
      "cwd": "C:\\path\\to\\yt-clipping-intelligence"
    }
  }
}
```

See [`docs/mcp.md`](docs/mcp.md) for full technical specification, parameter schemas, and JSON-RPC payloads.

---

## 6. CLI Operator Guide

Detailed instructions are available in [`docs/CLI_REFERENCE.md`](docs/CLI_REFERENCE.md).

### 🚀 Autonomous Channel Sweep & Clipping: `yt-clip autoprobe`
Scan a creator channel, detect viral velocity, register affiliate attribution, select top moments, and render vertical shorts with executive HTML reporting in one command:
```bash
# 1. Sweep channel uploads and evaluate virality in real time
yt-clip autoprobe --channel "@HubermanLab" --max-videos 1

# 2. End-to-end auto-clipping with Hormozi kinetic captions and auto-layout framing:
yt-clip autoprobe --channel "@Veritasium" --render --layout auto --subtitle-preset hormozi

# 3. Autoprobe with Call-to-Action overlay and pacing polish:
yt-clip autoprobe --channel "@Veritasium" --render --enable-cta --cta-text "Follow for more daily facts" --enable-polish
```

### 🎬 Pipeline Run with Advanced Enhancements: `yt-clip run`
```bash
# Full pipeline with Active Speaker face tracking & animated Hormozi subtitles
yt-clip run --video-id rsOiZE19RVo --layout active_speaker --subtitle-preset hormozi --gpu

# Pipeline run with lower-third animated CTA banner
yt-clip run --video-id rsOiZE19RVo --enable-cta --cta-text "Subscribe for Part 2" --cta-style modern_pill

# Pipeline run with dedicated animated outro card and soft zen chime:
yt-clip run --video-id rsOiZE19RVo --enable-outro-card --outro-channel-name "Veritasium"

# Fast preview candidate highlights without rendering
yt-clip preview --video-id rsOiZE19RVo

# Visualize crowd-sourced retention replay curve
yt-clip heatmap --video-id rsOiZE19RVo --visual

# Register content rights manifest in compliance ledger
yt-clip rights register --video-id rsOiZE19RVo --basis OPERATOR_ASSET --owner "Veritasium"
```

### 🎙️ Broadcast Podcast Split-Screen Short Maker: `yt-clip podcast`
```bash
yt-clip podcast --source "data/assets/interview.mp4" --out "data/rendered_clips/podcast_short.mp4" --duration 30.0
```

### 🛰️ Channel Watcher & Background Daemon
```bash
# Add creators to the registry
python channel_watcher.py add @hubermanlab --baseline 150000 --policy OPEN_AFFILIATE

# Run background polling daemon (every 5 minutes)
python pinger_daemon.py --interval 300
```

---

## 7. Subtitle Presets & Video Layouts

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
| `active_speaker` | YuNet face tracking + Constrained Trajectory Smoothing centers speaker in 9:16 viewport. |
| `crop_center` | Proportional 9:16 center crop (`607.5x1080` scaled to `1080x1920`). |
| `split_screen` | Dual 9:8 vertical stack for multi-guest podcast conversations with active speaker attribution. |

---

## 8. Project Directory Structure

```text
yt-clipping-intelligence/
├── pyproject.toml                  # Packaging specification & CLI entrypoints
├── requirements.txt                # Pinned production dependencies
├── pytest.ini                      # Pytest runner configuration
├── Dockerfile                      # Standalone 24/7 container runtime
├── docker-compose.yml              # Multi-mode container orchestration
├── docker-entrypoint.sh            # Container init & service dispatch
├── render.yaml                     # Turnkey Render.com free-tier deployment blueprint
├── LICENSE                         # MIT License
├── README.md                       # Master platform documentation
├── THIRD_PARTY_NOTICES.md          # Upstream research attribution
│
├── top_trending_videos_in_youtube/ # Top Trending >10M subscriber channels streamer & autonomous clipper
│   ├── fetcher.py                  # High-velocity video discovery & caching
│   ├── streamer.py                 # In-process & REST stream-to-clipper engine
│   └── test_trending.py            # Automated streamer test harness
│
├── channel_watcher.py              # CLI: Creator registry & live scan sweeps
├── pinger_daemon.py                # Daemon: Autonomous RSS & WebSub pinger
├── trend_scorer.py                 # CLI: Standalone velocity & virality scoring
├── attribution_engine.py           # CLI: Formatted creator attribution packages
│
├── docs/                           # Technical Specifications & Documentation
│   ├── README.md                   # Documentation master portal
│   ├── SYSTEM_MENTAL_MAP.md        # Architecture mental models & traceability matrix
│   ├── ARCHITECTURE.md             # System architecture & component topology
│   ├── PODCAST_ENGINE.md           # 9:8 Stacked split-screen & diarization engine
│   ├── mcp.md                      # Model Context Protocol (MCP) specification
│   ├── CLI_REFERENCE.md            # Complete CLI operator reference handbook
│   ├── MODULE_REFERENCE.md         # Exhaustive Python module, class & API reference
│   ├── RELEASE_READINESS_REPORT.md # Formal release certification & feature freeze
│   ├── COMPREHENSIVE_TEST_REPORT.md# Exhaustive 410-test execution telemetry report
│   ├── ACTIVE_SPEAKER_AND_CAPTIONS.md # Face tracking & ASS subtitle styling
│   ├── VIRALITY_AND_ATTRIBUTION.md # Virality math, resonance gate, and licensing
│   ├── adr/                        # Architecture Decision Records
│   └── research/                   # Repository intelligence & research matrices
│
├── data/                           # Runtime data storage
│   └── .gitkeep                    # Canonical directory placeholder
│
├── src/yt_clipping/                # Core modular Python package
│   ├── audio/                      # Voiceover & TTS synthesis (`tts_engine.py`)
│   ├── cli/                        # Master CLI entry points (`master_cli.py`)
│   ├── contracts/                  # Typed dataclasses (`models.py`) & interfaces (`interfaces.py`)
│   ├── detection/                  # Arc detector (`arc_detector.py`), dead-air pruner (`deadair.py`), viability, segmenter, IoU
│   ├── discovery/                  # Pinger daemon, Heatmap analyzer, Outlier multiplier, Quota governor
│   ├── ingestion/                  # yt-dlp downloader & stream probe (`asset_provider.py`)
│   ├── mcp/                        # Native MCP JSON-RPC 2.0 stdio server (`server.py`)
│   ├── orchestration/              # Resumable pipeline (`pipeline.py`), SQLite WAL journal, queue, storage
│   ├── podcast/                    # 9:8 split-screen, diarization (`diarization.py`), shot detector
│   ├── publisher/                  # Autopost webhook & watched folder publisher (`adapter.py`)
│   ├── qa/                         # Media quality verifier (`verifier.py`: SAR 1:1, DAR 9:16, decodability)
│   ├── rendering/                  # FFmpeg renderer, trajectory optimizer, B-roll engine (`b_roll.py`), CTA engine (`cta_overlay.py`), Outro card (`outro_card.py`)
│   ├── reporting/                  # Executive HTML diagnostic reports (`html_report.py`)
│   ├── rights/                     # Hard RightsPolicyGate & license audit ledger (`gate.py`)
│   ├── scoring/                    # Multi-signal scorecard (`scorecard.py`), packaging linter, Gemini provider
│   └── transcription/              # Faster-Whisper transcriber & WhisperX alignment (`alignment.py`)
│
└── tests/                          # Automated Pytest Suite (428 test cases)
    ├── test_active_speaker_framer.py
    ├── test_adversarial_broll_pipeline.py
    ├── test_adversarial_gemini.py
    ├── test_adversarial_m1.py
    ├── test_adversarial_m2.py
    ├── test_alignment.py
    ├── test_arc_detector.py
    ├── test_audio_energy.py
    ├── test_b_roll_engine.py
    ├── test_cli_and_preview.py
    ├── test_cta_overlay.py
    ├── test_dead_air_pruner.py
    ├── test_diarization.py
    ├── test_gemini_provider.py
    ├── test_heatmap_analysis.py
    ├── test_local_autonomy.py
    ├── test_mcp_server.py
    ├── test_outlier_multiplier.py
    ├── test_outro_card.py
    ├── test_omnipost_publisher.py
    ├── test_docker_and_prebake.py
    ├── test_pacing_polish.py
    ├── test_packaging_linter.py
    ├── test_pinger_and_virality_scraper.py
    ├── test_pipeline_deadair_broll.py
    ├── test_podcast_engine.py
    ├── test_trajectory_optimizer.py
    └── ... (439 tests total)
```

---

## 9. 24/7 Cloud Worker Deployment (Docker & GPU Ready)

Deploy the autonomous clipping engine 24/7 on GPU cloud servers (RunPod, Lambda Labs, AWS EC2 g4dn/g5, GCP T4/A100) or headless Linux nodes.

### 🐳 Key Container Features:
- **NVIDIA CUDA 12.4 + NVENC**: Full hardware-accelerated video decoding, active-speaker facial tracking, and 60fps vertical H.264 rendering.
- **100% Pre-Baked AI Models**: Pre-bakes Faster-Whisper (`base` and `small`), OpenCV YuNet, and Ultralytics YOLOv8 segmentation weights during Docker build—zero cold-start lag or runtime download failures.
- **Durable Persistent Storage**: Binds `./data` volume preserving SQLite jobs ledger (`jobs.db`), rights policy, and rendered MP4 artifacts across container restarts.
- **Auto-Healing Daemon**: Managed by `docker-entrypoint.sh` with graceful signal handling (`SIGTERM`, `SIGINT`) and Docker healthcheck probes (`python -m yt_clipping doctor`).

### 🚀 1-Click Launch with Docker Compose:

```bash
# Standard Launch (CPU / Auto Fallback)
docker compose up -d --build

# Dedicated Cloud GPU Server Launch (NVIDIA Hardware Acceleration)
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build

# Inspect 24/7 Daemon Logs
docker compose logs -f clipping-daemon

# Run MCP Server Container
docker compose run --rm -p 8000:8000 clipping-daemon mcp
```

---

## 10. Direct Social Media Publishing (OmniPost Integration)

Seamlessly distribute rendered vertical shorts to **YouTube Shorts**, **Instagram Reels**, **Facebook Reels**, and **LinkedIn** via the integrated OmniPost adapter:

```bash
# Clip and deliver directly to OmniPost publishing engine
yt-clip run --video-id rsOiZE19RVo \
  --enable-outro-card \
  --outro-channel-name "Veritasium" \
  --autopost-mode omnipost \
  --omnipost-url "http://localhost:3300" \
  --omnipost-key "YOUR_SECRET_KEY" \
  --omnipost-platforms "youtube,instagram,facebook"

# Dry-run simulate publishing without posting
yt-clip run --video-id rsOiZE19RVo --autopost-mode omnipost --dry-run
```

---

## 11. Testing & Quality Assurance

Run the comprehensive test suite:
```bash
pytest
```

**Quality Assurance Metrics:**
- **439 Passing Tests:** 100% pass rate across functional baseline, unit, integration, stress, and adversarial suites (439 passed, 0 failed, 0 xfailed, 0 skipped out of 439 collected items).
- **Strict Regression Invariance:** All baseline tests maintain complete functional parity with full local autonomy.
- **Hardware Boundary Verification:** Full test execution verified locally on Windows, Python 3.12, CUDA active, $\le 4\text{GB}$ VRAM constraints with automated CPU fallbacks.

---

## 12. Documentation & Technical Specifications

- [**System Mental Map & Reference Architecture**](docs/SYSTEM_MENTAL_MAP.md)
- [**Documentation Portal (Master Index)**](docs/README.md)
- [**System Architecture & Subsystems**](docs/ARCHITECTURE.md)
- [**Podcast Split-Screen Short Maker Engine**](docs/PODCAST_ENGINE.md)
- [**Model Context Protocol (MCP) Server Specification**](docs/mcp.md)
- [**CLI Operator Reference Guide**](docs/CLI_REFERENCE.md)
- [**Exhaustive Module & API Reference**](docs/MODULE_REFERENCE.md)
- [**Comprehensive Test & Adversarial Verification Report**](docs/COMPREHENSIVE_TEST_REPORT.md)
- [**Formal Release Readiness Report**](docs/RELEASE_READINESS_REPORT.md)
- [**Virality Scorer, Early-Hour Velocity & Attribution**](docs/VIRALITY_AND_ATTRIBUTION.md)
- [**Active Speaker Face Tracking & Subtitles**](docs/ACTIVE_SPEAKER_AND_CAPTIONS.md)

---

## 11. License & Attribution

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for terms.
All upstream algorithm inspirations, research foundations, and external references are formally credited in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
