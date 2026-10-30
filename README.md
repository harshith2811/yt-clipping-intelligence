# YouTube Clipping Intelligence Platform

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-blue?logo=python)](https://python.org)
[![Pytest](https://img.shields.io/badge/Tests-47%20Passed-brightgreen?logo=pytest)](https://pytest.org)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-Hardware%20Accelerated-007808?logo=ffmpeg)](https://ffmpeg.org)
[![NVIDIA](https://img.shields.io/badge/GPU-NVENC%20h264__nvenc-76B900?logo=nvidia)](https://developer.nvidia.com/video-codec-sdk)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

A research-driven, modular, rights-aware video discovery, audience retention heatmap intelligence, and vertical clip production engine built for automated publishing workflows.

---

## 1. System Architecture

```text
                             [ YouTube Ingestion Layer ]
                                          │
            ┌─────────────────────────────┼─────────────────────────────┐
            ▼                             ▼                             ▼
  [ Creator RSS Feeds ]        [ YouTube Data API v3 ]      [ yt-dlp Video / Audio ]
   (Quota-free Polling)       (Trending Charts, Comments)      (1080p60 Source Ingest)
            │                             │                             │
            ▼                             ▼                             │
  ┌───────────────────┐         ┌───────────────────┐                   │
  │   TrendAnalyzer   │         │  HeatmapAnalyzer  │                   │
  │ View Velocity (V) │         │ 100-Point Replay  │                   │
  │ Baseline Multi (M)│         │ Prominence Peaks  │                   │
  │ Virality Index    │         │ Sentence Snapping │                   │
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
                        │   FFmpeg Renderer   │ ◄───────────────────────┘
                        │  blur_background    │
                        │  crop_center        │
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

## 2. Core Modules & Innovations

### A. Audience Retention Heatmap Intelligence (`src/yt_clipping/discovery/heatmap.py`)
- **Tiered Telemetry Ingestion**:
  1. *Primary*: Extracts YouTube's raw 100-segment `heatmap` array directly from player response metadata.
  2. *Fallback 1 (Comment Timestamp Mining)*: If heatmaps are unavailable (new uploads, livestreams, or 429 rate limits), queries YouTube Data API v3 `commentThreads.list`, extracts timestamp tokens (`12:34`), weights them by comment likes, and applies Gaussian Kernel Density Estimation (KDE) to reconstruct crowd-sourced retention curves.
  3. *Fallback 2 (Speech & Cadence Curve)*: Synthesizes a baseline engagement curve from speech cadence (140–180 WPM) and exclamation patterns.
- **Topological Prominence Peak Detection**: Walks left/right to find surrounding baseline valleys, eliminating flat plateau false positives ($P_i = y_i - \max(m_{\text{left}}, m_{\text{right}})$).
- **Sentence Boundary Snapping**: Aligns peak windows to natural speech start and punchline endings (25s–55s target).
- **Terminal ASCII Sparklines**: Renders instant terminal waveforms for CLI operators.

### B. Macro Trend & Virality Engine (`src/yt_clipping/discovery/trend_analyzer.py`)
- **Hourly View Velocity**: $V = \frac{\Delta\text{Views}}{\Delta\text{Hours}}$.
- **Channel Baseline Normalization ($M$)**: Compares velocity against the creator's historical 30-day baseline ($M = V / V_{\text{baseline}}$).
- **Audience Resonance Ratios**: Like-to-View Ratio (LVR) and Comment-to-View Ratio (CVR).
- **Composite Virality Index (CVI)**: Calibrated 0–100 index predicting breakout viral potential.
- **YouTube Trending Chart Ingestion**: Polls official trending charts across regions and categories using 1 API quota unit.

### C. Hardware-Accelerated 9:16 Video Rendering (`src/yt_clipping/rendering/renderer.py`)
- **`blur_background` (Default & Industry Standard - OpusClip/TikTok style)**:
  - Fits the complete 16:9 widescreen video across the 1080px portrait width with zero edge cropping.
  - Dynamically fills upper and lower letterbox areas with a matching Gaussian-blurred (`boxblur=25:5`) backdrop.
  - Enforces square pixels (`setsar=1`, `DAR 9:16`).
- **`crop_center`**: Direct 9:16 crop (`607.5x1080` scaled to `1080x1920` with `setsar=1`), preserving 100% natural human proportions with zero distortion.
- **`split_screen`**: Dual 9:8 aspect ratio crops (`ih*9/8:ih`) stacked vertically with zero geometric stretching.
- **NVIDIA NVENC Hardware Acceleration**: High-speed encoding via `h264_nvenc` with preset `p4` and constant quality rate control (`-cq 22`), with seamless CPU fallback to `libx264`.

### D. Multi-Signal Explainable Scorecard (`src/yt_clipping/scoring/scorecard.py`)
- Evaluates candidates across independent dimensions:
  - **Opening Hook (25%)**: First 3–5 seconds question/curiosity capture.
  - **Heatmap Replay Peak (25%)**: Alignment with crowd-sourced "Most Replayed" peaks.
  - **Moment Payoff (20%)**: Core insight, climax, or punchline.
  - **Standalone Coherence (15%)**: Self-contained thought without dangling pronouns or connectors.
  - **Cadence & Pacing (10%)**: Optimal short-form rate (135–185 WPM).
  - **Audio Energy (5%)**: Acoustic inflection and volume dynamics.

### E. Hard RightsGate & Checkpoint Recovery (`src/yt_clipping/rights/`, `src/yt_clipping/orchestration/`)
- **Strict Rights Verification**: Blocks downloading or rendering unless an asset has a verified rights basis (`OWNED`, `EXPLICIT_PERMISSION`, `CREATIVE_COMMONS`, `OPERATOR_ASSET`).
- **SQLite WAL Checkpointing**: Resilient state machine preserves pipeline checkpoints (`RIGHTS_CHECKED`, `ASSET_INGESTED`, `TRANSCRIBED`, `SEGMENTED`, `SCORED`, `REVIEWED`, `RENDERED`, `QA_VERIFIED`, `HANDED_OFF`).

---

## 3. Installation & Setup

### Prerequisites
- **Python 3.10+** (Tested on Python 3.12)
- **FFmpeg & ffprobe** (Must be on system PATH)
- **NVIDIA GPU** with updated drivers (optional, for hardware NVENC encoding)

### 1. Clone & Set Up Virtual Environment
```powershell
git clone <YOUR_REPO_URL>
cd yt
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env`:
```powershell
Copy-Item .env.example .env
```
Populate `.env` with your API keys:
```dotenv
# YouTube Data API v3 Configuration
YOUTUBE_API_KEY=AIzaSy...YourKeyHere
YOUTUBE_DAILY_QUOTA_LIMIT=10000

# Media Processing Defaults
DEFAULT_LAYOUT_MODE=blur_background
CRF_QUALITY=22
AUTO_APPROVE_THRESHOLD=65.0
```

---

## 4. CLI Command Reference

The platform provides an operational CLI via `python -m src.yt_clipping` or the console script `yt-clip`:

### 1. End-to-End Pipeline Run (GPU Accelerated)
Process an authorized video, score highlights, render 9:16 clip, and hand off to autopost:
```powershell
python -m src.yt_clipping run --video-id wS64_n65u3k --gpu --layout blur_background
```
*Options:*
- `--layout`: `blur_background` (default), `crop_center`, or `split_screen`
- `--gpu`: Enables NVIDIA NVENC (`h264_nvenc`) hardware acceleration
- `--dry-run` / `--no-dry-run`: Toggle live autopost handoff vs simulation

### 2. Audience Retention Heatmap & ASCII Waveform
Extract the crowd-sourced "Most Replayed" curve and identify viral peaks:
```powershell
python -m src.yt_clipping heatmap --video-id wS64_n65u3k --visual
```
*Output Preview:*
```text
[OK] Heatmap Ingestion Source: COMMENT_DENSITY (100 points)
Global Peak (#1 Most Replayed): 190.5s (03:10) | Intensity: 84.3%, Prominence: 84.3%
Recommended Clip Window: 171.2s -> 206.2s (35.0s duration)

Viewer Replay Retention Waveform [COMMENT_DENSITY] (Duration: 300s):
  ^ 100% |  ==                           ==                 |
  v   0%  00:00                 02:30                 05:00

Prominent Replay Peaks:
  #1 [GLOBAL_MAXIMA] 03:10 | Intensity: 84.3%, Prominence: 84.3%, Suggested: 171.2s - 206.2s (35.0s)
  #2 [SPIKE_PAYOFF] 00:16 | Intensity: 71.8%, Prominence: 71.8%, Suggested: 0.0s - 32.2s (32.2s)
```

### 3. Live YouTube Trending Charts & Video Virality
Query YouTube's real-time trending chart and rank videos by Virality Index:
```powershell
python -m src.yt_clipping trends --chart popular --region US --limit 5
```
Evaluate any single video's virality velocity:
```powershell
python -m src.yt_clipping trends --video-id wS64_n65u3k
```

### 4. Highlight Candidate Preview (No Render)
Preview candidate moments and explainable scorecards without rendering:
```powershell
python -m src.yt_clipping preview --video-id wS64_n65u3k
```

### 5. Content Rights Management
Register and verify operator rights in the audit ledger:
```powershell
python -m src.yt_clipping rights register --video-id wS64_n65u3k --basis OPERATOR_ASSET --owner "Browney" --proof "AGREEMENT-001"
python -m src.yt_clipping rights check --video-id wS64_n65u3k
```

### 6. Pipeline Job Audit & Checkpoint History
Inspect active and completed jobs in the SQLite WAL journal:
```powershell
python -m src.yt_clipping jobs --status SUCCEEDED
```

---

## 5. Directory Structure

```text
yt/
├── .env.example                # Configuration template
├── .gitignore                  # Production Git ignore rules
├── pyproject.toml              # Modern build & packaging spec
├── pytest.ini                  # Test suite runner configuration
├── requirements.txt            # Pinned dependencies
├── README.md                   # Platform documentation
├── THIRD_PARTY_NOTICES.md      # Upstream attribution & provenance
├── docs/                       # Architecture Decision Records (ADRs) & research
│   ├── adr/                    # Architecture Decision Records
│   └── research/               # Benchmarks, provenance, and research logs
├── src/
│   └── yt_clipping/
│       ├── cli/                # Master CLI commands & argument parser
│       ├── contracts/          # Data contracts, dataclasses, and interfaces
│       ├── detection/          # Sentence-aligned candidate segmentation & IoU dedupe
│       ├── discovery/          # TrendAnalyzer, HeatmapAnalyzer, ChannelMonitor, Ranker
│       ├── ingestion/          # Local media asset resolution & probing
│       ├── orchestration/      # Pipeline coordinator, state machine & SQLite journal
│       ├── publisher/          # Watched-folder & Webhook autopost adapters
│       ├── qa/                 # MediaQualityVerifier (streams, aspect ratio, duration)
│       ├── rendering/          # FFmpegRenderer (blur_bg, crop_center, split) & ASS captions
│       ├── rights/             # LocalRightsPolicy hard gate
│       ├── scoring/            # ExplainableScorecardScorer (Hook, Heatmap, Payoff)
│       └── transcription/      # LocalTranscriber with Faster-Whisper integration
└── tests/                      # Comprehensive test suite (47 tests)
    ├── test_autopost_adapter.py
    ├── test_cli_and_preview.py
    ├── test_contracts.py
    ├── test_deduplication.py
    ├── test_discovery_ranker.py
    ├── test_end_to_end_vertical_slice.py
    ├── test_heatmap_analysis.py
    ├── test_qa_verifier.py
    ├── test_rendering_and_captions.py
    ├── test_rights_gate.py
    ├── test_scoring.py
    ├── test_state_machine_recovery.py
    ├── test_timestamp_math.py
    └── test_trend_analysis.py
```

---

## 6. Testing & Quality Assurance

Run the complete 47-test suite:
```powershell
pytest -v tests
```

Every commit enforces:
- 100% deterministic arithmetic on subtitle centisecond carry-overs
- Temporal IoU suppression on overlapping candidate intervals
- Mathematical precision in topological prominence calculations
- Zero regression on pipeline state-machine recovery

---

## 7. License & Compliance

Distributed under the **MIT License**. See `LICENSE` for details.
All external algorithms, inspiration sources, and upstream research references are documented in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
