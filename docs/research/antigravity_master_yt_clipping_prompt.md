# Antigravity Master Task: Build a Research-Driven, Multi-Agent YouTube Clipping Intelligence Platform

## ROLE AND MISSION

Act as the lead engineering orchestrator for a multi-agent software team. Research the open-source ecosystem, inspect and clone the most relevant repositories, identify reusable components and engineering patterns, and then build a coherent, tested master repository for automated video discovery, highlight selection, clip production, and handoff to an existing autopost automation.

This is not a request to make a shallow demo or merely write a report. Execute a disciplined research-to-implementation workflow. Use parallel specialist agents where possible, give each agent an isolated branch/worktree or clearly separated research area, reconcile their findings, and integrate their work through a single architecture owned by the lead agent.

**Product goal:** discover promising recent videos from a configurable list of creators and topics; rank videos using public, compliant signals; find and rank likely high-value moments inside authorized source videos; produce technically verified vertical clips with captions and appropriate framing; and hand approved output to an existing autopost system through a stable adapter. The platform should eventually learn from the performance of clips it is authorized to measure.

**Do not replace or rewrite the existing autopost automation.** Treat it as an external downstream system. Build a documented adapter (webhook/API, command-line handoff, or watched output directory—choose after inspecting whatever integration details are actually available) with dry-run behavior by default.

## OPERATING PRINCIPLES

1. **Research before choosing.** Verify repository contents, current default branch, recent activity, tests, dependencies, license, and architecture. Do not rely on names, stars, README claims, or model memory alone.
2. **Build one system, not a pile of repos.** Do not blindly merge entire codebases. Reuse suitable libraries and discrete modules; borrow architecture patterns only where copying code is not appropriate. All integrations must have clear interfaces and tests.
3. **Honor licenses and provenance.** Before copying any upstream code, record its source repository, commit SHA, file paths, license, copyright notices, and required attribution. Do not copy code with unclear, absent, incompatible, GPL, or AGPL licensing into the core without a documented compatibility decision. For uncertain components, isolate them as optional references/adapters and report the issue; do not silently assume compatibility. Preserve license and NOTICE files where required. Do not remove upstream attribution.
4. **Respect YouTube and creator rights.** Use official YouTube Data API capabilities and documented channel RSS feeds where appropriate for discovery. Do not scrape undocumented endpoints, evade access controls, bypass DRM, or assume that a publicly viewable video is free to download or repost. Model explicit rights/authorization for every source asset. Download and render only assets the operator owns, has explicit permission to process, or is otherwise lawfully authorized to use. When authorization is absent or unclear, the system may store allowed discovery metadata and a review task, but must not download, render, or publish the video. Verify current official API and platform policies during implementation and cite them in the compliance notes.
5. **Separate measured data from predictions.** Public view counts do not reveal the most-watched timestamp inside a video. Use actual retention data only when the authenticated channel owner or an authorized account can provide it. Otherwise call the output a *predicted highlight score*, never an actual view/retention peak.
6. **Preserve user data and systems.** Inspect the current workspace before modifying it. Do not overwrite existing files, secrets, local automations, or repositories. Do not delete anything or push to a remote/main branch without explicit authorization. Keep API keys out of source control, logs, test fixtures, reports, and agent outputs.
7. **Deliver working software.** Do not stop after repository research or planning. Implement a small but end-to-end vertical slice, run tests, fix failures, and document any remaining limitations. If the full scope cannot be completed in one run, leave a coherent working increment with explicit next steps and no false claims.

## MULTI-AGENT PLAN

The lead/orchestrator owns the architecture, task graph, interface contracts, integration, final testing, and final report. Delegate these workstreams in parallel, preferably in isolated worktrees or separate branches. Avoid having multiple agents edit the same files at the same time.

### Agent A — Open-source discovery and repository auditor

Find and compare at least 40 repositories across these categories: AI highlight detection, video clipping, transcription/word timestamps, speaker diarization, subject/face tracking and vertical reframing, scene detection, rendering/caption systems, YouTube channel discovery/trend analytics, job queues/recovery, quality assurance, and publishing adapters. Start with the seed list below, then find further candidates based on actual technical merit.

For every shortlisted repo inspect the README, LICENSE, dependency manifest, relevant source modules, tests, commit history/activity and known open issues. Create `docs/research/repository-matrix.md` containing: purpose, URL, current commit SHA, license, stack, activity/maintenance evidence, test quality, useful components, limitations, integration cost, and adopt/adapt/reference/reject recommendation. Rank candidates by evidence, not stars alone.

Clone the selected repositories at shallow depth into a research-only directory such as `research/upstream/`, outside production package/runtime paths. Keep each upstream clone intact and read-only. Never copy its `.git` directory into the master repository. Exclude clones from container images, distribution bundles, and normal application imports. Do not execute upstream install scripts or application code before checking for suspicious commands and dependency risks.

### Agent B — License, provenance, and policy auditor

Create `docs/research/license-and-provenance.md` and `THIRD_PARTY_NOTICES.md` as needed. Make an explicit component-by-component decision: `safe to integrate`, `integrate with conditions`, `pattern/reference only`, or `blocked pending review`. Track license text, attribution, source file paths, upstream commit SHA, local modifications, and any required notices. Do not infer a project's license from badges alone; inspect the actual license file and file-level notices. Check transitive dependencies and FFmpeg build/license implications. Document YouTube API terms, developer-policy requirements, permitted metadata handling, downloading restrictions, copyright/permission gates, and platform publication considerations. Isolate any uncertain component rather than blocking unrelated work.

### Agent C — Discovery, channel monitoring, and video intelligence

Design the source registry and compliant metadata ingestion layer. Support configurable creators/channels, niches/keywords, regions where permitted, lookback windows, and prioritization rules. Use the official YouTube Data API and documented feeds as appropriate; add quota-aware polling, caching, retry/backoff, deduplication, and observed metric timestamps. Track snapshots of public metrics over time where policy permits so the system can calculate observed view velocity (for example, views gained per hour since the previous observation), not pretend to know historical velocity from a single snapshot.

Create a configurable ranking score that combines recency, total public views, observed view velocity, engagement signals where available, and a per-channel baseline to avoid simply favoring the largest creators. Explain each score component and its limitations. Store source URL, creator/channel, publication time, retrieval time, metrics timestamp, authorization/rights state, and discovery rationale. Include API quota accounting and a policy-aware data-retention strategy.

### Agent D — Transcript, multimodal analysis, and highlight intelligence

Design a pluggable pipeline for transcription, timestamps, candidate segmentation, and ranking. Evaluate local and hosted options rather than hard-coding a single vendor. Where suitable, evaluate faster-whisper, WhisperX, OpenAI Whisper, and pyannote-audio for word timestamps/diarization; use a compatible scene/visual analysis adapter only where it adds measurable value.

Create candidates that are complete, context-preserving moments rather than arbitrary fixed windows. Detect sentence boundaries, pauses, topic/scene changes, speaker turns and overlapping moments. Use transcript chunks with overlap for long videos, but deduplicate overlapping candidate intervals. Score at least: opening-hook strength, standalone clarity, narrative/payoff completeness, novelty or insight, emotional/timing signal, audio energy, speaking pace, visual legibility, duration fit, and context dependence. Use actual visual/audio signals only when measured; never invent missing metrics. Return a structured scorecard with per-signal values, confidence/unknown fields, a short human-readable rationale, start/end timestamps, title/hook suggestions, and source provenance.

Make the scoring model provider-independent. Define interfaces for hosted LLMs (including Claude/Gemini/OpenAI-compatible endpoints when configured) and local models. Validate all LLM outputs against a typed schema, retry malformed responses safely, support timeouts/cost tracking, and provide deterministic fallback behavior. Keep API credentials in environment variables or a secret store. Do not send complete video files or transcripts to a provider without an explicit configured privacy decision. Where genuine channel-retention analytics are available through an authorized account, keep those measured values distinct from model predictions and use them as optional training/evaluation labels.

### Agent E — Media pipeline, rendering, and clip quality

Build robust asset validation, media probing, trimming, reframing, captions, and export. Evaluate FFmpeg/ffprobe as the rendering and validation backbone; assess PySceneDetect, MediaPipe, and other libraries only where the source and license support their use. Treat MoviePy as optional, not automatically the core renderer. Support a configurable vertical output profile (default 9:16), selectable duration targets, sentence-safe cut points, word-synced captions, subtitle-safe margins, audio preservation/normalization, and speaker/subject-aware framing. For multi-speaker video, support a reasonable fallback such as split-screen or full-frame letterboxing when a single crop would lose essential context.

Use render manifests and deterministic output names. Render to temporary paths first; do not mark a clip complete until ffprobe and post-render validation confirm that the file is readable, has expected streams/duration/aspect ratio, has non-trivial size, and passes available audio/video checks. Use atomic promotion to the final output path so a failed render never replaces a good result. Report structural failures as errors and softer visual/audio problems as warnings. Avoid expensive full-resolution analysis when low-resolution sampling is sufficient, and provide CPU/GPU-aware fallback behavior.

### Agent F — Reliability, orchestration, data model, and testing

Define explicit typed contracts and durable state transitions for the pipeline. Include idempotent jobs, deduplication keys, checkpoint/restart semantics, retry limits with exponential backoff, cancellation, structured logs, per-stage timing, error classification, artifact manifests, and a dead-letter/failed-job view. Do not let a failed analytics or notification event break a clip-processing job. Keep secrets out of serialized job state. Ensure concurrent tasks cannot overwrite each other's outputs or publish duplicates.

Choose the simplest maintainable stack after inspecting the candidates. Prefer a modular Python core with clear interfaces; use a small local database for MVP if suitable and preserve a clean path to a production database/queue. Do not add Redis, Kubernetes, a frontend framework, or a multi-service deployment unless the evaluated workload justifies it. Provide a reproducible development environment, pinned/declared dependencies, configuration examples, migration strategy, and health/readiness checks.

Build automated tests covering timestamp math, sentence-safe boundaries, clip overlap/deduplication, score normalization, rights gating, idempotent job submission, retries/recovery, transcript schema validation, render verification, output file safety, provider fallbacks, and the autopost adapter. Use mock providers and small test fixtures; do not make tests download third-party videos or incur real paid API calls. Add one end-to-end synthetic/local-fixture test proving that an authorized input can flow through transcript, candidate selection, render, QA, and handoff/dry-run.

### Agent G — Existing autopost integration and operational UX

Inspect the workspace for the existing autopost automation only if it is available in the current environment. First read its docs and interfaces; do not change its internals. Implement an adapter with a documented contract, authentication option, idempotency key, metadata payload, delivery receipts, retry behavior, and dry-run mode. If the automation cannot be inspected, define a stable generic webhook/API contract and a watched-folder/JSON-manifest fallback, but do not invent that an integration has been tested against a system that was unavailable.

Build a lightweight review interface only if needed for an operationally useful MVP. Operators should be able to inspect source rights, candidate timestamps, preview/score rationale, approve/reject candidates, rerender, and see queue status. Automatic handoff must be disabled for sources without verified authorization and must not post publicly during development. Keep review and publishing actions auditable.

## SEED REPOSITORIES TO AUDIT

Treat this as a starting shortlist, not a pre-approved copy list. Verify current status, source code, licenses, commits and tests before adoption.

**Full clipping/pipeline candidates**
- https://github.com/mutonby/openshorts — OpenShorts (MIT reported in the repository metadata; verify actual files). Candidate scaffold and full-pipeline reference.
- https://github.com/fralapo/clippyme — ClippyMe (MIT reported; verify). Candidate reference for channel monitoring, durable jobs, reframing and QA.
- https://github.com/kleZ799/clipmint — ClipMint (MIT reported; verify). Candidate reference for scoring, scorecards and performance feedback.
- https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator — AI YouTube Shorts Generator (MIT reported; verify). Candidate for transcript highlight selection and deduplication.
- https://github.com/NaufalRizqullah/opensource-clipping — Open-source Clipping (MIT reported; verify). Candidate for face tracking, split-screen, captions and uploader patterns.
- https://github.com/GrepCut/OpenClipper — OpenClipper (MIT reported; verify). Candidate for local-first rendering/reframing UX.
- https://github.com/Chamanrajragu/purffle-shorts — PurffleShorts (MIT reported; verify). Review only the relevant podcast-clipping and pipeline patterns; avoid unrelated synthetic/faceless-video scope.
- https://github.com/gyoridavid/short-video-maker — Short Video Maker (MIT reported; verify). Candidate for REST/MCP integration patterns; its core purpose is text-driven video generation, so adopt selectively.
- https://github.com/FujiwaraChoki/supoclip — SupoClip (AGPL-3.0 reported; verify). Architecture and tests may be useful, but do not copy its code into core without an explicit licensing decision.
- https://github.com/Anil-matcha/ai-clipping-comfyui — investigate if relevant after verifying availability and scope.

**Discovery, monitoring, trend ranking**
- https://github.com/gpsyrou/tube-virality — Tube Virality (MIT reported; verify). Candidate for API-based trend collection and historical observations.
- https://github.com/thevops/youtube-tracker — YouTube Tracker (MIT reported; verify). Candidate for feed polling and duplicate suppression.
- https://github.com/darshanabk/YouTube-Trends — YouTube Trends; verify license, freshness, and implementation depth before use.
- https://github.com/FassihShah/YT-Videos-Agent — YT Videos Agent (MIT reported; verify). Candidate for agent approvals and YouTube API integration.
- Search further for maintained YouTube Data API examples, channel RSS monitors, quota-aware metadata collectors, and creator analytics tools.

**Core technical building blocks**
- https://github.com/SYSTRAN/faster-whisper — transcription (MIT reported; verify).
- https://github.com/m-bain/whisperX — word-level alignment/diarization workflow (BSD-2-Clause reported; verify).
- https://github.com/openai/whisper — transcription reference (MIT reported; verify).
- https://github.com/pyannote/pyannote-audio — speaker diarization components (MIT reported; verify exact dependencies/model terms).
- https://github.com/Breakthrough/PySceneDetect — scene-cut detection (BSD-3-Clause reported; verify).
- https://github.com/google-ai-edge/mediapipe — visual tracking/ML utilities (Apache-2.0 reported; verify).
- https://github.com/WyattBlue/auto-editor — silence-aware editing (Unlicense reported; verify current repo and license).
- https://github.com/yt-dlp/yt-dlp — media downloader (Unlicense reported; verify and review applicable platform terms before any use).
- https://ffmpeg.org/ — rendering/probing backbone; document the exact FFmpeg build and licensing configuration.
- https://github.com/Zulko/moviepy and https://github.com/kkroening/ffmpeg-python — optional orchestration wrappers; benchmark and use only if they simplify the implementation.

For each seed project, record the actual commit SHA and the date inspected. Re-run the search for better or newer candidates where a seed is stale, weak, unmaintained or irrelevant. Do not claim to have reviewed a repository beyond the files actually inspected.

## TARGET ARCHITECTURE AND DATA CONTRACTS

First evaluate whether a candidate repository can safely serve as the scaffold. If so, document why and remove or isolate unrelated product-specific code. Otherwise build a clean modular core and port only justified components.

The final architecture should have small replaceable interfaces similar to:

- `DiscoveryProvider`: returns normalized candidate videos and source metadata.
- `MetricObserver`: records timestamped public metric snapshots where policy permits.
- `RightsPolicy`: checks authorization state before any media retrieval, rendering or publishing.
- `AssetProvider`: resolves an authorized local/source asset and records provenance.
- `Transcriber`: returns transcript text, segments, words, timestamps, language and provider metadata.
- `HighlightDetector`: returns candidate time intervals with evidence and confidence.
- `HighlightScorer`: returns an explainable scorecard, including unknown/unavailable signals.
- `Renderer`: renders a selected interval into a configured clip profile.
- `QualityVerifier`: checks the actual rendered file and emits errors/warnings.
- `HandoffPublisher`: sends only approved, rights-cleared clips to the existing autopost system.

Use typed data models for at least `CreatorSource`, `VideoCandidate`, `MetricSnapshot`, `RightsManifest`, `Transcript`, `WordTimestamp`, `HighlightCandidate`, `ScoreBreakdown`, `ClipJob`, `RenderedClip`, and `HandoffReceipt`. Keep time units explicit, normalize timestamps to seconds, make intervals half-open where practical (`start <= t < end`), and test boundary rounding. Each final clip must have a provenance manifest: source video ID/URL, creator, rights basis, input asset hash, source duration, start/end time, transcript/model versions, score and component evidence, render settings, output checksum, QA report, and handoff status.

Suggested flow:

`discover -> filter -> rights-check -> authorized asset resolution -> transcribe -> segment -> score -> deduplicate -> review/approval -> render -> QA -> handoff -> outcome feedback`

A rights-check failure must stop the pipeline before downloading, rendering, or handoff. A QA failure must block handoff. Handoff retries must be idempotent.

## EXECUTION PHASES

### Phase 0 — Inspect and protect the workspace
- Locate the current repository/root and inspect existing files, git state, existing autopost documentation, runtime, test commands and secrets-handling practices.
- Do not overwrite uncommitted work. Create a new branch/worktree or a new project directory as appropriate.
- Write `docs/research/project-baseline.md` with the workspace findings and assumptions.

### Phase 1 — Broad research and cloning
- Find 40+ candidate repositories across the defined categories.
- Shortlist the most relevant projects, inspect their code, tests, licenses and activity, and shallow-clone the selected 12–20 into `research/upstream/` or an adjacent research workspace.
- Generate repository matrix, component map, license/provenance ledger and an evidence-based shortlist.
- Publish a recommendation for scaffold-vs-clean-room architecture. Do not spend the entire task on a repository list.

### Phase 2 — Architecture and interfaces
- Define the MVP scope, diagrams, typed schemas, provider interfaces, rights gates, state machine, artifact paths and acceptance tests.
- Record important trade-offs as short ADRs under `docs/adr/`.
- Verify that agents agree on contracts before implementing in parallel.

### Phase 3 — Implement the vertical slice
Build an executable end-to-end path using a local test fixture or operator-authorized input:
1. ingest a configured source record;
2. persist normalized video metadata and rights state;
3. obtain or load a transcript;
4. generate timestamped candidate intervals and explainable rankings;
5. allow a selected candidate to render in a 9:16 profile with captions;
6. validate the exported clip;
7. create a handoff manifest and send it to a mocked/dry-run autopost adapter.

A minimal reliable vertical slice is more important than a large amount of unintegrated code.

### Phase 4 — Add discovery and scoring quality
- Implement API/feed-based discovery, snapshots, recency/velocity ranking, channel-normalized signals, deduplication and quota budgeting.
- Improve highlight detection, boundaries, scorecards, provider fallbacks and candidate overlap suppression.
- Add evaluation fixtures and quality thresholds. Maintain a small manually labeled validation set from content the operator is authorized to process. Report precision/recall or ranking agreement where ground truth exists; do not invent accuracy numbers.

### Phase 5 — Reliability and operations
- Add retry/checkpoint recovery, job idempotency, logging, status reporting, config validation, resource limits and output QA.
- Add an operational view or CLI sufficient to find failed jobs, preview candidate timestamps, inspect rights, approve/reject, and rerender.
- Ensure no publicly visible upload occurs unless the downstream autopost system is deliberately enabled by the operator.

### Phase 6 — Integration, tests, documentation
- Integrate all agent branches/worktrees after interface review. Resolve conflicts centrally; run formatting, type checks, unit/integration/end-to-end tests and security/dependency scans available in the environment.
- Test CPU mode and GPU mode only if hardware is available. If an API key or service is absent, test with mocks and clearly report that live behavior was not verified.
- Provide `.env.example` with placeholders only, setup scripts, a quickstart, architecture docs, sample config, troubleshooting, data lifecycle/policy notes and autopost adapter documentation.
- Verify the repository can be set up from a clean environment using documented commands.

## DEFINITION OF DONE

The task is complete only when the following are true or each unmet item is explicitly recorded as a blocker:

- A research matrix covers at least 40 candidates and explains the final chosen components.
- Selected repositories were actually cloned and inspected; their upstream commit SHAs and licenses are recorded.
- No upstream code was incorporated without license/provenance review and required notices.
- The master repository has a documented architecture and replaceable provider interfaces.
- The rights gate prevents unauthorized assets from entering download/render/handoff stages.
- Public metadata, actual retention data, and predicted highlight scores are clearly distinguished.
- At least one local/authorized fixture completes the end-to-end vertical slice and a dry-run autopost handoff.
- Tests exercise timestamps, boundaries, rights gates, ranking/deduplication, output QA, retries and idempotent handoff.
- The output video is checked with ffprobe/validation and an artifact manifest is produced.
- Existing autopost code and user files remain unchanged unless modifications were explicitly approved.
- Setup, configuration, limitations, licensing, and known unverified live integrations are documented honestly.

## REPORTING AND DECISION RULES

Maintain `docs/research/progress.md` with phase status, decisions, blockers, tests run and next steps. Keep updates concise and evidence-based. Before major implementation, show the architecture and repository selection rationale as an artifact; then continue implementation rather than waiting unnecessarily for confirmation.

When choosing between two approaches, prioritize in this order: legal/policy compliance; correctness and recoverability; measurable clip quality; maintainability; local-first operation and cost control; speed of implementation. Do not overfit to repository star counts or promotional claims. Do not add unrelated faceless-video generation, AI actor generation, TTS story generation, billing/SaaS, or a complex frontend unless it is required for the clipping objective.

At the end, produce a concise final summary with: what was built, architecture, repositories cloned, components adopted and their exact provenance, license/policy findings, tests and their results, commands to run, where outputs are stored, integration status with the existing autopost system, and the specific remaining blockers. Be truthful about tests, API access, GPU access, and integrations that were not available.

**Start now. Inspect the workspace, launch the research agents in parallel, and execute Phases 0–3 first. Continue through the remaining phases as far as the environment permits; do not stop after writing a plan.**
