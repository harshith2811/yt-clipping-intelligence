# YouTube Clipping Intelligence Platform - CLI Command Reference

Comprehensive operator handbook for all command-line tools across the platform.

---

## 1. Primary Pipeline CLI (`yt-clip` / `python -m src.yt_clipping`)

The master CLI orchestrates end-to-end highlight detection, rendering, quality assurance, and publishing.

### Global Syntax
```bash
python -m src.yt_clipping [SUBCOMMAND] [OPTIONS]
# or when installed in environment:
yt-clip [SUBCOMMAND] [OPTIONS]
```

### Subcommands

#### `autoprobe`: Autonomous Channel Scan & End-to-End Clipping
Unified workflow that scans a channel, calculates velocity, auto-registers affiliate attribution, and optionally renders vertical clips with HTML reports.
```bash
# Sweep channel uploads and calculate view velocity
yt-clip autoprobe --channel "@HubermanLab" --max-videos 1

# End-to-end auto-clipping with Hormozi kinetic captions and auto-layout framing:
yt-clip autoprobe --channel "@Veritasium" --render --layout auto --subtitle-preset hormozi

# End-to-end clipping with animated CTA overlay and pacing polish:
yt-clip autoprobe --channel "@Veritasium" --render --enable-cta --cta-text "Follow for more science shorts" --cta-style modern_pill --enable-polish
```
- `--channel` *(required)*: YouTube channel ID (`UC...`), `@handle`, or channel URL.
- `--max-videos` *(optional, default: 1)*: Maximum recent uploads to evaluate.
- `--baseline` *(optional, default: 10000.0)*: Channel baseline view velocity benchmark.
- `--min-duration` *(optional, default: 15.0)*: Minimum highlight duration in seconds.
- `--max-duration` *(optional, default: 60.0)*: Maximum highlight duration in seconds.
- `--render` *(optional)*: Enables full vertical 9:16 rendering.
- `--layout` *(optional, default: `auto`)*: Dynamic layout selection (`auto`, `blur_background`, `split_screen`, `active_speaker`, `crop_center`).
- `--subtitle-preset` *(optional, default: `hormozi`)*: Subtitle style preset (`hormozi`, `beast_bounce`, `neon_cyber`, `karaoke_gold`, `bold_social`, `karaoke`, `clean_editorial`, `classic`).
- `--dry-run` / `--no-dry-run` *(optional, default: `--dry-run`)*: Simulates autopost delivery without webhook dispatches.
- `--output-dir` *(optional, default: `data/rendered_clips`)*: Directory for rendered clips and report.html.
- `--enable-deadair-pruning` *(optional, default: False)*: Enables DeadAirPruner micro-cuts (removes pauses >0.5s and filler words).
- `--enable-broll` *(optional, default: False)*: Enables BRollOverlayEngine stock video overlays.
- `--broll-assets-dir` *(optional)*: Directory containing stock B-roll video assets (default: `assets/broll`).
- `--enable-cta` *(optional, default: False)*: Enables animated lower-third Call-to-Action overlay banner/pill.
- `--cta-text` *(optional, default: "Subscribe to this channel for more")*: CTA display text.
- `--cta-timing` *(optional, choices: `end`, `intro`, `persistent`; default: `end`)*: Timing window for CTA appearance.
- `--cta-style` *(optional, choices: `modern_pill`, `neon_banner`, `minimal`; default: `modern_pill`)*: Visual style preset.
- `--enable-polish` / `--no-enable-polish` *(optional, default: True)*: Enables broadcast hook pacing polish (dead-air trimming to ~0.10s) and anti-pop audio fades.

#### `run`: Full Pipeline Execution
Executes the full pipeline for a verified video from highlight selection through rendering and publishing.
```bash
python -m src.yt_clipping run --video-id <ID> [OPTIONS]
```
- `--video-id` *(required)*: 11-character YouTube video ID.
- `--min-duration` *(optional, default: 15.0)*: Minimum highlight duration in seconds.
- `--max-duration` *(optional, default: 60.0)*: Maximum highlight duration in seconds.
- `--layout` *(optional, default: `blur_background`)*:
  - `blur_background`: Fits widescreen 16:9 across 1080px with Gaussian-blurred top/bottom backdrop.
  - `active_speaker`: YuNet facial detection with EMA camera tracking centering active subjects.
  - `crop_center`: Direct 9:16 center crop (`607.5x1080` scaled to `1080x1920`).
  - `split_screen`: Dual 9:8 vertical stack for multi-subject podcasts.
- `--subtitle-preset` *(optional, default: `hormozi`)*:
  - `hormozi`: Bold yellow uppercase font with black outline and active word highlight.
  - `beast_bounce`: High-contrast green-yellow pop aesthetic.
  - `neon_cyber`: Cyan/magenta cyber-glow with drop shadow.
  - `karaoke_gold`: Subtle karaoke progressive fill.
  - `bold_social`: Clean, minimalist white text with black border.
- `--threshold` *(optional, default: 65.0)*: Score threshold for auto-approval.
- `--gpu` *(optional)*: Enables hardware NVIDIA NVENC (`h264_nvenc`) encoding.
- `--vcodec` *(optional, default: `libx264`)*: Video encoder codec (`libx264`, `h264_nvenc`, `hevc_nvenc`).
- `--output-dir` *(optional, default: `data/rendered_clips`)*: Directory for rendered clips.
- `--dry-run` / `--no-dry-run` *(optional, default: `--dry-run`)*: Simulates autopost delivery without webhook dispatches.
- `--enable-deadair-pruning` *(optional, default: False)*: Removes pauses >0.5s and conversational fillers.
- `--enable-broll` *(optional, default: False)*: Contextual B-roll video overlay.
- `--broll-assets-dir` *(optional)*: Directory containing stock B-roll assets.
- `--enable-cta` *(optional, default: False)*: Burns animated lower-third Call-to-Action overlay into video or subtitles.
- `--cta-text` *(optional, default: "Subscribe to this channel for more")*: CTA display text.
- `--cta-timing` *(optional, choices: `end`, `intro`, `persistent`; default: `end`)*: Timing window for CTA appearance.
- `--cta-style` *(optional, choices: `modern_pill`, `neon_banner`, `minimal`; default: `modern_pill`)*: Visual style preset.
- `--enable-polish` / `--no-enable-polish` *(optional, default: True)*: Broadcast hook pacing polish and anti-pop audio fades.

#### `podcast`: Broadcast-Grade Podcast Split-Screen Rendering
Renders broadcast-grade 9:8 stacked vertical Shorts from multi-speaker podcast footage directly from the master CLI.
```bash
python -m src.yt_clipping podcast --source "data/assets/interview.mp4" --out "data/rendered_clips/podcast.mp4" --duration 30.0
```
- `--source`, `-s` *(required)*: Path to input podcast widescreen video.
- `--out`, `-o` *(required)*: Destination path for rendered 9:16 vertical MP4.
- `--start` *(optional, default: 0.0)*: Start offset in seconds.
- `--duration`, `-d` *(optional, default: 30.0)*: Clip duration in seconds.
- `--mode`, `-m` *(optional, choices: `hybrid`, `stacked_always`; default: `hybrid`)*: Visual layout mode.
- `--host-side` *(optional, choices: `left`, `right`; default: `left`)*: Host seat position in wide shot.
- `--preview` *(optional)*: Fast preview mode (540x960 ultrafast resolution).
- `--no-subtitles` *(optional)*: Disable subtitle burning.
- `--divider-thickness` *(optional, default: 4)*: Split-screen divider bar thickness in pixels.
- `--divider-color` *(optional, default: `0x202020`)*: Split-screen divider bar color in hex format.
- `--enable-cta` *(optional)*: Overlay animated Call-to-Action with safe-zone clearance above/below the divider.
- `--cta-text` *(optional, default: `"Subscribe to this channel for more"`)*: Custom CTA text message.
- `--cta-timing` *(optional, choices: `end`, `intro`, `persistent`; default: `end`)*: Timing window for CTA appearance.
- `--cta-style` *(optional, choices: `modern_pill`, `neon_banner`, `minimal`; default: `modern_pill`)*: Visual style preset.

#### `preview`: Fast Highlight Inspection (No Render)
Scores highlights, displays hook and payoff metrics, and outputs suggested bounds without launching FFmpeg.
```bash
python -m src.yt_clipping preview --video-id <ID>
```

#### `heatmap`: Audience Retention Curve & ASCII Waveform
Extracts and visualizes the crowd-sourced replay curve.
```bash
python -m src.yt_clipping heatmap --video-id <ID> --visual
```
- `--visual`: Renders terminal ASCII waveform and lists prominent replay peaks.

#### `trends`: YouTube Macro Trends & Velocity
Queries regional trending charts or evaluates individual video virality velocity.
```bash
# Query trending chart
python -m src.yt_clipping trends --chart popular --region US --limit 10

# Evaluate single video
python -m src.yt_clipping trends --video-id <ID>
```

#### `rights`: Rights Audit Ledger Management
Registers and inspects permissions in the compliance ledger.
```bash
# Register authorized asset
python -m src.yt_clipping rights register --video-id <ID> --basis OPEN_AFFILIATE --owner "Creator Name" --proof "AGREEMENT-001"

# Verify asset status
python -m src.yt_clipping rights check --video-id <ID>
```

#### `jobs`: SQLite WAL Journal & Pipeline Status
Lists queued, running, succeeded, or failed jobs.
```bash
python -m src.yt_clipping jobs --status SUCCEEDED --limit 20
```

#### `tts`: Voiceover Speech Synthesis
Synthesizes speech audio tracks using local edge TTS.
```bash
python -m src.yt_clipping tts --text "Welcome back to the channel" --output "data/assets/tts_sample.mp3"
```

#### `mcp-server` / `mcp serve`: Native Model Context Protocol Server
Launches the MCP JSON-RPC 2.0 stdio server for agentic IDE and LLM orchestration.
```bash
python -m src.yt_clipping mcp-server --log-level INFO
```

---

## 2. Channel Watcher CLI (`channel_watcher.py` / `channel-watcher`)

Manages the registry of monitored creators, channel policies, and triggers instant manual discovery scans.

### Syntax
```bash
python channel_watcher.py <SUBCOMMAND> [OPTIONS]
# or
channel-watcher <SUBCOMMAND> [OPTIONS]
```

### Subcommands

#### `add`: Register a Creator Channel
Automatically resolves `@handles`, custom URLs (`/c/`, `/user/`), or canonical `UC...` IDs.
```bash
python channel_watcher.py add @hubermanlab --baseline 150000 --policy OPEN_AFFILIATE
python channel_watcher.py add @GoogleDevelopers --baseline 20000 --policy OPEN_AFFILIATE
```
- `identifier`: Channel handle (`@handle`), channel URL, or canonical ID (`UC...`).
- `--baseline` *(default: 20000)*: Historical 30-day baseline view benchmark.
- `--policy` *(default: `OPEN_AFFILIATE`)*: `OPEN_AFFILIATE`, `CREATIVE_COMMONS`, `PARTNER_PROGRAM`, `STRICT_COPYRIGHT`.

#### `list`: Display Monitored Channels
Prints active channels, clipping policies, and last polled timestamps.
```bash
python channel_watcher.py list
```

#### `scan`: Immediate Live RSS Discovery Sweep
Polls all active channels, computes early-hour velocity, updates SQLite, and enqueues breakout candidates.
```bash
python channel_watcher.py scan
```

#### `test-feed`: Test Atom XML Parsing
Validates live feed connectivity and prints the 5 latest uploads without saving to database.
```bash
python channel_watcher.py test-feed @hubermanlab
```

#### `pause` & `resume`: Temporary State Control
Temporarily excludes a channel from scheduled pinger cycles without deleting its historical records.
```bash
python channel_watcher.py pause UC2D2CMWXMOVWx7giW1n3LIg
python channel_watcher.py resume UC2D2CMWXMOVWx7giW1n3LIg
```

#### `remove`: Deactivate Channel
Deactivates a channel from the active monitoring pool.
```bash
python channel_watcher.py remove UC2D2CMWXMOVWx7giW1n3LIg
```

---

## 3. Pinger Daemon CLI (`pinger_daemon.py` / `pinger-daemon`)

Runs continuous background monitoring or single-sweep cron jobs.

### Syntax
```bash
python pinger_daemon.py [OPTIONS]
# or
pinger-daemon [OPTIONS]
```

### Options
- `--interval <SECONDS>` *(default: 300)*: Sleep duration between discovery sweeps.
- `--cycles <COUNT>` *(optional)*: Maximum poll cycles before halting (ideal for scheduled cron jobs).
- `--websub`: Starts background HTTP server for WebSub push alerts.
- `--websub-port <PORT>` *(default: 8088)*: Port for WebSub HTTP listener.

### Examples
```bash
# Run continuous background daemon with 5-minute intervals
python pinger_daemon.py --interval 300

# Run a single sweep for cron execution
python pinger_daemon.py --cycles 1

# Run with WebSub push listener active on port 8088
python pinger_daemon.py --interval 120 --websub --websub-port 8088
```

---

## 4. Standalone Podcast Short Maker CLI (`python -m yt_clipping.podcast.cli`)

Dedicated standalone CLI for generating broadcast-quality 9:8 stacked split-screen vertical Shorts from multi-speaker podcast recordings.

### Syntax
```bash
python -m yt_clipping.podcast.cli [OPTIONS]
```

### Options
- `--input-video <PATH>` *(required)*: Source 16:9 widescreen video file.
- `--output <PATH>` *(required)*: Destination path for rendered 9:16 vertical MP4.
- `--start-time <SECONDS>` *(optional, default: 0.0)*: Start timestamp in seconds.
- `--duration <SECONDS>` *(optional, default: 30.0)*: Clip duration in seconds.
- `--host-x <RATIO>` *(optional, default: 0.25)*: Horizontal center ratio for host panel ($0.0 - 1.0$).
- `--guest-x <RATIO>` *(optional, default: 0.75)*: Horizontal center ratio for guest panel ($0.0 - 1.0$).
- `--divider-thickness <PIXELS>` *(optional, default: 20)*: Height of center divider bar in pixels.
- `--divider-color <HEX>` *(optional, default: `#1E293B`)*: Hex color code for divider bar.
- `--diarize`: Runs speaker diarization (Pyannote or zero-VRAM acoustic energy fallback).
- `--burn-subtitles`: Generates and burns center-divider aligned ASS subtitles.
- `--gpu`: Enables NVIDIA NVENC hardware acceleration.

### Example
```bash
python -m yt_clipping.podcast.cli \
  --input-video "data/assets/interview.mp4" \
  --output "data/rendered_clips/podcast_short.mp4" \
  --start-time 45.0 \
  --duration 35.0 \
  --host-x 0.25 \
  --guest-x 0.75 \
  --divider-color "#1E293B" \
  --divider-thickness 20 \
  --diarize \
  --burn-subtitles \
  --gpu
```

---

## 5. Standalone Trend & Attribution CLIs

### TrendScorer CLI (`trend_scorer.py`)
Evaluates video views, age, like-to-view ratio (LVR), and comment-to-view ratio (CVR) against channel baseline:
```bash
python trend_scorer.py
```

### AttributionEngine CLI (`attribution_engine.py`)
Generates standardized fair-use and creator affiliate attribution descriptions:
```bash
python attribution_engine.py
```

---

## 6. Environment Variables Reference

The platform dynamically respects the following environment configuration variables (configurable via `.env`):

| Variable | Type | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | `string` | *(empty)* | Google Gemini Flash API key for cloud highlight discovery (optional; pure local fallback). |
| `YOUTUBE_API_KEY` | `string` | *(empty)* | YouTube Data API v3 key (optional; zero-quota RSS used by default). |
| `FFMPEG_BINARY` | `string` | `ffmpeg` | Path or command for FFmpeg executable. |
| `FFPROBE_BINARY` | `string` | `ffprobe` | Path or command for FFprobe executable (OpenCV fallback if missing). |
| `DEFAULT_VIDEO_CODEC` | `string` | `libx264` | Default video encoder (`libx264`, `h264_nvenc`). |
| `DEVICE` | `string` | `auto` | Execution device target (`cuda`, `cpu`, `auto`). |
| `LOG_LEVEL` | `string` | `INFO` | Console logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `AUTOPOST_WEBHOOK_URL` | `string` | *(empty)* | Destination REST endpoint for published clip webhooks. |
| `AUTOPOST_WEBHOOK_SECRET`| `string`| *(empty)* | HMAC-SHA256 signature secret for secure webhook payloads. |
