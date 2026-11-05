# Phase 2 Implementation Plan: Production-Grade YouTube Clipping Intelligence Platform

## 1. Executive Summary & Audit Overview

This document specifies the architectural audit, component reuse strategy, design decisions, implementation sequence, and verification plan for Phase 2 of the YouTube Clipping Intelligence Platform.

The platform's baseline codebase currently consists of:
- **452 Passing Automated Tests** covering active speaker framing, B-roll pipelines, Gemini multimodal scoring, diarization, dead-air pruning, heatmap analysis, MCP server tools, and SQLite state persistence.
- A functional end-to-end pipeline (`build_pipeline`) combining transcription, segmentation, scoring, vertical rendering with FFmpeg, and rights checking.
- A basic FastAPI server with an embedded live dashboard in `src/yt_clipping/web/server.py`.

Phase 2 elevates the platform into a production-grade, commercial-quality SaaS Web Studio with dual-engine metadata ingestion, explainable AI clip intelligence, multi-model caption synthesis with deterministic offline fallback, durable project/clip sidecar persistence surviving restarts, asynchronous background job management, rigorous media QA validation, and a redesigned dark-mode frontend studio.

---

## 2. Existing Architecture & Current Capabilities

### Current Core Modules:
1. **Ingestion & Rights:**
   - `src/yt_clipping/ingestion/asset_provider.py`: Handles local assets and yt-dlp downloading. Contains `extract_youtube_video_id` for basic URL parsing.
   - `src/yt_clipping/rights/gate.py`: Enforces `RightsManifest` checks before processing.
2. **Detection & Scoring:**
   - `src/yt_clipping/detection/solid_shorts.py` (`SolidShortsDecider`): Dynamic yield algorithm calculating optimal clip count based on video duration, hook strength, and temporal spacing.
   - `src/yt_clipping/scoring/gemini_provider.py` (`GeminiHighlightDiscoveryProvider`): Cloud highlight discovery using Google Gemini 1.5 Flash.
   - `src/yt_clipping/scoring/scorecard.py` (`ExplainableScorecardScorer`): Offline heuristic scorecard with hook, coherence, pacing, and moment scoring.
   - `src/yt_clipping/discovery/heatmap.py`: Heatmap replay intensity extraction from YouTube or comment density.
3. **Rendering Pipeline:**
   - `src/yt_clipping/rendering/renderer.py` (`FFmpegClipRenderer`): Renders 9:16 vertical video using `active_speaker`, `blur_background`, or `split_screen`.
   - `src/yt_clipping/rendering/captions.py`: Generates animated burned-in subtitles with presets (`hormozi`, `beast_bounce`, `neon_cyber`, `clean_editorial`).
   - `src/yt_clipping/rendering/outro_card.py` & `cta_overlay.py`: Animated outro cards, sound chimes, and subscription CTA overlays.
4. **Orchestration & Persistence:**
   - `src/yt_clipping/orchestration/state_machine.py` (`JobJournal`): SQLite-backed durable journal with WAL mode (`data/jobs.db`).
   - `src/yt_clipping/orchestration/db.py` (`DatabaseManager`): Core database interface.
   - `src/yt_clipping/orchestration/storage_manager.py` (`StorageManager`): Artifact lifecycle and cache cleanup.
5. **Quality Assurance:**
   - `src/yt_clipping/qa/verifier.py` (`MediaQualityVerifier`): Container readability, duration tolerance, and stream inspection.
6. **Web Dashboard & API:**
   - `src/yt_clipping/web/server.py`: FastAPI server serving endpoints `/api/v1/health`, `/api/v1/preview`, `/api/v1/render`, `/api/v1/clips`, and `HTML_DASHBOARD`.

---

## 3. Gap Analysis: Missing Capabilities for Phase 2

1. **Dual-Engine Metadata Ingestion (`discovery/video_metadata.py`):**
   - Lacks YouTube Data API v3 integration with structured quota management.
   - URL parsing currently in `asset_provider.py` does not normalize embed URLs, tracking params, and lacks SSRF protections.
   - No standardized `EnrichedVideoInfo` typed data contract.
   - No automatic cascading fallback from YouTube Data API v3 to `yt-dlp` metadata-only extraction.

2. **Explainable AI Clip Intelligence:**
   - While `ScoreBreakdown` provides raw numeric scores, there is no explainability engine producing human-readable "Why This Short Works" breakdowns (hook strength, context completeness, narrative quality, information density, ending quality, engagement potential).

3. **Multi-Model Caption & Hook Synthesizer (`scoring/caption_synthesizer.py`):**
   - No dedicated multi-platform caption package generator supporting model cascading (`gemini-3.5-flash-lite` -> `gemini-flash-latest` -> offline deterministic fallback).
   - Missing structured platform variants (YouTube Shorts, Instagram Reels, TikTok), creator attribution formatting, legal copyright awareness disclaimers, and hashtag intelligence.

4. **Persistent Project & Clip Sidecar Storage:**
   - Rendered clips are currently saved only as loose MP4 files in `data/rendered_clips/`.
   - When the server restarts, clip metadata (candidate info, scores, captions, intelligence rationale, QA report) is disconnected from the files.
   - No structured project directory convention (`data/projects/project_<id>/...`) with atomic sidecar JSON files.

5. **Asynchronous Background Job Management:**
   - Current `/api/v1/render` stores running jobs in an ephemeral in-memory dictionary `active_render_jobs`, which is wiped if the server restarts.
   - Lacks graceful job cancellation, staged progress tracking (`queued`, `discovering`, `analyzing`, `generating_caption`, `rendering`, `validating`, `completed`, `failed`, `cancelled`), and persistent job resumption.

6. **Automated Post-Render Video Quality Assurance:**
   - Existing `MediaQualityVerifier` lacks checks for black frames, corrupt frame decoding samples, audio silence detection, and subtitle safe zone compliance.

7. **Professional SaaS Web Studio Redesign:**
   - Current `HTML_DASHBOARD` is a simple developer testing tool.
   - Needs a commercial dark-mode SaaS UI featuring a video player with range request seeking, "Why This Short Works" intelligence cards, an interactive Caption Studio (edit, copy, platform variants), project history explorer, and system diagnostics.

---

## 4. Components to Reuse vs. Modify vs. Create New

| Component | Status | Strategy |
|:---|:---|:---|
| `SolidShortsDecider` (`src/yt_clipping/detection/solid_shorts.py`) | **Reuse** | Preserve core scoring and dynamic capacity ceiling logic. Wrap with intelligence explainability. |
| `JobJournal` (`src/yt_clipping/orchestration/state_machine.py`) | **Reuse & Extend** | Reuse SQLite schema and connection handling. Add project records and enhanced job stage tracking. |
| `MediaQualityVerifier` (`src/yt_clipping/qa/verifier.py`) | **Reuse & Extend** | Extend with audio volume/silence probing, black frame inspection, and video decodability validation. |
| `FFmpegClipRenderer` & Subtitles (`src/yt_clipping/rendering/*`) | **Reuse** | Maintain existing robust FFmpeg rendering, face tracking, and animated caption generation. |
| `VideoMetadataService` (`src/yt_clipping/discovery/video_metadata.py`) | **Create New** | Implement dual-engine ingestion (YouTube Data API v3 + yt-dlp fallback) and URL normalizer. |
| `CaptionSynthesizer` (`src/yt_clipping/scoring/caption_synthesizer.py`) | **Create New** | Implement multi-model cascading Gemini prompt with strict JSON parsing and deterministic fallback. |
| `ProjectStore` (`src/yt_clipping/orchestration/project_store.py`) | **Create New** | Implement atomic sidecar persistence, project directory structure, and restoration logic. |
| `JobManager` (`src/yt_clipping/orchestration/job_manager.py`) | **Create New** | Implement persistent, cancellable, staged background job execution. |
| `Web Studio Server` (`src/yt_clipping/web/server.py`) | **Modify** | Add REST endpoints (`/api/v1/metadata`, `/api/v1/jobs/...`, `/api/v1/projects/...`, HTTP range media streaming) and rewrite `HTML_DASHBOARD`. |

---

## 5. Implementation Sequence

1. **Phase A: Repository Audit & Baseline Verification** (Completed: 452 passing tests verified).
2. **Phase B: Dual-Engine YouTube Metadata Ingestion** (`video_metadata.py` + tests).
3. **Phase C: AI Short Intelligence & Caption Synthesizer** (`caption_synthesizer.py` + tests).
4. **Phase D: Persistent Project & Clip Sidecar Storage** (`project_store.py` + tests).
5. **Phase E: Asynchronous Background Job Manager** (`job_manager.py` + tests).
6. **Phase F: Media Quality Assurance Hardening** (`verifier.py` enhancement + tests).
7. **Phase G: REST API Integration & Media Streaming** (`server.py` extensions).
8. **Phase H: Professional SaaS Web Studio Redesign** (Modern dark-mode UI with full interactivity).
9. **Phase I: Security, SSRF & Path Traversal Auditing**.
10. **Phase J: Comprehensive Test Suite & Zero-Regression Verification** (Run all 452+ tests).
11. **Phase K: Documentation & Operations Guides**.

---

## 6. Risks and Mitigation Strategies

- **Risk: External YouTube API Quota Exhaustion or Network Failure.**
  - *Mitigation:* Automatic fallback to `yt-dlp` metadata-only extraction with aggressive caching (`data/cache/metadata/`).
- **Risk: Gemini API Latency or Rate Limits.**
  - *Mitigation:* Configurable model cascading (`gemini-3.5-flash-lite` -> `gemini-flash-latest`) and immediate deterministic offline fallback producing structured captions without hanging.
- **Risk: Storage Corruption on Crash.**
  - *Mitigation:* Atomic write pattern (`write to .tmp` -> `flush` -> `atomic rename`) for all metadata and sidecar files.
- **Risk: Long Video Rendering HTTP Timeouts.**
  - *Mitigation:* Pure asynchronous job queue returning `job_id` within 50ms, with frontend polling and cancellation support.
- **Risk: Regressions in Existing 452 Tests.**
  - *Mitigation:* Strict backward-compatibility in contracts (`to_dict` / `from_dict`), keeping existing interfaces intact.
