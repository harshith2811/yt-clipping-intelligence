# YouTube Clipping Master Repo — Open-Source Research & Architecture Brief

**Research date:** 28 October 2026  
**Purpose:** Identify reusable engineering patterns for a rights-aware system that discovers promising video opportunities, selects strong moments, renders short-form clips, and hands them to an existing autopost workflow.

## Executive recommendation

Do not combine entire repositories by copy-pasting code. Their dependency stacks, data models, licenses, and assumptions differ. Create one modular master system, use permissively licensed libraries directly where sensible, and adapt well-understood patterns with attribution and license compliance.

**Provisional starting point:** evaluate [OpenShorts](https://github.com/mutonby/openshorts) as an MIT-licensed end-to-end UI/pipeline scaffold. It has local/self-hosted operation, transcription backends, a render service, API/MCP access, and a substantial set of tests. Compare it with the smaller [AI-Youtube-Shorts-Generator](https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator) if the initial goal is just a compact processing core. Before adopting either, perform a code, dependency, secrets, and license audit; this was a reconnaissance review, not a security certification.

Take the strongest operational patterns from [ClippyMe](https://github.com/fralapo/clippyme) (watchers, resumable jobs and post-render QA) and [ClipMint](https://github.com/kleZ799/clipmint) (transparent hook/moment scoring and a performance-feedback loop). Use [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [WhisperX](https://github.com/m-bain/whisperX), [PySceneDetect](https://github.com/Breakthrough/PySceneDetect), [MediaPipe](https://github.com/google-ai-edge/mediapipe), and FFmpeg for focused media capabilities instead of reimplementing them.

## Critical product distinction: views vs. retention

There are two different ranking problems:

1. **Which source videos look promising?** Public metadata can provide upload time, total views, likes, comments where available, creator/channel context, and growth snapshots where tracking is permitted.
2. **Which segment inside a video was most watched?** That requires audience-retention/watch-segment analytics. YouTube's Analytics API exposes metrics such as `audienceWatchRatio` against `elapsedVideoTimeRatio`, but those Analytics reports require authorization and channel ownership. For unrelated creators, the system cannot claim to know their exact most-watched timestamps from public view totals. It can only estimate candidate moments from transcript, audio, and visual evidence unless the creator supplies retention data.

Official docs:
- [YouTube Data API: Search list](https://developers.google.com/youtube/data/reference/rest/v3/search/list) — supports channel/date/view-count-related search controls, but explicitly recommends the uploads playlist (`playlistItems.list`) to reliably find a channel's latest uploads rather than relying on `search.list`.
- [Videos list / mostPopular](https://developers.google.com/youtube/data/guides/implementation/videos) — supports the regional/category `mostPopular` chart.
- [YouTube Analytics channel reports](https://developers.google.com/youtube/analytics/channel_reports) and [audience-retention metrics](https://developers.google.com/youtube/analytics/metrics) — retention is owner-authorized Analytics data.

## Non-negotiable rights and platform-policy gate

The desired flow includes downloading and reposting videos from top creators. That must not be implemented as an unrestricted downloader/reposter for arbitrary YouTube content.

- YouTube's current API policies prohibit API clients from downloading, importing, backing up, caching, or storing copies of YouTube audiovisual content without YouTube's prior written approval; they also prohibit scraping YouTube applications. See [YouTube API Services Developer Policies, section E](https://developers.google.com/youtube/terms/developer-policies).
- The standard YouTube license is the default. A creator's explicit permission or a license such as CC BY can change copyright permissions, but terms still need to be checked, and attribution alone does not grant rights. See [YouTube license types](https://support.google.com/youtube/answer/2797468?hl=en).
- YouTube's reused-content/monetization policy is separate from copyright. Minimal edits or reposting can still be ineligible for monetization even when a creator has given permission. See [YouTube channel monetization policies](https://support.google.com/youtube/answer/1311392?hl=en).
- The YouTube API policies also restrict aggregation of API data across unrelated content owners. Before implementing a cross-creator ranking database, review the applicable terms and get legal/policy guidance. Do not assume that public visibility means unrestricted harvesting, downloading, storage, or republishing.

**Recommended approved-source model:** discover opportunities via permitted metadata; require each source asset to pass a rights gate; ingest video/audio from a creator-provided file, an authorized storage location, the user's own channel/source archive, or an explicitly reusable source whose license permits the intended use. Keep evidence of rights and allowed uses attached to every clip. Do not bypass access controls or scrape/downloader-block protections.

## Repository survey

The ecosystem is large and changes quickly; this is a broad, targeted sweep of repositories and selected source modules, not a claim that every repository on GitHub was exhaustively audited. Star counts are omitted from most rows because they change continuously and are a poor proxy for code quality.

### A. Primary clip-generation and automation candidates

| Repository | License (observed) | Useful ideas to borrow | Assessment / caution |
|---|---|---|---|
| [OpenShorts](https://github.com/mutonby/openshorts) | MIT | End-to-end app, clip selection module, transcription backend contract, render worker, API/MCP, tests around transcript checkpoints, clip readiness and malformed inputs; split-screen layout for multi-speaker content | **Best provisional scaffold candidate.** Recent activity and breadth make it worth a deeper audit. Do not inherit every feature by default; preserve modular boundaries. |
| [AI-Youtube-Shorts-Generator](https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator) | MIT | Small processing core, content-type/density classification, long-video chunking with overlap, configurable LLM provider, JSON output, overlap suppression/deduplication | **Best compact baseline for highlight logic.** README and code are easy to inspect; far less complete as a monitoring/job system. |
| [ClipMint](https://github.com/kleZ799/clipmint) | MIT | Scores opening hook separately from overall moment, audio/visual/text signals, interpretable scorecard, YouTube post-performance collection, ranking feedback | Strong scoring/product-loop reference. It states that it builds on the AI-Youtube-Shorts-Generator; treat as a derivative branch, not fully independent validation of the same algorithm. |
| [ClippyMe](https://github.com/fralapo/clippyme) | MIT | Channel monitor, unattended processing, async jobs, crash-safe journal/checkpoints, restart/resume, active-speaker reframing, post-render QA | Strongest operational inspiration for unattended runs and failure recovery. More integrated and complex than a minimal MVP. |
| [SupoClip](https://github.com/FujiwaraChoki/supoclip) | AGPL-3.0 | Rich editor, virality scoring, social caption generation, worker queue, export tracking, progress events, broad tests, publishing/performance loop | Excellent feature reference. **AGPL-3.0 is a material constraint** if you want a differently licensed or proprietary master repo; do not copy code casually. |
| [Open Clipper](https://github.com/GrepCut/OpenClipper) | MIT | Local-first editing, local/cloud transcription options, scene-aware subject reframing, GPU-aware processing and batch exports | Useful for desktop/local-processing ergonomics; less central to discovery and intelligence. |
| [Open-source clipping](https://github.com/NaufalRizqullah/opensource-clipping) | MIT | Face tracking, speaker diarization, split-screen/hybrid layouts, B-roll pipeline, captions, uploader/tracker modules | Useful reference for richer rendering and multi-speaker handling; audit dependencies and module boundaries before adopting components. |
| [Purffle Shorts](https://github.com/Chamanrajragu/purffle-shorts) | MIT | Provider adapters for Claude/Gemini/OpenAI/Ollama-compatible LLMs, word-synced captions, MCP integration, scheduled publishing | More focused on end-to-end generated/faceless content than authorized repurposing; borrow provider abstraction and automation interfaces, not its whole product scope. |
| [Clips / ClipPulse-AI](https://github.com/musaoffice/ClipPulse-AI) | No declared license observed in repository metadata | Chunked transcription, local/API modes, caching, dedupe and JSON outputs | Inspiration only until a reusable license is confirmed. |
| [AI Shorts Generator](https://github.com/aminedrif/ai-shorts-generator) | MIT | Transcript + audience-retention features for authorized analytics, face tracking, FFmpeg reframe, subtitles, multiple input paths | Small, relevant prototype; verify maintenance and tests before relying on it. |
| [VideoHighlighter](https://github.com/touplikiotisapostolis-web/videohighlighter) | AGPL-3.0 | Multimodal local analysis: scene, motion, objects/actions, audio peaks and transcript | Useful detector taxonomy. AGPL code licensing must be considered. |
| [Hi-Lite](https://github.com/seanng-1/hi-lite) | GPL-3.0 | Segment review UI, local transcription, offline/remote-LLM scoring, manual override | Good human-in-the-loop UX concept; GPL-3.0 is a constraint for code reuse. |
| [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) | MIT | Batch workflow patterns, dashboard/API, media assembly and configuration | Very popular, but primarily generates videos from topics/assets instead of selecting clips from source videos. Reuse relevant workflow ideas only. |
| [Short Video Maker](https://github.com/gyoridavid/short-video-maker) | MIT | REST API and MCP patterns, n8n automation, template-based rendering | More text-to-video than source clipping; useful at the integration boundary. |
| [AI clipping generator](https://github.com/SamurAIGPT/ai-clipping-generator) | MIT | Next.js/API/job-oriented application scaffolding and product isolation | SaaS-heavy (billing/auth); don't import payment code unless needed. |
| [NouClip](https://github.com/nouverse/nouclip) | MIT | Agentic CLI, Whisper + FFmpeg, scriptable clipping workflow | Useful CLI/agent interface reference; smaller community and less end-to-end operations evidence. |
| [Auto-clipping](https://github.com/rawiansyahas/auto-clipping) | Apache-2.0 | Batch segmentation, local faster-whisper, OpenCV crop tracking, word-synced captions | A compact implementation reference for a local batch pipeline. |
| [RipClips](https://github.com/xniperbuilds/ripclips) | MIT | Agent-oriented workflow chaining, speaker crop and burned-in captions | Small project; reference only after reviewing code quality. |
| [Tukdify Clips](https://github.com/Tukdify/Tukdify-clips) | No license observed | Local transcription/reframing/caption workflow | Do not copy code until a license is provided. |

### B. Discovery, channel monitoring, and trends

| Repository | License (observed) | Useful ideas | Assessment / caution |
|---|---|---|---|
| [Tube Virality](https://github.com/gpsyrou/tube-virality) | MIT | Separate trending/control samples, metrics collection, historical snapshots and ML-based virality estimation | Best research reference for trend-analysis methodology, but apply YouTube API aggregation and retention rules before implementing cross-owner storage. |
| [YouTube Tracker](https://github.com/thevops/youtube-tracker) | MIT | Multiple channel watchlists, scheduled polling, cached IDs/deduplication, new-video events from feeds | Small and straightforward monitor reference; less active code history. Check the source/feed's permitted use before deployment. |
| [YT Tracker](https://github.com/vicke4/yt-tracker) | MIT | Channel/video stats in a Sheets-facing workflow | Older codebase; idea reference rather than a modern base. |
| [YT Videos Agent](https://github.com/FassihShah/YT-Videos-Agent) | MIT | Human approval step, LangGraph-style flow and controlled upload actions | Primarily creates content from trends rather than clipping source footage; borrow explicit approval states. |
| [YouTube Trends](https://github.com/darshanabk/YouTube-Trends) | No license assertion observed | Keyword-driven metadata collection and trend reports | Do not copy until the repository declares a license. |
| [YouTube Auto Uploader](https://github.com/SJbuilds04/yt-auto-uploader) | No license observed | Schedule dashboard, multi-channel publishing and AI metadata generation | Useful as interface inspiration only until licensing is clarified; your existing uploader should remain the publishing system of record. |
| [YouTube Scrapy Scraper](https://github.com/Simple-Python-Scrapy-Scrapers/youtube-scrapy-scraper) | MIT | Structured extraction/export patterns | Description advertises scraping and anti-bot/proxy features. Do **not** adopt scraping or bypass tactics; prefer documented/authorized sources and current platform terms. |

### C. Focused media and ML building blocks

| Repository | License (observed) | Best use in the master repo |
|---|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Unlicense for repository source (bundled artifacts can have different terms) | A technically capable media tool, but **not a rights layer**. Do not use it as an unrestricted mechanism for downloading other people's YouTube videos. Source assets must already be approved and supplied through a compliant route. |
| [OpenAI Whisper](https://github.com/openai/whisper) | MIT | Baseline speech recognition, multilingual transcription and fallback path. |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT | Efficient transcription, reduced memory usage, local CPU/GPU deployment. Its README reports up to 4× speed versus the original Whisper implementation under its benchmark setup; benchmark on our hardware. |
| [WhisperX](https://github.com/m-bain/whisperX) | BSD-2-Clause | Word-level timestamp alignment and optional diarization pipeline integration. Verify model/diarization dependencies separately. |
| [pyannote.audio](https://github.com/pyannote/pyannote-audio) | MIT code license observed | Speaker diarization, speaker changes and speech regions; model weights may have their own licensing/access terms. |
| [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) | BSD-3-Clause | Scene-cut detection and shot boundaries that inform candidate segmentation and crop planning. |
| [MediaPipe](https://github.com/google-ai-edge/mediapipe) | Apache-2.0 | Face/person tracking and landmarks for crop placement; use smoothing and shot-boundary resets. |
| [MoviePy](https://github.com/Zulko/moviepy) | MIT | Python-level composition for prototyping and orchestration; use FFmpeg directly for repeatable/efficient production rendering. |
| [ffmpeg-python](https://github.com/kkroening/ffmpeg-python) | Apache-2.0 | Typed-ish Python graph wrapper for FFmpeg filter pipelines. FFmpeg itself has its own LGPL/GPL build and codec considerations. |
| [auto-editor](https://github.com/WyattBlue/auto-editor) | Unlicense | Silence/low-activity detection and automated cuts; use selectively, since silence removal can damage comedic timing or conversational context. |

## What we should actually build

### 1. Rights-aware source registry

Every channel/source has an explicit policy record, not just a URL:

- Creator/content owner and contact/reference.
- Allowed source-asset acquisition method.
- Permission evidence or license URL/version.
- Allowed territories, platforms, duration, edit types, attribution requirements, monetization rights, expiry/revocation status.
- Whether the uploader has supplied source files or authorized access to the source archive.

A candidate without a valid rights state can be analyzed as metadata only, but its video/audio cannot enter the rendering/publishing queue. Rights status follows every generated clip and is rechecked before posting.

### 2. Discovery and momentum service

For owned or properly authorized channels, use documented API operations and scopes. For reliably identifying new uploads, resolve a channel's uploads playlist and poll `playlistItems.list`; do not depend solely on `search.list` for new-upload detection. Use `videos.list` for current public fields where permitted. A regional `mostPopular` chart can inform a broad trend candidate list, but it is not the same as a personalized list of “top YouTubers.”

Where terms permit time-series data, compute view velocity from successive snapshots rather than ranking by lifetime views alone. Normalize growth against that channel/content class's expected performance and video age. Keep the policy-enforced boundaries on data retention and aggregation; do not build a prohibited cross-owner analytics store.

The system should separate:
- **Discovery score:** recency, eligible public momentum signals, topic relevance, source quality.
- **Clip score:** moment quality inside the asset.
- **Rights status:** a hard eligibility gate, not a score that can be outweighed by virality.

### 3. Highlight intelligence engine

Use a multi-stage candidate/rerank workflow. Ask an LLM to reason over a timestamped transcript and return structured clip candidates, but never trust generated timestamps without mapping them back to real transcript word/sentence boundaries.

**Candidate signals:**
- Immediate opening hook; can it start cold without 8 seconds of setup?
- Coherent self-contained thought: setup → tension/question → payoff.
- Useful insight, revelation, story climax, surprising claim, disagreement, humor or emotional reaction.
- Pace, filler/silence, speaker change, laughter/applause and audio-energy peaks.
- Visual changes, scene boundaries, active speaker visibility and crop feasibility.
- Ending integrity: no chopped word, no missing payoff, no abrupt sentence fragment.

Use category-aware scoring (podcast, interview, tutorial, commentary, gaming, lecture, vlog). Keep separate values for `hook`, `moment`, `coherence`, `novelty`, `emotion`, `pacing`, `audio`, `visual_crop`, `rights`, and model confidence. Expose “why this ranked here” and allow human override. Initial weights should be treated as hypotheses and later calibrated on real output metrics, not presented as a validated virality model.

**Long-source handling:** transcribe once and cache; chunk long transcripts with overlap; ask a fast model to shortlist then use a stronger model to judge finalists; merge word-level timestamps; suppress high-overlap duplicates and semantic near-duplicates; retain a few alternatives rather than assuming the top score is always right.

### 4. Smart rendering engine

Render as deterministic jobs from a clip specification:
- Input source asset plus precise start/end time and source transcript mapping.
- 9:16 (and optional square/landscape) presets.
- Track a face/person/speaker with crop-path smoothing and reset at scene cuts.
- For two active speakers, use a stacked/split layout when it improves legibility; otherwise select the active speaker or preserve the wide frame with background fill.
- Burn in word-synced captions using readable safe zones, line lengths, contrast and platform-aware sizing.
- Do not fabricate subtitles: preserve a route to manual correction for low-confidence words, names, numbers and mixed-language speech.
- Optional opener/title/card/branding only when permitted by the source's rights policy.

### 5. QA and durable automation

ClippyMe's QA and restartable-job patterns are especially valuable. Build explicit job phases such as `discovered → rights_pending → source_ready → transcribed → candidates_scored → awaiting_review/approved → rendered → qa_passed → handed_to_publisher → published`.

Use a durable database for state, a job queue for expensive CPU/GPU tasks, and a journal/checkpoint for restart recovery. Every job should be idempotent. A retry must not create duplicate clips, uploads or scheduler entries. Store checkpoints after source inspection, transcription, candidate selection and render; never mark a job successful just because FFmpeg returned exit code zero.

Post-render QA should verify with `ffprobe` and sampled frames:
- Video stream and audio stream exist.
- File is non-empty, decodable and duration is within tolerance.
- Dimensions and aspect ratio match the selected preset.
- Black frames/freezes, audio silence/peaking and obvious render corruption are absent or flagged.
- Captions stay inside safe zones and no text glyphs are missing.
- Source/timestamp/rights metadata and final media path are present.

Critical failures block publication; quality warnings remain reviewable. Preserve the previous known-good artifact until the new render passes QA.

### 6. Integration with the existing autopost system

Do not rebuild the uploader unless a real integration gap requires it. Define a stable handoff contract (webhook/REST or watched folder + manifest):

```json
{
  "clip_id": "stable-id",
  "asset_path": "approved-artifact.mp4",
  "title": "reviewed title",
  "description": "description with required source attribution",
  "tags": [],
  "source_id": "source-id",
  "source_start_seconds": 123.4,
  "source_end_seconds": 168.2,
  "rights_record_id": "rights-id",
  "approval_status": "approved",
  "qa_status": "passed",
  "idempotency_key": "stable-publication-key"
}
```

The publisher should reject a clip unless `rights_record_id`, `approval_status`, and `qa_status` pass policy. It should return an upload/job ID, and the master repo should track that same ID. The actual fields can be matched to your existing autopost schema rather than replacing it.

### 7. Performance feedback loop

For your own or separately authorized channels, fetch permitted publishing outcomes and channel analytics after publication. Track clip ID → upload ID → views/likes/comments/watch metrics at defined checkpoints. Compare outcomes to the clip's pre-publish scores and update ranking weights cautiously. Avoid training the model on tiny samples; use confidence intervals/baselines and separate performance by content type, channel, duration, hook format and posting slot.

ClipMint and SupoClip show the value of closing the loop, but the master repo must respect YouTube's authorization and API data-storage/aggregation policies. For third-party channels, use creator-supplied/authorized analytics or an external data provider whose license and API terms explicitly permit the intended research; do not infer unauthorized audience-retention access.

## Suggested system layout

```text
master-repo/
  apps/
    dashboard/                 # source queue, candidate review, job status
    api/                       # FastAPI REST/webhook surface
  services/
    discovery/                 # permitted feeds/API integrations, channel list
    rights/                    # permissions, licenses, expiry and audit trail
    ingestion/                 # approved files/storage and ffprobe preflight
    transcription/              # faster-whisper / WhisperX adapters
    candidate_detection/       # transcript chunks, scenes, audio/visual cues
    scoring/                   # pluggable LLM providers, schema validation, dedupe
    rendering/                 # FFmpeg filters, reframe/captions/templates
    qa/                        # media validation and artifact policy checks
    publisher_adapter/          # existing autopost handoff only
    analytics/                  # authorized publication outcomes and calibration
  workers/                      # durable background work and retry policy
  contracts/                    # typed candidate/clip/job/publisher schemas
  tests/
    unit/ integration/ fixtures/ golden_media/ e2e/
  docs/
    architecture.md rights-policy.md model-evaluation.md runbook.md
  compose.yaml
```

**Suggested starting stack:** Python + FastAPI for the pipeline API; PostgreSQL for durable job/rights/clip state; Redis plus Celery/Dramatiq/RQ for background CPU/GPU jobs; FFmpeg/ffprobe for rendering/verification; faster-whisper/WhisperX and PySceneDetect as adapters; MediaPipe/other face detectors behind a replaceable framing interface. Use Docker Compose for reproducible local deployment. Keep the LLM provider swappable (Claude, Gemini, OpenAI-compatible local server), with JSON schema validation, retry limits, cost logging and deterministic fallback rules.

## Implementation roadmap

### Phase 0 — permissions and requirements

- Define which sources are owned, explicitly authorized, or reusable under documented licenses.
- Decide allowed platforms, edit types, attribution and monetization rules.
- Document the existing autopost endpoint/schema and failure behavior.
- Choose a repo baseline after reading its license, deployment docs, dependencies and tests.

### Phase 1 — reliable single-source vertical slice

- Ingest one approved source asset.
- Generate/cache word-timestamp transcript.
- Produce 5–10 candidate moments with explanations and valid time boundaries.
- Render 2–3 vertical clips, run QA and surface a preview/review screen.
- Hand one explicitly approved clip to the existing autopost tool with an idempotency key.

### Phase 2 — channel watchlist and job durability

- Add permitted channel/feed discovery, dedupe and new-video notification.
- Add rights state before media ingest.
- Add durable checkpoints, restart/resume, GPU concurrency controls, retries and queue observability.
- Test with failures: empty transcript, LLM timeout, malformed JSON, missing audio, FFmpeg failure, duplicate webhook and worker restart.

### Phase 3 — ranking evaluation

- Build a labelled test set of source timestamps and preferred clips.
- Measure boundary accuracy, clip coherence, duplicate rate, caption word error, crop stability and reviewer acceptance rate.
- Run A/B comparisons of scoring strategies. Treat “virality scores” as uncalibrated until actual posting outcomes support them.

### Phase 4 — authorized performance feedback

- Join published results using the upload ID.
- Evaluate performance only under valid channel-owner authorization and applicable API rules.
- Adjust scoring by content category and publication context; retain human controls and rollback.

### Phase 5 — harden for unattended production

- Secrets management, least-privilege OAuth, audit log, data retention/deletion, storage quotas and backup/restore.
- Resource-aware worker scheduling, GPU/CPU fallback, artifact checksums and storage cleanup.
- End-to-end tests, golden-video regression fixtures, license inventory/SBOM and release checklist.

## Acceptance criteria for the master repo

1. No source asset enters render/publish without a valid rights record.
2. Every clip's timestamps map to the real transcript and remain inside source duration.
3. Same source/job rerun is idempotent; no duplicate artifacts or uploads.
4. Worker crash resumes from a checkpoint without corrupting a known-good clip.
5. Every exported file passes structural QA; QA failure blocks the publisher.
6. Clip candidates include component scores, a concise rationale and confidence/uncertainty.
7. The autopost system remains the single publishing authority.
8. Model providers and detector modules can be swapped without rewriting the pipeline.
9. License compliance is tracked for copied code, libraries, FFmpeg builds, model weights and fonts.
10. Public metrics/analytics storage follows applicable YouTube API terms, including authorization, refresh/deletion and aggregation boundaries.

## Bottom line

Build the master repo around **rights-aware ingestion + explainable moment ranking + verified rendering + durable orchestration + a small integration seam to your existing autoposter**. The best implementation ingredients are not a blind merge: OpenShorts is the leading candidate to audit as a scaffold; ClippyMe is the strongest operational-pattern reference; ClipMint informs interpretable, hook-aware scoring and authorized performance feedback; faster-whisper/WhisperX/PySceneDetect/MediaPipe/FFmpeg provide the media substrate.

The most important differentiator is the discovery-and-learning system, not just vertical cropping. But external creators' exact audience retention and permission to download/repost cannot be assumed; both must be handled honestly in the design.
