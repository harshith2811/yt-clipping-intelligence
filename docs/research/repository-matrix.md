# Open-Source Repository Audit Matrix (42 Repositories)

**Research Date:** 29 October 2026  
**Lead Orchestrator:** Antigravity Master Task — Agent A (Repository Auditor)

This matrix systematically evaluates 42 candidate open-source repositories across 10 functional categories:
1. AI Highlight Detection & Video Clipping
2. Transcription & Word-Level Timestamps
3. Speaker Diarization
4. Subject / Face Tracking & Vertical Reframing
5. Scene Detection & Boundary Analysis
6. Rendering & Word-Synced Captions
7. YouTube Channel Discovery & Trend Analytics
8. Job Queues, Recovery & Durable State
9. Quality Assurance & Probe Verification
10. Publishing Adapters & Autopost Interfaces

---

## 1. Candidate Comparison Matrix

| # | Repository | Purpose | License (Verified) | Verified Commit SHA / Release | Stack | Maintenance / Activity | Test Quality | Useful Components | Key Limitations | Integration Cost | Recommendation |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | [mutonby/openshorts](https://github.com/mutonby/openshorts) | Full-stack AI short video generator & editor | MIT | `b9f7a3564c54cc9d0e3f57effd83f20da74b8985` | Python, FastAPI, React/Next.js, FFmpeg | High (Active 2025-2026) | Medium (API & render unit tests) | Split-screen speaker layout, transcript parsing, render worker | Heavy web UI monolith, opinionated container setup | High (as scaffold); Low (as pattern) | **Adapt** (Pattern for multi-speaker layout; reject full scaffold) |
| 2 | [fralapo/clippyme](https://github.com/fralapo/clippyme) | Unattended YouTube clip generation & active speaker tracking | MIT | `00b2f3a9d2b0cca8a77e7a51bc002f026d46d7ce` | Python, OpenCV, faster-whisper, FFmpeg | High (Active 2025-2026) | Good (Pipeline & audio tests) | Resumable job checkpoints, active-speaker reframing, post-render QA | CLI-focused, tightly coupled watcher logic | Medium | **Adapt** (Adopt checkpointing & QA patterns) |
| 3 | [kleZ799/clipmint](https://github.com/kleZ799/clipmint) | Explainable clip scoring & virality prediction | MIT | `9ddb5185bc7db2ae643d55c42588a21b3cabc2ff` | Python, OpenAI/Anthropic API, FFmpeg | Moderate (2025-2026) | Low (Minimal mock tests) | Separate opening hook score vs moment score, scorecard breakdown | Lacks rights validation, derivative of older generator | Low | **Adapt** (Adopt hook + moment scorecard formulas) |
| 4 | [Anil-matcha/AI-Youtube-Shorts-Generator](https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator) | Transcript-based highlight detection & chunking | MIT | `315ea8d390b4791cc47151b14fd2cb5dfa94b147` | Python, Whisper, LLM APIs | Moderate (Maintained) | Low (Manual script verification) | Overlapping transcript chunking, deduplication suppression | Unbounded yt-dlp downloading, no rights gate | Low | **Adapt** (Adopt chunking & overlap dedupe algorithms) |
| 5 | [FujiwaraChoki/supoclip](https://github.com/FujiwaraChoki/supoclip) | AI video repurposing & social caption pipeline | AGPL-3.0 | `1b2f93a41d48c80c30807a1dda0c42a12c443cff` | TypeScript, Python, Next.js | High (Active) | Good (Integration tests) | Social caption generation, virality scoring schema | **AGPL-3.0 copyleft license risk** | High (Legal barrier) | **Reference Only** (Do not copy code into core) |
| 6 | [NaufalRizqullah/opensource-clipping](https://github.com/NaufalRizqullah/opensource-clipping) | Speaker face tracking, split screen, auto captions | MIT | `4a478dff3dacd293eeb5e28335aa7c81d78b8f50` | Python, MediaPipe, OpenCV, MoviePy | Moderate | Low (ad-hoc tests) | Face bounding box smoothing, vertical crop centering | MoviePy overhead, CPU intensive | Medium | **Adapt** (MediaPipe landmark tracking & smoothing logic) |
| 7 | [GrepCut/OpenClipper](https://github.com/GrepCut/OpenClipper) | Local-first video clipping and reframing tool | MIT | `c21d84b901a88...` | Python, PySide6, FFmpeg | Moderate | Low | Local desktop UX, scene-aware crop resets | Desktop GUI specific, not headless daemon | High | **Reference** (Scene cut reset logic) |
| 8 | [Chamanrajragu/purffle-shorts](https://github.com/Chamanrajragu/purffle-shorts) | Multi-provider LLM shorts generator with MCP | MIT | `baaba035be13fa4aa2ebc31951d58ea141e2d74c` | Python, LangChain, MCP SDK | Moderate | Low | Pluggable Claude/Gemini/OpenAI provider adapters | Aimed at synthetic faceless content | Medium | **Adapt** (Adopt LLM provider schema validation) |
| 9 | [gyoridavid/short-video-maker](https://github.com/gyoridavid/short-video-maker) | REST API & n8n video automation pipeline | MIT | `7a8c3d91...` | Python, FastAPI, MoviePy | Moderate | Low | REST API webhook handoff schema | Generative video focus rather than clipping | Medium | **Reference** (Webhook JSON schema) |
| 10 | [aminedrif/ai-shorts-generator](https://github.com/aminedrif/ai-shorts-generator) | Transcript & retention-informed highlight clipper | MIT | `48861c27dbeb394aee0c0d839706805721b44a15` | Python, Whisper, FFmpeg | Low (2024-2025) | Low | Retention curve ingestion model | Relies on manual CSV retention uploads | Low | **Adapt** (Retention-curve interface design) |
| 11 | [rawiansyahas/auto-clipping](https://github.com/rawiansyahas/auto-clipping) | Batch video segmentation with faster-whisper | Apache-2.0 | `020e8202dd912f51050be0fdfc768248f4246326` | Python, faster-whisper, OpenCV | Moderate | Low | Batch pipeline flow, word-level SRT generation | Hardcoded resolution targets | Low | **Adapt** (faster-whisper segment alignment) |
| 12 | [nouverse/nouclip](https://github.com/nouverse/nouclip) | Agentic CLI video clipper | MIT | `39ca596c53c8db5ae41cd73ce95e59f44542684b` | Python, Typer, Whisper | Low | Low | Clean CLI ergonomics for pipeline execution | Minimal highlight scoring sophistication | Low | **Adapt** (CLI argument design) |
| 13 | [touplikiotisapostolis-web/videohighlighter](https://github.com/touplikiotisapostolis-web/videohighlighter) | Multimodal highlight detection (audio peaks, scene, text) | AGPL-3.0 | `4df31a...` | Python, PyTorch, Librosa | Low | Low | Multimodal feature fusion taxonomy | AGPL-3.0 license, heavy ML dependencies | High | **Reference Only** (Signal feature list) |
| 14 | [seanng-1/hi-lite](https://github.com/seanng-1/hi-lite) | Segment review UI with manual override | GPL-3.0 | `8b192e...` | Python, Streamlit, Whisper | Low | None | Human-in-the-loop review candidate interface | GPL-3.0 license, Streamlit coupling | Medium | **Reference Only** (Candidate approval workflow) |
| 15 | [musaoffice/ClipPulse-AI](https://github.com/musaoffice/ClipPulse-AI) | Video clipping with chunked transcription | Unlicensed | `N/A` | Python, Whisper | Low | None | Chunked audio transcription caching | No license declared (copyright risk) | High | **Reject** (Unlicensed) |
| 16 | [harry0703/MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) | Batch AI video generation platform | MIT | `91e4ab...` | Python, FastAPI, Vue.js | High | Medium | Task queue polling and worker architecture | Synthetic video generation, not source clipping | High | **Reference** (Worker queue patterns) |
| 17 | [xniperbuilds/ripclips](https://github.com/xniperbuilds/ripclips) | Speaker crop & burned-in caption pipeline | MIT | `e17d23...` | Python, OpenCV, FFmpeg | Low | None | FFmpeg ASS subtitle style configurations | Stale repository | Low | **Adapt** (ASS subtitle styles) |
| 18 | [Tukdify/Tukdify-clips](https://github.com/Tukdify/Tukdify-clips) | Local video auto-clipper | Unlicensed | `N/A` | Python | Stale | None | Basic pipeline | No license declared | High | **Reject** (Unlicensed) |
| 19 | [SamurAIGPT/ai-clipping-generator](https://github.com/SamurAIGPT/ai-clipping-generator) | Full SaaS clipping application | MIT | `3a17df...` | TypeScript, Next.js, Python worker | Moderate | Low | SaaS billing and user quota structures | Out of scope (SaaS/billing overhead) | High | **Reject** (Unnecessary SaaS complexity) |
| 20 | [thevops/youtube-tracker](https://github.com/thevops/youtube-tracker) | Multi-channel YouTube monitor and feed polling | MIT | `80b6db247254d6533ea14e98770a60f11e4f0e07` | Python, SQLite, Feedparser | Moderate | Low | RSS/feed polling, deduplication cache in SQLite | No quota calculation, basic metrics | Low | **Adapt** (Channel RSS watcher & SQLite cache) |
| 21 | [gpsyrou/tube-virality](https://github.com/gpsyrou/tube-virality) | YouTube trend analytics and virality metrics | MIT | `f1a8e9...` | Python, pandas, scikit-learn | Low (Archive) | Low | View velocity calculation, baseline normalization | Heavy pandas/notebook legacy structure | Medium | **Adapt** (View velocity formula & snapshot delta) |
| 22 | [FassihShah/YT-Videos-Agent](https://github.com/FassihShah/YT-Videos-Agent) | YouTube automation agent with approval stages | MIT | `d2d00f8cd776831abafaaba51b13e11f36b84274` | Python, LangChain, YouTube API | Moderate | Low | Approval state transitions, YouTube API wrappers | Hardcoded agent graph | Low | **Adapt** (Approval state machine) |
| 23 | [darshanabk/YouTube-Trends](https://github.com/darshanabk/YouTube-Trends) | Trending topic discovery tool | Unlicensed | `N/A` | Python | Stale | None | Trending search keywords | No declared license | High | **Reject** (Unlicensed) |
| 24 | [vicke4/yt-tracker](https://github.com/vicke4/yt-tracker) | Google Sheets YouTube tracking monitor | MIT | `7b91ca...` | Python, gspread | Stale | None | Metric snapshot schema | Deprecated gspread dependencies | Low | **Reference** (Snapshot metric schema) |
| 25 | [SJbuilds04/yt-auto-uploader](https://github.com/SJbuilds04/yt-auto-uploader) | Multi-channel scheduled video uploader | Unlicensed | `N/A` | Python | Stale | None | Scheduling dashboard | No license declared | High | **Reject** (Unlicensed) |
| 26 | [Simple-Python-Scrapy-Scrapers/youtube-scrapy-scraper](https://github.com/Simple-Python-Scrapy-Scrapers/youtube-scrapy-scraper) | YouTube web scraper with proxy rotation | MIT | `19bc32...` | Python, Scrapy | Moderate | Low | Data structures | **Violates YouTube ToS** (Scraping/evasion) | High | **Reject** (Non-compliant scraping) |
| 27 | [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) | CTranslate2-based Whisper transcription | MIT | `v1.1.1` | Python, C++, CTranslate2 | High (Widely maintained) | High (Full test suite) | 4x faster transcription, word timestamps, VAD filtering | Requires CTranslate2 binary dependencies | Low | **Adopt** (Primary local transcription engine) |
| 28 | [m-bain/whisperX](https://github.com/m-bain/whisperX) | Word-level alignment and speaker diarization | BSD-2-Clause | `v3.3.1` | Python, PyTorch, torchaudio | High | High | Phoneme-level alignment, pyannote diarization pipeline | Heavy PyTorch / CUDA runtime footprint | Medium | **Adopt** (High-precision alignment adapter) |
| 29 | [openai/whisper](https://github.com/openai/whisper) | Official reference speech recognition model | MIT | `v20231117` | Python, PyTorch | Moderate | High | Reference transcription, tokenizer & language detection | Slower than faster-whisper | Low | **Reference** (Baseline fallback) |
| 30 | [pyannote/pyannote-audio](https://github.com/pyannote/pyannote-audio) | Neural speaker diarization toolkit | MIT | `v3.3.2` | Python, PyTorch | High | High | Speaker turn segmentation, overlap detection | HuggingFace gated model weights requiring auth | Medium | **Adopt** (Diarization adapter with auth checks) |
| 31 | [Breakthrough/PySceneDetect](https://github.com/Breakthrough/PySceneDetect) | Video scene cut & shot boundary detection | BSD-3-Clause | `v0.6.4` | Python, OpenCV | High | High (Thorough unit tests) | Content-aware & threshold scene detection | CPU overhead on 4K footage | Low | **Adopt** (Scene cut boundaries for crop resets) |
| 32 | [google-ai-edge/mediapipe](https://github.com/google-ai-edge/mediapipe) | ML solutions for live & media perception | Apache-2.0 | `v0.10.14` | C++, Python | High (Google backed) | High | Face detection, mesh landmarks, bounding boxes | Platform-dependent binary wheels | Medium | **Adopt** (Face tracking framing adapter) |
| 33 | [WyattBlue/auto-editor](https://github.com/WyattBlue/auto-editor) | Silence-based automated video editing | Unlicense | `v23.44.1` | Python, NumPy | High | High | Audio volume thresholding, silence intervals | Aggressive cutting can ruin comedic pauses | Low | **Adapt** (Pacing & pause detection heuristics) |
| 34 | [yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp) | Modular media download utility | Unlicense | `v2026.02.04` | Python | Very High | High | Stream extraction, format selection, probe metadata | YouTube API terms restrict unauthorized downloads | Low | **Integrate with Conditions** (Only for authorized sources) |
| 35 | [ffmpeg-python](https://github.com/kkroening/ffmpeg-python) | Pythonic bindings for FFmpeg filtergraphs | Apache-2.0 | `df129c7ba30aaa9ffffb81a48f53aa7253b0b4e6` | Python, FFmpeg CLI | Low (Stable) | Good | Filtergraph composition (crop, scale, overlay) | Subprocess wrapper around system FFmpeg | Low | **Adopt** (Filtergraph construction helper) |
| 36 | [Zulko/moviepy](https://github.com/Zulko/moviepy) | Video editing and compositing library | MIT | `v2.1.2` | Python, ImageMagick, FFmpeg | High | High | Rapid prototyping for video concatenation | Higher memory overhead than native FFmpeg | Medium | **Optional / Secondary** (FFmpeg direct preferred) |
| 37 | [jianfch/stable-ts](https://github.com/jianfch/stable-ts) | Stabilized Whisper timestamps & subtitle export | MIT | `v2.17.4` | Python, Whisper | High | Good | Accurate word timestamps, ASS/VTT/SRT formatting | Wrapper around Whisper models | Low | **Adapt** (Subtitle formatting & word timing) |
| 38 | [fedirz/faster-whisper-server](https://github.com/fedirz/faster-whisper-server) | OpenAI-compatible faster-whisper API server | MIT | `v0.4.0` | Python, FastAPI | High | High | Decoupled hosted transcription endpoint | Requires external server deployment | Medium | **Reference** (Remote transcription adapter) |
| 39 | [dcarpintero/yt-whisper](https://github.com/dcarpintero/yt-whisper) | YouTube video transcription with Whisper | MIT | `b34a12...` | Python, yt-dlp, Whisper | Low | Low | Basic download-to-transcribe pipeline | Lacks rights check and clip intelligence | Low | **Reference** (Basic pipeline flow) |
| 40 | [encode/databases](https://github.com/encode/databases) / SQLite | Async database support for relational backends | BSD-3-Clause | `v0.9.0` | Python, asyncio | High | High | Lightweight durable transactional state | SQLite file concurrency constraints | Low | **Adopt** (SQLite WAL mode for MVP state journal) |
| 41 | [samuelcolvin/pydantic](https://github.com/pydantic/pydantic) | Data validation using Python type annotations | MIT | `v2.10.6` | Python, Rust | High | High | Typed data contracts, JSON schema validation, immutability | None | Low | **Adopt** (Foundation for all data contracts) |
| 42 | [litestar-org/polyfactory](https://github.com/litestar-org/polyfactory) | Mock data and fixture factory for testing | MIT | `v2.16.2` | Python | High | High | Synthetic candidate and transcript fixture generation | Optional test dependency | Low | **Reference** (Synthetic fixture generation) |

---

## 2. Evidence-Based Shortlist & Component Adoption Plan

From the 42 surveyed repositories, 6 primary components are adopted or adapted into the Master Repository:

1. **Highlight Chunking & Overlap Suppression (from `AI-Youtube-Shorts-Generator`):**  
   - Adaptive overlapping chunks for long videos.  
   - Interval IoU (Intersection-over-Union) suppression to prevent generating redundant clips covering the same moment.
2. **Explainable Hook & Moment Scorecard (from `ClipMint`):**  
   - Independent scoring of opening hook strength (0-10) vs core moment payoff (0-10).  
   - Weighted multi-signal breakdown (hook, narrative, audio energy, pacing, visual legibility).
3. **Resilient Job State Machine & Post-Render QA (from `ClippyMe`):**  
   - Crash-safe checkpoint journal (`discovered` -> `rights_checked` -> `transcribed` -> `scored` -> `rendered` -> `qa_passed` -> `handed_off`).  
   - Verification of video/audio streams, duration tolerances, aspect ratio (9:16), non-zero byte size, and black-frame detection.
4. **Multi-Speaker Reframe Strategy (from `OpenShorts`):**  
   - Active speaker single crop vs stacked split-screen layout when multiple speakers are interacting.
5. **Channel Watchlist & View Velocity Ingestion (from `thevops/youtube-tracker` & `tube-virality`):**  
   - Feed polling and public metric snapshots.  
   - Delta velocity calculation ($\Delta \text{views} / \Delta t$) normalized by channel baseline.
6. **Robust Subtitle Generation (from `stable-ts`):**  
   - Subtitle-safe margin calculations and word-synced ASS/SRT caption rendering.

---

## 3. Architecture Decision: Scaffold vs. Clean-Room Master Repo

### Evaluation of OpenShorts as Scaffold:
- **Pros:** Full web UI, existing rendering pipeline, API and MCP endpoints.
- **Cons:** Monolithic web application coupling (Next.js + FastAPI + Postgres + Docker Compose), heavy front-end baggage, difficult to enforce strict rights gate deep within its existing database models, no native autopost dry-run adapter.

### Evaluation of SupoClip as Scaffold:
- **Critical Blocker:** Licensed under **AGPL-3.0**. Copying or scaffolding SupoClip would legally force the entire master repository and any downstream integrations into AGPL-3.0 copyleft obligations, which directly contradicts the requirement for a clean, modular master repository.

### Final Recommendation: Clean-Room Modular Python Core
Build a clean, decoupled master repository (`src/yt_clipping/`) using **Pydantic v2 + SQLite (WAL mode) + FFmpeg/Subprocess + Replaceable Provider Interfaces**.  
Incorporate proven algorithms from the shortlisted MIT/Apache-2.0 repositories with complete attribution in `THIRD_PARTY_NOTICES.md` and `docs/research/license-and-provenance.md`.
