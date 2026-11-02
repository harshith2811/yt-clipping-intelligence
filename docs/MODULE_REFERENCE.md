# YouTube Clipping Intelligence Platform — Module Reference

Comprehensive architectural index and API specification for every package, module, class, and subsystem in `yt-clipping-intelligence`. For visual component topologies and mental models, see [System Mental Map](SYSTEM_MENTAL_MAP.md).

---

## Table of Packages

| Package | Path | Primary Purpose |
|---|---|---|
| **Contracts** | `src/yt_clipping/contracts/` | Strongly-typed dataclasses, interfaces, state enums, and exceptions. |
| **Discovery** | `src/yt_clipping/discovery/` | Zero-quota RSS feeds, outlier multiplier, channel monitoring, WebSub, quota governor, virality scoring. |
| **Ingestion** | `src/yt_clipping/ingestion/` | yt-dlp media downloader, video ID parsing, ffprobe/OpenCV stream probing, SHA-256 provenance hashing. |
| **Rights** | `src/yt_clipping/rights/` | Hard non-bypassable transactional SQLite copyright & rights verification gate. |
| **Transcription** | `src/yt_clipping/transcription/` | Faster-Whisper int8 transcriber and WhisperX/monotonic forced alignment engine. |
| **Detection** | `src/yt_clipping/detection/` | Context-aware segmentation, narrative arc detection, dead-air pruning, audio/motion energy, short viability. |
| **Scoring** | `src/yt_clipping/scoring/` | Explainable multi-signal scorecard, Gemini Flash cloud discovery, packaging linter, metadata generator. |
| **Podcast** | `src/yt_clipping/podcast/` | Stacked 9:8 split-screen, acoustic/Pyannote diarizer, shot detector, subtitle generator. |
| **Rendering** | `src/yt_clipping/rendering/` | Native FFmpeg NVENC/CPU compositing, ASS kinetic subtitles, AutoFlip kinematics, B-Roll engine, CTA overlay engine, Outro card engine. |
| **QA** | `src/yt_clipping/qa/` | Video stream, aspect ratio (9:16), SAR 1:1, audio level, duration, and container integrity verification. |
| **Publisher** | `src/yt_clipping/publisher/` | Watched-folder and HMAC-signed REST webhook handoff adapter. |
| **Orchestration** | `src/yt_clipping/orchestration/` | Resumable pipeline manager, SQLite WAL task queue, state machine journal, storage manager. |
| **Reporting** | `src/yt_clipping/reporting/` | Executive HTML diagnostic and telemetry reports. |
| **MCP** | `src/yt_clipping/mcp/` | Model Context Protocol JSON-RPC 2.0 stdio server for AI agents. |
| **CLI** | `src/yt_clipping/cli/` | Master terminal interface & 21 subcommands. |
| **Audio** | `src/yt_clipping/audio/` | Text-to-speech voice synthesis & Edge-TTS audio generation. |
| **Root Tools** | Repository Root | Direct convenience CLI scripts delegating to discovery subsystem. |

---

## 1. Contracts Subsystem (`src/yt_clipping/contracts/`)

Typed data schemas and abstract provider contracts enforcing decoupled, testable components.

### `models.py`
- **`RightsBasis` (Enum):**
  - `OWNED`: Content created and wholly owned by operator.
  - `EXPLICIT_PERMISSION`: Written agreement or licensing grant from creator.
  - `CREATIVE_COMMONS`: Verified CC-BY or public reuse license.
  - `OPERATOR_ASSET`: Internal operational asset cleared for processing.
- **`RightsStatus` (Enum):**
  - `VERIFIED`: Rights validated and active for processing.
  - `PENDING_REVIEW`: Awaiting operator manual audit.
  - `REJECTED`: Unauthorized asset rejected by rights gate.
  - `REVOKED`: Previously granted permission revoked.
- **`JobStage` (Enum):** Discrete stages for resumable execution:
  - `DISCOVERED`, `RIGHTS_CHECKED`, `ASSET_INGESTED`, `TRANSCRIBED`, `SEGMENTED`, `SCORED`, `REVIEWED`, `RENDERED`, `QA_VERIFIED`, `HANDED_OFF`, `FAILED`.
- **`JobStatus` (Enum):**
  - `PENDING`, `IN_PROGRESS`, `SUCCEEDED`, `FAILED`, `RETRY_PENDING`.
- **`WordTimestamp`:** Dataclass containing `word: str`, `start: float`, `end: float`, `confidence: float = 1.0`, `speaker_tag: Optional[str] = None`.
- **`TranscriptSegment`:** Contains `segment_id: int`, `start: float`, `end: float`, `text: str`, `words: List[WordTimestamp]`, `speaker_tag: Optional[str] = None`.
- **`Transcript`:** Container with `video_id: str`, `language: str`, `duration_seconds: float`, `text: str`, `segments: List[TranscriptSegment]`, `provider: str`, `model_version: str`.
- **`ScoreBreakdown`:** Multi-signal component scores:
  - `hook_score`: 0.0 to 10.0 (first 3-5 seconds strength).
  - `moment_score`: 0.0 to 10.0 (climax or revelation quality).
  - `coherence_score`: 0.0 to 10.0 (semantic standalone completeness).
  - `pacing_score`: 0.0 to 10.0 (speech rate and silence ratio).
  - `audio_energy_score`: 0.0 to 10.0 (measured acoustic volume / inflection).
  - `visual_score`: 0.0 to 10.0 (framing clarity and crop legibility).
  - `heatmap_score`: 0.0 to 10.0 (retention hotspot or replay curve match).
  - `compute_composite_score()`: Calibrated weighted composite (0 to 100).
- **`HighlightCandidate`:** Complete moment description:
  - `candidate_id: str`, `video_id: str`, `start_seconds: float`, `end_seconds: float`, `duration_seconds: float`, `score: float`, `breakdown: ScoreBreakdown`, `hook_title: str`, `suggested_description: str`, `rationale: str`, `approval_status: str`, `transcript_text: str`, `loop_affinity_score: float = 0.0`.
  - `validate_bounds(source_duration: float) -> bool`: Validates bounds safety.
- **`RenderProfile`:** Rendering configuration:
  - `name: str = "vertical_9_16"`, `width: int = 1080`, `height: int = 1920`, `aspect_ratio: str = "9:16"`, `fps: int = 30`, `vcodec: str = "libx264"`, `acodec: str = "aac"`, `crf: int = 22`, `burn_subtitles: bool = True`, `layout_mode: str = "blur_background"`, `subtitle_preset: str = "hormozi"`.
  - **CTA Overlay:** `enable_cta: bool = False`, `cta_text: str`, `cta_timing: str = "end"`, `cta_style: str = "modern_pill"`, `cta_duration: float = 3.5`, `cta_margin_bottom: int = 440`.
  - **Outro Card:** `enable_outro_card: bool = False` (strictly opt-in), `outro_duration: float = 2.5`, `outro_channel_name: Optional[str] = None`, `outro_sub_heading: str = "Thanks for watching!"`, `outro_prompt: str = "Turn on notifications for more clips!"`, `enable_outro_chime: bool = True`, `outro_chime_style: str = "soft_zen"`.
  - **Pacing Polish:** `enable_pacing_polish: bool = True`, `audio_fade_in_seconds: float = 0.02`, `audio_fade_out_seconds: float = 0.25`, `video_fade_in_seconds: float = 0.15`, `video_fade_out_seconds: float = 0.25`.
- **`RenderedClip`:** Represents completed export: `clip_id`, `job_id`, `candidate_id`, `file_path`, `file_hash`, `duration_seconds`, `width`, `height`, `manifest_path`, `rendered_at`.
- **`VideoCandidate`:** Candidate video metadata container: `video_id`, `channel_id`, `title`, `published_at`, `view_count`, `duration_seconds`, `baseline_views`, etc.
- **`HeatmapPeak`:** Represents an audience retention replay curve peak: `start_time: float`, `end_time: float`, `peak_time: float`, `intensity: float`, `prominence: float`.
- **`TrendReport`:** High-level velocity report: `video_id`, `channel_id`, `title`, `hourly_velocity`, `velocity_multiplier`, `virality_classification`, `like_to_view_ratio`, `comment_to_view_ratio`.
- **`Function compute_canonical_idempotency_key(video_id: str, start_seconds: float, end_seconds: float, rights_id: Optional[str] = None) -> str`:** Computes a canonical SHA-256 idempotency key across all pipeline operations enforcing 3-decimal fixed point rounding for deterministic repeatability.
- **`QAReport`:** Verification record: `qa_id`, `clip_id`, `status` (`PASSED`, `FAILED`, `WARNING`), `video_stream_ok: bool`, `audio_stream_ok: bool`, `duration_ok: bool`, `aspect_ratio_ok: bool`, `sar_ok: bool`, `file_size_bytes: int`, `duration_seconds: float`, `sha256_checksum: str`, `errors: List[str]`, `warnings: List[str]`, `verified_at: str`.
- **`HandoffReceipt`:** Delivery acknowledgment: `receipt_id`, `job_id`, `clip_id`, `destination_mode`, `destination_target`, `delivered_at`, `payload_hash`, `external_job_id`, `status`, `response_payload`.
- **`ClipJob`:** Durable state entity: `job_id`, `video_id`, `stage: JobStage`, `status: JobStatus`, `created_at`, `updated_at`, `payload: Dict[str, Any]`, `error_message`, `retry_count`.
- **`HeatmapPoint` & `HeatmapData`:** Normalized 100-point replay curves.

### `interfaces.py`
Abstract Base Classes (ABCs) and exceptions:
- **Exceptions:** `RightsPolicyViolationError`, `TranscriptionError`, `RenderingError`.
- **`DiscoveryProvider`:** `fetch_recent_videos(channel_id, limit)`, `get_video_metadata(video_id)`.
- **`MetricObserver`:** `record_snapshot(video_id, view_count, ...)`, `calculate_view_velocity(snapshots)`.
- **`RightsPolicy`:** `check_rights(video_id)`, `verify_rights(manifest)`, `register_rights(manifest)`.
- **`AssetProvider`:** `resolve_asset(video_id, rights_manifest)`, `probe_asset(asset_path)`.
- **`Transcriber`:** `transcribe(media_path, video_id)`.
- **`HighlightDetector`:** `detect_candidates(transcript, min_duration, max_duration)`.
- **`HighlightScorer`:** `score_candidate(candidate, transcript)`.
- **`Renderer`:** `render_clip(source_path, candidate, profile, output_dir)`.
- **`QualityVerifier`:** `verify_clip(rendered_clip, candidate)`.
- **`HandoffPublisher`:** `publish_clip(rendered_clip, candidate, rights_manifest, qa_report, dry_run)`.

---

## 2. Discovery Subsystem (`src/yt_clipping/discovery/`)

### `monitor.py`
- **Class `ChannelMonitor`:** Observes channel video uploads and metadata.
  - Primary zero-quota RSS Atom feed parser (`/feeds/videos.xml?channel_id={id}`).
  - Fallback to YouTube Data API v3 when API key is provided and quota allows.
  - Caches HTTP responses with `ETag` and `If-Modified-Since` (HTTP 304).

### `ranker.py`
- **Class `PublicMetricRanker`:** Computes public velocity rank, recency decay, and candidate prioritization.

### `outlier.py`
- **Class `OutlierMultiplier`:** Computes channel-normalized virality ratio against creator median:
  - Classifications: `BREAKOUT` ($\ge 3.0\times$), `ABOVE_AVERAGE` ($\ge 1.5\times$), `TYPICAL` ($0.7\times - 1.5\times$), `UNDERPERFORMING` ($< 0.7\times$).

### `heatmap.py`
- **Class `HeatmapAnalyzer`:** Reconstructs YouTube 100-point audience replay curves to locate peak attention zones and snap segment bounds to local retention valleys.

### `trend_analyzer.py`
- **Class `TrendAnalyzer`:** Evaluates real-time view accumulation velocity ($V_{\text{hourly}}$) and detects viral acceleration.

### `trend_scorer.py`
- **Class `TrendScorer`:** Standalone velocity and audience resonance calculator. Enforces Like-to-View Ratio ($LVR \ge 1.2\%$) and Comment-to-View Ratio ($CVR \ge 0.03\%$).

### `attribution_engine.py`
- **Class `AttributionEngine`:** Generates verified creator attribution packages and compliance descriptions for affiliate, CC, or licensed content.

### `channel_registry.py`
- **Class `ChannelRegistry`:** SQLite-backed registry of monitored creator channels with baseline views and active flags.

### `channel_watcher.py`
- **Class `ChannelWatcher`:** High-level controller for creator registration, handle resolution, live sweeps, and feed testing.

### `daemon.py`
- **Class `DiscoveryDaemon`:** Continuous background channel polling service handling graceful OS signal shutdown (`SIGINT`, `SIGTERM`).

### `pinger_daemon.py`
- **Class `PingerDaemon`:** Zero-quota background daemon with optional local WebSub push notification HTTP server.

### `quota_governor.py`
- **Class `APIQuotaGovernor`:** Daily YouTube API v3 budget tracker enforcing hard limits (default 10,000 units/day) with cost estimation.

---

## 3. Ingestion Subsystem (`src/yt_clipping/ingestion/`)

### `asset_provider.py`
- **Class `LocalAssetProvider` (implements `AssetProvider`):**
  - **Rights Gate Enforcement:** Enforces valid `RightsManifest` before resolving or downloading any asset. Raises `RightsPolicyViolationError` if rights status is not `VERIFIED`.
  - **Media Download:** Integrates `yt-dlp` for local 1080p source media acquisition with best-audio extraction.
  - **Stream Probing:** Inspects containers using `ffprobe`, falling back to `cv2.VideoCapture` and native headers to retrieve duration, resolution, codecs, and stream properties.
  - **Provenance Checksum:** Computes SHA-256 asset checksums for immutable provenance tracking.
- **Function `extract_youtube_video_id(url_or_id: str) -> str`:** Robust parser extracting canonical 11-character video IDs from full URLs (`watch?v=`, `shorts/`, `youtu.be/`, `live/`) or bare strings.
- **Exceptions:** `MediaProbeError`, `AssetIngestionError`.

---

## 4. Rights Subsystem (`src/yt_clipping/rights/`)

### `gate.py`
- **Class `LocalRightsPolicy` (implements `RightsPolicy`):**
  - Enforces hard transactional rights gate in SQLite (`data/jobs.db`) with JSON ledger mirror (`data/rights_ledger.json`).
  - `check_rights(video_id: str) -> RightsManifest`: Returns manifest or empty `REJECTED` manifest if unregistered.
  - `verify_rights(manifest: RightsManifest) -> bool`: Validates `status == VERIFIED` and verifies expiration timestamp (`valid_until`).
  - `register_rights(manifest: RightsManifest) -> None`: Inserts or updates verified rights record.
  - `revoke_rights(video_id: str, reason: str) -> None`: Revokes permission, preventing any subsequent processing.

---

## 5. Transcription & Alignment (`src/yt_clipping/transcription/`)

### `transcriber.py`
- **Class `LocalTranscriber` (implements `Transcriber`):**
  - Offline speech-to-text using `faster-whisper` with int8 quantization on GPU (`float16`) or CPU (`int8`).
  - On-disk JSON caching under `data/transcripts/{video_id}.json`.
  - Automatic memory cleanup (`gc.collect()` and `torch.cuda.empty_cache()`) on OOM.
- **Class `DiarizationAnnotator`:** Heuristic speaker diarization layer assigning speaker turns based on acoustic pause thresholds.
- **Exception `TranscriptionError`:** Raised when speech transcription fails across all fallbacks.

### `alignment.py`
- **Class `AlignmentEngine` (ABC):** Sub-second word alignment contract.
- **Class `FasterWhisperAlignmentAdapter`:** Lightweight offline adapter enforcing strict monotonicity, boundary clamping, and minimum word durations (40ms) with zero extra neural dependencies.
- **Class `WhisperXAlignmentAdapter`:** Phoneme-level wav2vec2 forced alignment via WhisperX with automatic VRAM safety checks and fallback to `FasterWhisperAlignmentAdapter`.
- **Function `get_alignment_engine(...) -> AlignmentEngine`:** Factory function resolving alignment engines.

---

## 6. Detection Subsystem (`src/yt_clipping/detection/`)

### `segmenter.py`
- **Class `ContextAwareSegmenter` (implements `HighlightDetector`):**
  - Tokenizes speech transcripts into semantically coherent 15–60s segments aligned strictly with sentence boundaries.

### `arc_detector.py`
- **Class `ArcDetector`:**
  - High-retention narrative arc detection enforcing "Strong Start, Strong End".
  - Rejects weak starter words (`and`, `so`, `because`, `uh`) and trailing sentence fragments.
  - Integrates acoustic volume energy, motion energy, and speech cadence modulation.

### `sentence_classifier.py`
- **Class `SentenceClassifier`:**
  - Classifies sentences into narrative roles: `HOOK`, `CONTEXT`, `ESCALATION`, `REVELATION`, `PAYOFF`, `FILLER`, `SPONSOR`.
  - Enforces hard sponsor segment exclusion.

### `deadair.py`
- **Class `DeadAirPruner`:**
  - Detects inter-word pauses $> 0.35\text{s}$ and computes micro-cut jump cuts or pacing penalties.
  - Identifies conversational fillers (`"um"`, `"uh"`, `"like"`, `"you know"`, `"basically"`).
  - Detects speaker false starts via prefix matching.

### `short_viability.py`
- **Class `ShortViabilityValidator`:**
  - Enforces "Survives Without Context" criteria: Complete Thought Opening, Narrative Turn, and Definitive Payoff.
  - Computes `loop_affinity_score` (0–100) assessing syntactic and semantic continuity between opening and closing lines.

### `audio_energy.py`
- **Class `AudioEnergyAnalyzer`:** Computes RMS volume envelopes, audio peak densities, and vocal laugh/energy spikes.
- **Class `MotionEnergyAnalyzer`:** Analyzes video frame optical flow and motion energy.
- **Class `AdaptiveCadenceScorer`:** Measures tempo shifts and cadence modulation across speech intervals.

### `dedupe.py`
- **Function `suppress_overlapping_candidates(candidates, iou_threshold=0.35) -> List[HighlightCandidate]`:** Non-Maximum Suppression (NMS) over temporal candidate intervals based on temporal Intersection-over-Union (IoU).

---

## 7. Scoring Subsystem (`src/yt_clipping/scoring/`)

### `scorecard.py`
- **Class `ExplainableScorecardScorer` (implements `HighlightScorer`):**
  - Deterministic scoring engine computing 0–100 highlight retention scores with transparent weight breakdowns.

### `gemini_provider.py`
- **Class `GeminiHighlightDiscoveryProvider` (implements `HighlightDetector`, `HighlightScorer`):**
  - Multimodal cloud highlight discovery leveraging Google Gemini 1.5 Flash.
  - Gated strictly by environment variables; automatic graceful degradation to local scorecard when unconfigured or offline.

### `metadata_generator.py`
- **Class `MetadataGenerator`:** Generates short-form titles, descriptions, hashtags, and 3 hook variations (question, bold statement, curiosity gap).
- **Dataclass `ClipMetadata`:** Encapsulates generated metadata package.

### `packaging_linter.py`
- **Class `PackagingLinter`:** Enforces viral packaging quality standards:
  - Mobile truncation safety: Main hook $\le 40$ chars; hard cap at 60 chars.
  - Stop-word front loading prevention: Flags generic opening phrases.
  - Click-surface deduplication: Ensures title and thumbnail text do not mirror each other identically.
  - Buzzword elimination: Replaces vague clickbait with concrete metrics or proper nouns.
- **Dataclasses `LintIssue`, `PackagingLintReport`:** Linter findings and suggestions.

---

## 8. Podcast Engine Subsystem (`src/yt_clipping/podcast/`)

### `pipeline.py`
- **Class `PodcastShortMaker`:** Complete orchestration pipeline for podcast videos:
  - Ingests wide two-shot or multi-camera footage.
  - Runs shot detection, active speaker diarization, dynamic layout switching, and subtitle generation.
  - Renders broadcast-grade 9:16 vertical shorts.

### `config.py`
- **Dataclass `PodcastLayoutConfig`:** Layout mode (`hybrid`, `stacked_always`), host position, divider dimensions, CTA overlay config, and preview settings.

### `layout.py`
- **Functions `build_podcast_split_filtergraph` & `build_podcast_closeup_filtergraph`:** Constructs optimized FFmpeg filtergraphs for stacked 9:8 split-screen and director close-ups.
- **Function `escape_libass_path(path: str) -> str`:** Escapes Windows/POSIX file paths for libass filter strings.

### `shot_detector.py`
- **Class `PodcastShotDetector`:** CV2 frame difference and facial layout analyzer classifying shots as `SPLIT_HOST_GUEST`, `SOLO_HOST`, `SOLO_GUEST`, or `WIDE_TWO_SHOT`.

### `diarization.py`
- **Class `SpeakerDiarizer` (ABC):** Unified diarization contract.
- **Class `AcousticEnergyDiarizer`:** Zero-VRAM, 100% offline acoustic energy and spectral centroid clustering.
- **Class `PyannoteDiarizerAdapter`:** Neural voice clustering via Pyannote with automatic acoustic fallback.
- **Function `get_speaker_diarizer(...) -> SpeakerDiarizer`:** Factory function.

### `captions.py`
- **Class `PodcastSubtitleGenerator`:** Center-divider aligned ASS subtitle generator (`MarginV = height // 2`).

### `cli.py`
- **Function `main()`:** Dedicated standalone CLI for podcast short creation (`python -m src.yt_clipping.podcast.cli`).

---

## 9. Rendering & Polish Subsystem (`src/yt_clipping/rendering/`)

### `renderer.py`
- **Class `FFmpegRenderer` (implements `Renderer`):**
  - Multi-layout rendering engine: `blur_background`, `active_speaker`, `crop_center`, `split_screen`.
  - Broadcast audio anti-pop fades (20ms half-sine `afade` onset and 250ms outro fade) and video transitions.
  - Hardware acceleration with NVIDIA NVENC (`h264_nvenc`) and CPU fallback (`libx264`).
  - Integrated CTA overlay burning and dedicated animated outro card appending.

### `outro_card.py`
- **Class `OutroCardEngine`:** Orchestrates the generation of dedicated animated outro cards:
  - Generates animated ASS script for pulsing subscribe button and rocking bell icon.
  - Renders standalone outro video with synchronized chime sound effect.
  - Concatenates main clip and outro card into seamless master MP4 with format normalization.
- **Dataclass `OutroCardConfig`:** Configuration for outro duration, channel name, text, and sound style.
- **Function `synthesize_bell_chime(output_wav_path, duration=1.8, sample_rate=44100, f0=523.25, chime_style="soft_zen") -> str`:**
  - Local mathematical audio synthesis using pure Python standard library (`math`, `wave`, `struct`).
  - Zero external APIs or cloud dependencies.
  - Sound styles: `"soft_zen"` (warm marimba/celesta, C5+G5 fifth, ~ -12.5 dB peak), `"soft_double"`, `"classic_bell"`.

### `cta_overlay.py`
- **Class `CTAOverlayEngine`:** Self-contained animated Call-to-Action overlay engine.
  - Enums: `CTAStyle` (`MODERN_PILL`, `NEON_BANNER`, `MINIMAL`), `CTATiming` (`END`, `INTRO`, `PERSISTENT`).
  - Dataclass `CTAConfig`: Parameters for text, style, timing, duration, and placement.
  - Safe-zone geometry avoiding TikTok/Reels UI buttons and podcast center dividers.
  - Libass vector pill rendering (`\move` keyframes, `\fad` alpha fades) with native `drawbox`/`drawtext` fallback.

### `face_tracker.py`
- **Class `FaceFocusedFramer`:** Active speaker dynamic video framing engine with YuNet ONNX neural face detector and Haar cascade fallback.
- **Class `ConstrainedTrajectoryOptimizer`:** AutoFlip-inspired 1D camera path smoother using SciPy banded linear solvers or forward-backward kinematic velocity/acceleration clamps ($v_{\text{max}} \le 450 \text{ px/s}$, $a_{\text{max}} \le 750 \text{ px/s}^2$).
- **Dataclasses `TrajectoryConfig`, `KinematicSegment`, `TrajectoryResult`:** Trajectory optimization schemas.

### `b_roll.py`
- **Class `BRollOverlayEngine`:** Automated B-roll video overlay engine.
  - Analyzes transcript for extended speaker monologues ($>4\text{s}$).
  - Slices and inserts contextual stock video overlays with 0.25s cross-fades and $0.4\times$ audio ducking.
- **Dataclasses `BRollConfig`, `MonologueInterval`, `BRollOverlayResult`:** B-roll schemas.

### `subject_segmenter.py`
- **Class `SubjectSegmenter`:** Deep learning subject finding and segmentation engine powered by YOLOv8 detection & instance segmentation models.

### `captions.py`
- **Class `SubtitleGenerator`:** Word-synced animated ASS subtitle generator:
  - Presets: `hormozi` (bold yellow bounce), `beast_bounce` (high-energy pop), `neon_cyber` (cyan glow), `karaoke_gold`, `bold_social`.
  - Platform safe zones avoiding TikTok/Reels UI buttons.

---

## 10. Quality Assurance Subsystem (`src/yt_clipping/qa/`)

### `verifier.py`
- **Class `MediaQualityVerifier` (implements `QualityVerifier`):**
  - Post-render validation ensuring exact 1080x1920 dimensions, 9:16 Display Aspect Ratio (DAR), 1:1 Sample Aspect Ratio (SAR), non-zero audio streams, duration constraints, and valid container decodability.
  - Generates comprehensive `QAReport` with SHA-256 integrity checksums.
  - Multi-tier fallback hierarchy when `ffprobe` is omitted (OpenCV + container inspection).

---

## 11. Publisher Subsystem (`src/yt_clipping/publisher/`)

### `adapter.py`
- **Class `DualModeAutopostPublisher` (implements `HandoffPublisher`):**
  - Delivers approved, rights-cleared clips to external autopost systems.
  - Hard gate: strictly rejects any clip failing rights verification or QA validation.
  - Modes:
    1. `watched_folder`: Atomic local handoff moving video MP4, sidecar JSON metadata, and subtitle files into target delivery folder.
    2. `webhook`: HMAC-SHA256 signed HTTP REST webhook dispatch with retry policy and dead-letter queue (DLQ) logging.

---

## 12. Pipeline Orchestration Subsystem (`src/yt_clipping/orchestration/`)

### `pipeline.py`
- **Class `ClippingPipeline`:** Master controller connecting all 9 stages:
  - Stage 1: Rights policy verification (`LocalRightsPolicy`).
  - Stage 2: Media asset resolution and header probing (`LocalAssetProvider`).
  - Stage 3: Speech transcription and forced alignment (`LocalTranscriber` + `AlignmentEngine`).
  - Stage 4: Candidate moment segmentation (`ContextAwareSegmenter` / `ArcDetector`).
  - Stage 5: Multi-signal scorecard ranking (`ExplainableScorecardScorer`).
  - Stage 6: Short viability audit & loop continuity scoring (`ShortViabilityValidator`).
  - Stage 6b: Broadcast hook pacing polish (dead-air onset trim to ~0.10s, outro word protection).
  - Stage 7: Video rendering (`FFmpegRenderer` + `CTAOverlayEngine` + `OutroCardEngine`).
  - Stage 8: Media quality verification (`MediaQualityVerifier`).
  - Stage 9: Autopost publisher handoff (`DualModeAutopostPublisher`).

### `state_machine.py`
- **Class `JobJournal`:** Crash-resilient checkpoint ledger recording stage transitions, telemetry, and error recovery states in SQLite (`data/jobs.db`). Supports resuming failed jobs from the last validated stage.

### `queue.py`
- **Class `JobQueue`:** Durable SQLite WAL job queue featuring priority leases, atomic transitions, exponential backoff, and concurrency governors.
- **Enum `JobPriority`:** `CRITICAL = 1`, `HIGH = 2`, `NORMAL = 3`, `LOW = 4`.

### `db.py`
- **Class `DatabaseManager`:** Thread-safe SQLite database manager enforcing Write-Ahead Logging (WAL) mode, connection pooling, and schema migrations.

### `storage_manager.py`
- **Class `StorageManager`:** Manages file paths, temporary workspace directories, asset lifecycles, and cache retention pruning.

---

## 13. Reporting Subsystem (`src/yt_clipping/reporting/`)

### `html_report.py`
- **Class `ExecutiveReportGenerator`:** Generates standalone, self-contained executive HTML diagnostic and telemetry reports (`report.html`) containing:
  - Video and creator metadata.
  - Multi-signal scorecard radar charts.
  - Audience retention replay curves.
  - QA verification checklists.
  - Autopost delivery receipts.

---

## 14. Model Context Protocol Subsystem (`src/yt_clipping/mcp/`)

### `server.py`
- **Class `MCPServer`:** Native JSON-RPC 2.0 stdio server conforming to the `2024-11-05` MCP specification.
  - Exposes 7 granular tools for LLM agent integration:
    1. `discover_channel_uploads`: Search, RSS ingest, and outlier ranking.
    2. `verify_source_rights`: Non-bypassable transactional rights checks.
    3. `analyze_replay_heatmap`: Reconstruct audience retention replay curves.
    4. `evaluate_highlight_candidates`: Extract candidate moments with explainable scoring.
    5. `render_vertical_clip`: 9:16 layout compositing, kinetic subtitles, CTA, and outro cards.
    6. `inspect_job_status`: Durable task state tracking and progress reporting.
    7. `list_available_tools`: Tool inventory discovery.
  - Strict stderr diagnostic logging isolation ensuring clean, parseable JSON-RPC on stdout.

---

## 15. Command-Line Interface (`src/yt_clipping/cli/`)

### `master_cli.py`
- **Function `build_parser() -> argparse.ArgumentParser`:** Constructs the master CLI argument parser with 21 operational commands and nested subparsers.
- **Function `main() -> None`:** Primary entrypoint handling UTF-8 stdout configuration, argument parsing, and command dispatch.

---

## 16. Audio Subsystem (`src/yt_clipping/audio/`)

### `tts_engine.py`
- **Class `TTSEngine`:** Voiceover speech synthesis supporting high-quality neural voices via Edge-TTS and offline SAPI5 fallback via `pyttsx3`. Includes audio ducking filters to overlay narrations onto video clips.

---

## 17. Root Convenience Tools

Convenience terminal scripts at the repository root delegating to discovery subsystem:
- `attribution_engine.py`: Direct CLI for creator attribution packages.
- `channel_watcher.py`: CLI for creator registry management and live sweeps.
- `pinger_daemon.py`: High-velocity virality alert and RSS pinger daemon.
- `trend_scorer.py`: Standalone velocity and virality evaluation tool.
