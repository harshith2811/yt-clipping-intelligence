# YouTube Clipping Intelligence Platform — Module Reference

Comprehensive architectural index and API specification for every package, module, class, and subsystem in `yt-clipping-intelligence`. For visual component topologies and mental models, see [System Mental Map](SYSTEM_MENTAL_MAP.md).

---

## Table of Packages

| Package | Path | Primary Purpose |
|---|---|---|
| **Audio** | `src/yt_clipping/audio/` | Text-to-speech voice synthesis & audio generation. |
| **CLI** | `src/yt_clipping/cli/` | Master terminal interface & subcommands. |
| **Contracts** | `src/yt_clipping/contracts/` | Strongly-typed dataclasses, interfaces, and state enums. |
| **Detection** | `src/yt_clipping/detection/` | Dead-air pruning, candidate segmentation, energy analyzers, short viability. |
| **Discovery** | `src/yt_clipping/discovery/` | Zero-quota RSS feeds, outlier virality multiplier, channel monitoring, WebSub. |
| **MCP** | `src/yt_clipping/mcp/` | Model Context Protocol JSON-RPC 2.0 stdio server. |
| **Orchestration** | `src/yt_clipping/orchestration/` | Pipeline manager, SQLite WAL task queue, state machine, storage. |
| **Podcast** | `src/yt_clipping/podcast/` | Stacked 9:8 split-screen, acoustic/Pyannote diarizer, shot detector. |
| **Publisher** | `src/yt_clipping/publisher/` | Watched-folder and REST webhook handoff adapter. |
| **QA** | `src/yt_clipping/qa/` | Video stream, aspect ratio (9:16), SAR 1:1, bitrate compliance verification. |
| **Rendering** | `src/yt_clipping/rendering/` | Native FFmpeg NVENC/CPU compositing, ASS kinetic subtitles, AutoFlip kinematics, B-Roll engine, CTA overlay engine. |
| **Reporting** | `src/yt_clipping/reporting/` | Executive HTML diagnostic and telemetry reports. |
| **Rights** | `src/yt_clipping/rights/` | Hard non-bypassable transactional SQLite copyright & rights verification gate. |
| **Scoring** | `src/yt_clipping/scoring/` | Multi-signal scorecard, Gemini Flash discovery, 40-char packaging linter. |
| **Transcription** | `src/yt_clipping/transcription/` | Faster-Whisper int8 transcriber and WhisperX forced alignment engine. |
| **Root Tools** | Repository Root | Direct convenience CLI scripts. |

---

## 1. Contracts Subsystem (`src/yt_clipping/contracts/`)

Typed data schemas and abstract provider contracts enforcing decoupled, testable components.

### `models.py`
- **`RightsBasis` (Enum):** `PUBLIC_DOMAIN`, `CREATIVE_COMMONS`, `EXPLICIT_LICENSE`, `FAIR_USE_COMMENTARY`, `STRICT_COPYRIGHT`.
- **`RightsStatus` (Enum):** `VERIFIED`, `QUARANTINED`, `REJECTED`, `PENDING_REVIEW`.
- **`JobStage` (Enum):** Discrete stages: `DISCOVERED`, `RIGHTS_VERIFIED`, `ASSETS_ACQUIRED`, `TRANSCRIBED`, `HIGHLIGHTS_DETECTED`, `SCORED`, `RENDERED`, `QA_VERIFIED`, `PUBLISHED`, `FAILED`.
- **`JobStatus` (Enum):** `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`.
- **`WordTimestamp`:** Dataclass containing `word: str`, `start: float`, `end: float`, `confidence: float`.
- **`TranscriptSegment`:** Contains `id: int`, `seek: int`, `start: float`, `end: float`, `text: str`, `words: List[WordTimestamp]`.
- **`Transcript`:** Complete transcript container with language, duration, full text, and segments.
- **`HighlightCandidate`:** Candidate clip bounds (`start_time`, `end_time`, `score`, `reason`, `breakdown`, `loop_affinity_score`).
- **`ScoreBreakdown`:** Multi-signal component scores (`hook_score`, `audio_energy`, `cadence_score`, `heatmap_score`, `narrative_arc_score`, `payoff_score`, `outlier_bonus`).
- **`RenderProfile`:** Rendering parameters (`canvas_width`, `canvas_height`, `fps`, `codec`, `preset`, `crf`, `layout_mode`, `subtitle_style`, `enable_cta`, `cta_text`, `cta_timing`, `cta_style`, `enable_pacing_polish`, audio/video fade durations).
- **`QAReport`:** Verification results (`passed: bool`, `streams_valid: bool`, `dar_valid: bool`, `duration: float`, `bitrate: int`, `issues: List[str]`).

### `interfaces.py`
Abstract Base Classes (ABCs):
- `DiscoveryProvider`: Interface for finding viral video candidates.
- `RightsPolicy`: Interface for non-bypassable rights verification.
- `Transcriber`: Interface for audio transcription.
- `HighlightDetector`: Interface for candidate moment extraction.
- `HighlightScorer`: Interface for multi-signal candidate scoring.
- `Renderer`: Interface for 9:16 vertical video compositing.
- `QualityVerifier`: Interface for post-render stream QA.
- `HandoffPublisher`: Interface for dispatching finished clips to destination publishers.

---

## 2. Audio Processing (`src/yt_clipping/audio/`)

### `tts_engine.py`
- **Class `TTSEngine`:** Offline and cloud-assisted voice synthesis.
  - Automatically synthesizes voiceover audio tracks for narration or intro hooks.
  - Generates cached MP3/WAV assets to prevent redundant API calls.
  - Configurable speech rate, pitch, and voice models.

---

## 3. Candidate Detection & Pacing (`src/yt_clipping/detection/`)

Algorithmic extraction, pruning, and filtering of high-potential video segments.

### `deadair.py`
- **Class `DeadAirPruner`:** Pacing and silence pruner adapted from cutting-edge short-form video editors.
  - **Dead-Air Removal:** Detects inter-word pauses $> 0.35\text{s}$ and computes micro-cut jump cuts or pacing penalties.
  - **Filler Token Pruning:** Identifies low-value conversational fillers (`"um"`, `"uh"`, `"like"`, `"you know"`, `"basically"`).
  - **Sentence Restart Detection:** Identifies speaker false starts when normalized word prefixes match (`norm(prev)[:5] == norm(curr)[:5]`).
  - **Output:** Returns `PruneResult` with pruned duration, timeline remapping, and tightness score.

### `short_viability.py`
- **Class `ShortViabilityValidator`:** Enforces the "Survives Without Context" criteria for standalone vertical shorts:
  - **Complete Thought Opening:** Rejects clips starting with dangling pronouns (`"he"`, `"they"`, `"that"`) referring to unknown prior context.
  - **The Narrative Turn:** Verifies the clip contains a claim followed by proof, complication, or emotional shift.
  - **Definitive Payoff:** Ensures the clip ends on a declarative sentence or punchline, not a mid-clause trailing fragment.
  - **Loop Hook:** Analyzes semantic affinity between the first and last line for seamless looping ($0.0 - 1.0 \rightarrow 0.0 - 10.0$ loop affinity score).

### `audio_energy.py`
- **Class `AudioEnergyAnalyzer`:** Computes RMS volume envelopes, audio peak densities, and detects vocal laughter spikes.
- **Class `AdaptiveCadenceScorer`:** Computes speech cadence dynamic changes, identifying shifts from explanatory speech into emphatic punchlines.

### `segmenter.py`
- **Class `ContextAwareSegmenter`:** Tokenizes speech transcripts into semantically coherent 15–60s segments aligned strictly with sentence boundaries.

### `dedupe.py`
- **Function `suppress_overlapping_candidates`:** Applies Non-Maximum Suppression (NMS) over temporal candidate intervals based on temporal Intersection-over-Union (IoU) overlap thresholds.

---

## 4. Channel Discovery & Virality (`src/yt_clipping/discovery/`)

### `outlier.py`
- **Class `OutlierMultiplier`:** Computes channel-normalized virality multipliers:
  $$\text{Virality Multiple} = \frac{\text{Video Views}}{\text{Median}(\text{Channel Views})}$$
  - Baseline requirement: $\ge 4$ recent videos on the creator's channel.
  - Classifications: `BREAKOUT` ($\ge 3.0\times$), `ABOVE_AVERAGE` ($\ge 1.5\times$), `TYPICAL` ($0.7\times - 1.5\times$), `UNDERPERFORMING` ($< 0.7\times$).

### `heatmap.py`
- **Class `HeatmapAnalyzer`:** Reconstructs YouTube 100-point audience replay curves to locate peaks of highest viewer attention, snapping boundaries to local baseline retention troughs.

### `pinger_daemon.py`
- **Class `PingerDaemon`:** Zero-quota background daemon monitoring creator channels via public Atom/RSS feeds with HTTP `ETag` and `304 Not Modified` caching.

### `trend_scorer.py`
- **Class `TrendScorer`:** Computes velocity metrics ($V_{\text{hourly}} = \frac{\text{views}}{\text{age}}$) and enforces the Audience Resonance Gate ($LVR \ge 1.2\%$, $CVR \ge 0.03\%$).

---

## 5. Model Context Protocol Server (`src/yt_clipping/mcp/`)

### `server.py`
- **Class `MCPServer`:** Native JSON-RPC 2.0 stdio server conforming to MCP `2024-11-05` specification.
  - Exposes 7 granular tools:
    1. `discover_viral_videos`: Search, RSS ingest, and outlier ranking.
    2. `verify_source_rights`: Non-bypassable transactional rights checks.
    3. `transcribe_and_align`: Audio transcription and WhisperX word alignment.
    4. `detect_highlights`: Candidate extraction with explainable multi-signal scoring.
    5. `prune_dead_air`: Silence gap, filler word, and false start pruning.
    6. `render_vertical_short`: 9:16 layout compositing, ASS subtitles, and B-roll.
    7. `get_pipeline_job_status`: Durable task state tracking and progress reporting.
  - See [docs/mcp.md](mcp.md) for full protocol specifications.

---

## 6. Podcast Engine Subsystem (`src/yt_clipping/podcast/`)

### `pipeline.py` & `cli.py`
- **Class `PodcastShortMaker`:** Complete orchestration pipeline for podcast videos.
- **Module `cli.py`:** Dedicated command-line entrypoint (`python -m yt_clipping.podcast.cli` and `yt-clip podcast`).

### `layout.py`
- **Functions `build_podcast_split_filtergraph` & `build_podcast_closeup_filtergraph`:** Constructs optimized FFmpeg filtergraphs for stacked 9:8 split-screen and director close-ups.

### `diarization.py`
- **Class `SpeakerDiarizer` (ABC):** Unified diarization contract.
- **Class `PyannoteDiarizerAdapter`:** Neural voice clustering via Pyannote.
- **Class `AcousticEnergyDiarizer`:** Zero-VRAM, 100% offline acoustic energy and spectral centroid clustering.

### `shot_detector.py`
- **Class `PodcastShotDetector`:** CV2 frame difference and facial layout analyzer classifying shots as `SPLIT_HOST_GUEST`, `SOLO_HOST`, `SOLO_GUEST`, or `WIDE_TWO_SHOT`.

### `captions.py`
- **Class `PodcastSubtitleGenerator`:** Center-divider aligned ASS subtitle generator (`MarginV = height // 2`).

---

## 7. Rendering & Kinematic Smoothing (`src/yt_clipping/rendering/`)

### `renderer.py`
- **Class `FFmpegRenderer`:** Multi-layout rendering engine:
  - `blur_background`: Centered 16:9 source with blurred background padding.
  - `active_speaker`: Face-tracked dynamic 9:16 crop.
  - `split_screen`: Stacked 9:8 top/bottom layout.
  - Broadcast audio anti-pop fades (20ms half-sine `afade=t=in:ss=0:d=0.02:curve=hsin` and 250ms outro fade) and video transitions.
  - Automated Call-to-Action (CTA) overlay burning and subtitle injection.
  - Hardware acceleration with NVIDIA NVENC (`h264_nvenc`) and CPU fallback (`libx264`).

### `cta_overlay.py`
- **Class `CTAOverlayEngine`:** Self-contained animated Call-to-Action overlay engine.
  - **Enums & Models:** `CTAConfig`, `CTAStyle` (`MODERN_PILL`, `NEON_BANNER`, `MINIMAL`), `CTATiming` (`END`, `INTRO`, `PERSISTENT`), `CTATimingWindow`.
  - **Safe-Zone Geometry:** Dynamically computes horizontal and vertical bounds avoiding TikTok/Reels UI obstructions and podcast center-divider bars.
  - **Libass Vector Graphics:** Renders smooth vector rounded-corner background pills using ASS drawing commands (`m ... b ... c ...`) with `\move` slide animations and `\fad` alpha fades.
  - **Subtitle Injection & Standalone Modes:** Injects CTA dialogue events directly into active subtitle files or generates standalone burnable ASS files.
  - **FFmpeg Filter Generation:** Emits native `drawbox` + `drawtext` filter chains for environments without libass.

### `face_tracker.py`
- **Class `ActiveSpeakerFramer`:** YuNet ONNX neural face detector tracking primary speaker centers.
- **Class `ConstrainedTrajectoryOptimizer`:** AutoFlip-inspired 1D camera path smoother using SciPy banded linear solvers, enforcing acceleration limits ($a_{\text{max}}$), velocity limits ($v_{\text{max}}$), and deadband hysteresis. Sanitizes string and non-finite coordinate inputs.

### `b_roll.py`
- **Class `BRollOverlayEngine`:** Automated B-roll video overlay engine.
  - Analyzes transcript for extended speaker monologues ($>4\text{s}$).
  - Slices and inserts contextual stock video overlays.
  - Applies automated background audio ducking ($0.4\times$) and crossfades.

### `captions.py`
- **Class `SubtitleGenerator`:** Generates word-synced animated ASS subtitle streams:
  - Presets: `hormozi` (bold yellow bounce), `beast_bounce` (high-energy pop), `neon_cyber` (cyan glow), `karaoke_gold`, `bold_social`.
  - Platform safe zones avoiding TikTok/Reels UI overlay buttons.

---

## 8. Pipeline Orchestration & Storage (`src/yt_clipping/orchestration/`)

### `pipeline.py`
- **Class `ClippingPipeline`:** End-to-end master controller connecting Ingestion $\rightarrow$ Rights Gate $\rightarrow$ Transcription $\rightarrow$ Highlight Detection $\rightarrow$ Rendering $\rightarrow$ QA $\rightarrow$ Publishing.
  - Stage 6: Populates candidate `loop_affinity_score` from short viability reports.
  - Stage 6b: Broadcast hook pacing polish (dead-air trimming to ~0.10s, consonant buffer protection, outro mid-word cut avoidance).

### `queue.py`
- **Class `JobQueue`:** Durable SQLite WAL job queue featuring priority leases, atomic transitions, and exponential backoff.

### `state_machine.py`
- **Class `JobJournal`:** Crash-resilient state machine ledger recording stage progress, telemetry, and error recovery states.

### `storage_manager.py`
- **Class `StorageManager`:** Manages file paths, temporary workspace directories, asset lifecycles, and cleanup routines.

---

## 9. Scoring & Packaging Quality Gates (`src/yt_clipping/scoring/`)

### `scorecard.py`
- **Class `ExplainableScorecardScorer`:** Deterministic scoring engine computing 0–100 highlight retention scores with transparent weight breakdowns.

### `gemini_provider.py`
- **Class `GeminiHighlightDiscoveryProvider`:** Multimodal highlight discovery leveraging Google Gemini Flash to identify high-emotion and context-rich moments. Includes `is_available()` health check with automatic local degradation when API keys are absent.

### `packaging_linter.py`
- **Class `PackagingLinter`:** Enforces viral packaging quality standards:
  - Mobile truncation safety: Main hook within 40 characters; hard cap at 60 characters.
  - Stop-word front loading prevention: Flags generic opening phrases.
  - Click-surface deduplication: Ensures title and thumbnail text do not mirror each other identically.
  - Buzzword elimination: Replaces vague clickbait with concrete metrics or proper nouns.

---

## 10. Transcription & Forced Alignment (`src/yt_clipping/transcription/`)

### `transcriber.py`
- **Class `LocalTranscriber`:** Offline speech-to-text powered by `faster-whisper` running int8 quantization on GPU or CPU.

### `alignment.py`
- **Class `AlignmentEngine` (ABC):** Sub-second word alignment contract.
- **Class `WhisperXAlignmentAdapter`:** Phoneme-level wav2vec2 forced alignment via WhisperX.
- **Class `FasterWhisperAlignmentAdapter`:** Monotonic fallback alignment preserving word order and clamping boundaries.

---

## 11. Quality Assurance & Publishing (`src/yt_clipping/qa/`, `publisher/`)

### `verifier.py`
- **Class `MediaQualityVerifier`:** Post-render validation ensuring exact 1080x1920 dimensions, 9:16 Display Aspect Ratio (DAR), 1:1 Sample Aspect Ratio (SAR), non-zero audio streams, and platform bitrate constraints. Features robust fallback hierarchy when `ffprobe` is omitted.

### `adapter.py`
- **Class `DualModeAutopostPublisher`:** Handoff publisher supporting both watched-folder local export and signed REST webhook dispatch.

---

## 12. Root Convenience Tools

Direct terminal scripts located at the workspace root for rapid operator workflow:
- `channel_watcher.py`: Real-time polling and scraping of creator channels.
- `pinger_daemon.py`: Autonomous zero-quota RSS upload monitor.
- `trend_scorer.py`: Standalone velocity and resonance evaluation.
- `attribution_engine.py`: Formats creator attribution packages and descriptions.

---

## 13. System Architecture & Traceability

For the holistic mental model, module interaction diagrams, and CLI-to-pipeline traceability mapping, refer to:
- **[System Architecture](ARCHITECTURE.md)**
- **[System Mental Map](SYSTEM_MENTAL_MAP.md)**
- **[CLI Operator Reference](CLI_REFERENCE.md)**
