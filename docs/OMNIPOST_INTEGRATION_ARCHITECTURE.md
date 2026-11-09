# Unified Platform Architecture: OmniPost + YouTube Automation Engine

## Executive Summary
This document establishes the architectural blueprint for the unification of **OmniPost** (Multi-Platform Social Publishing Engine) and the **YouTube Clipping Intelligence Platform** (Autonomous Content Simulation, Extraction, Framing, and QA Engine).

The integrated system provides an end-to-end automated and human-governed content pipeline:
```
Content Discovery / Simulation
              │
              ▼
       Video Rendering
              │
              ▼
   Intelligent Clipping & QA
              │
              ▼
     Manual Video Editor ◄─── Human Control & Precision Crafting
              │
              ▼
   Explicit User Approval
              │
              ▼
  Publishing Engine (OmniPost + Dedicated YouTube OAuth Channel)
              │
              ▼
   Tracking, Retries & Analytics
```

---

## 1. Architectural Audit & Project Comparison

| Dimension | YouTube Clipping Intelligence (`yt-clipping`) | OmniPost (`omnipost`) | Unified Target Architecture |
| :--- | :--- | :--- | :--- |
| **Primary Role** | Content generation, virality scoring, speaker tracking, subtitle rendering, clip extraction. | Social media distribution, container lifecycle, rate-limiting, publishing queue. | End-to-end production pipeline: Generation → Clipping → Editing → Approval → Publishing. |
| **Runtime & Language** | Python 3.12 (FastAPI, PyTorch/ONNX, OpenCV, MoviePy, Whisper). | Node.js v22 (Express, ES Modules, Supabase JS, Fetch). | Python FastAPI host with embedded Node.js OmniPost engine and direct REST integration. |
| **Database & Persistence** | SQLite (`data/jobs.db`) + JSON Sidecars (`data/projects/`). | SQLite / Supabase PostgreSQL + JSON cache (`data/posts.json`). | Unified persistence ledger: SQLite `jobs.db` holds publishing receipts, SQLite/JSON holds project sidecars. |
| **Authentication & Credentials** | API keys for external AI models (Gemini, Groq, Whisper). | Passkey RBAC (`x-admin-key`, `Authorization: Bearer`), session JWTs. | **Dedicated Google Account Isolation**: Independent OAuth 2.0 credentials exclusively for automation channel. Zero token leakage. |
| **Video Processing** | FFmpeg 7.1 pipelines, dynamic 9:16 reframing, active speaker tracking, word-level ASS subtitles. | Relies on external renderers or static media uploads. | FFmpeg-based modular Video Editor engine supporting multi-aspect ratio crop, trim, pan, and text overlays. |
| **Publishing Adapters** | Dual-mode handoff publisher (`DualModeAutopostPublisher`, `OmniPostPublisher`). | Native drivers for Facebook, Instagram, Threads, LinkedIn, Pinterest + n8n YouTube driver. | Direct Dedicated YouTube API v3 Publisher + OmniPost Multi-Platform Publishing Layer. |
| **Human Governance** | Web dashboard for preview and QA score inspection. | Preflight checks and approve/reject post status. | **Strict Human Approval Gate**: Automation generates candidates; publishing requires explicit authorization. |

---

## 2. Component Design & Module Boundaries

### 2.1 Dedicated Google Account & Credential Isolation (`yt_clipping.auth.google_oauth`)
To eliminate any risk of mixing personal accounts with automation channels:
1. **Isolated Credential Store**: Stored in `data/credentials/youtube_auth.json` with strict file permissions, ignored by `.gitignore`.
2. **Environment Variable Configuration**:
   - `YOUTUBE_CLIENT_ID`: Dedicated OAuth 2.0 client ID.
   - `YOUTUBE_CLIENT_SECRET`: Dedicated OAuth 2.0 client secret.
   - `YOUTUBE_REDIRECT_URI`: Dedicated OAuth redirect callback (`http://localhost:8000/api/v1/auth/google/callback`).
   - `YOUTUBE_REFRESH_TOKEN`: Pre-authorized refresh token (optional override).
   - `YOUTUBE_CHANNEL_ID`: Destination YouTube channel ID.
   - `OMNIPOST_ENV`: Separation between `development` (sandboxed/dry-run) and `production`.
3. **Automatic Token Refresh**: Transparent token renewal when access tokens expire.
4. **Data Sanitization**: Frontend APIs return channel brand metadata (Title, Handle, Subscriber Count, Avatar) and never reveal refresh tokens, client secrets, or auth tokens.

### 2.2 Manual Video Editor Engine (`yt_clipping.rendering.editor`)
The manual video editor bridges automated clip generation and final publishing:
1. **Interactive Timeline & Trimming**: Millisecond-accurate start and end markers.
2. **Multi-Ratio Viewport**: 9:16 (Shorts/Reels/TikTok), 16:9 (Landscape YouTube), and 1:1 (Square).
3. **Repositioning & Pan**: Configurable crop coordinates and subject focus adjustment.
4. **Text Overlays**: Configurable title cards, captions, font size, color, background boxes.
5. **Multi-Clip Extraction**: Segment a single long-form video into multiple edited clips.
6. **Lossless / Fast FFmpeg Export**: Synchronous or queued rendering with audio-video sync preservation (`-avoid_negative_ts make_zero -c:v libx264 -c:a aac`).

### 2.3 Publishing Workflow & Governance (`yt_clipping.publisher.omnipost`)
1. **Gated Rights & QA Verification**: Every clip must pass Rights Clearance and QA checks before publishing eligibility.
2. **Explicit User Approval**: The system rejects automated publishing requests lacking `approved_by_user=True`.
3. **Idempotency Ledger**: Deduplication using canonical video hashes and clip boundaries prevents accidental double-posting.
4. **Multi-Channel Dispatch**: Supports direct YouTube upload via Dedicated OAuth channel as well as OmniPost multi-channel distribution (Instagram, Facebook, LinkedIn).
5. **Safe Retries & History**: Real-time status tracker and replay mechanism for failed publishing attempts.

---

## 3. Data Flow Specification

```
[YouTube Video / Local Upload]
              │
              ▼
[Pipeline Processing: Ingestion -> Detection -> Scored Arcs -> QA Render]
              │
              ▼
[ProjectStore: ProjectRecord + ClipSidecarRecords]
              │
              ├──► [Manual Video Editor] ──► [Exported Edited Clips]
              │                                      │
              ▼                                      ▼
[Web Dashboard: Human Review, Approval & Metadata Editing]
              │
              ▼ (Explicit User Click: "Approve & Publish")
[Publisher Dispatcher]
        ├── Dedicated YouTube Publisher (YouTube Data API v3)
        └── OmniPost Gateway (Port 3300 / Universal Inbound API)
              │
              ▼
[Publishing Receipt Ledger: DELIVERED | SCHEDULED | FAILED]
```

---

## 4. Security & Compliance
- **Zero Token Leakage**: Credentials never appear in browser responses, logs, or sidecars.
- **CSRF & State Validation**: OAuth 2.0 authorization uses cryptographically signed state tokens.
- **Fail-Safe Rights Gates**: Unverified or disputed content is rejected at the publishing adapter layer before network egress.
