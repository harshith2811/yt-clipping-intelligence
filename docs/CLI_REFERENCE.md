# YouTube Clipping Intelligence Platform - CLI Command Reference

Comprehensive operator handbook and exact reference for all command-line tools and subparsers across the platform.

---

## 1. Master Pipeline CLI (`yt-clip` / `python -m src.yt_clipping`)

The master CLI provides operational commands for rights inspection, discovery ranking, pipeline execution, candidate review, rendering, and background services.

### Global Syntax
```bash
python -m src.yt_clipping <COMMAND> [OPTIONS]
# or when installed in environment:
yt-clip <COMMAND> [OPTIONS]
```

---

### Command Inventory

#### `autoprobe`: Autonomous Channel Scan & End-to-End Clipping
Unified workflow that scans a channel, calculates velocity, auto-registers attribution, and optionally renders vertical clips with HTML reports.
```bash
# Sweep channel uploads and calculate view velocity
yt-clip autoprobe --channel "@HubermanLab" --max-videos 1

# End-to-end auto-clipping with Hormozi kinetic captions and auto-layout framing:
yt-clip autoprobe --channel "@Veritasium" --render --layout auto --subtitle-preset hormozi

# End-to-end clipping with animated CTA overlay, pacing polish, and dedicated outro card:
yt-clip autoprobe --channel "@Veritasium" --render --enable-cta --cta-text "Follow for more daily facts" --enable-polish --enable-outro-card --outro-channel-name "Veritasium"
```
**Arguments:**
- `--channel` *(required, `str`)*: YouTube channel ID (`UC...`), `@handle`, or channel URL.
- `--max-videos` *(optional, `int`, default: `1`)*: Maximum recent uploads to evaluate.
- `--baseline` *(optional, `float`, default: `10000.0`)*: Channel baseline view velocity benchmark.
- `--min-duration` *(optional, `float`, default: `15.0`)*: Minimum highlight duration in seconds.
- `--max-duration` *(optional, `float`, default: `60.0`)*: Maximum highlight duration in seconds.
- `--render` *(optional, `flag`)*: Enables full vertical 9:16 rendering.
- `--layout` *(optional, choices: `auto`, `blur_background`, `crop_center`, `split_screen`, `active_speaker`, default: `auto`)*: Dynamic layout selection.
- `--subtitle-preset` *(optional, choices: `hormozi`, `beast_bounce`, `neon_cyber`, `karaoke_gold`, `bold_social`, `karaoke`, `clean_editorial`, `classic`, default: `hormozi`)*: Subtitle style preset.
- `--dry-run` / `--no-dry-run` *(optional, default: `True`)*: Simulates autopost delivery without live webhook dispatches.
- `--db` *(optional, `str`, default: `data/jobs.db`)*: Path to SQLite jobs database.
- `--output-dir` *(optional, `str`, default: `data/rendered_clips`)*: Directory for rendered clips and report.html.
- `--enable-deadair-pruning` *(optional, `flag`, default: `False`)*: Enables DeadAirPruner micro-cuts (removes pauses >0.5s and filler words).
- `--enable-broll` *(optional, `flag`, default: `False`)*: Enables BRollOverlayEngine stock video overlays.
- `--broll-assets-dir` *(optional, `str`, default: `None`)*: Directory containing stock B-roll video assets (default: `assets/broll`).
- `--enable-cta` *(optional, `flag`, default: `False`)*: Enables animated lower-third Call-to-Action overlay banner/pill.
- `--cta-text` *(optional, `str`, default: `"Subscribe to this channel for more"`)*: CTA display text.
- `--cta-timing` *(optional, choices: `end`, `intro`, `persistent`, default: `end`)*: Timing window for CTA appearance.
- `--cta-style` *(optional, choices: `modern_pill`, `neon_banner`, `minimal`, default: `modern_pill`)*: Visual style preset.
- `--cta-margin-bottom` *(optional, `int`, default: `440`)*: Safe-zone bottom margin in px for CTA overlay placement.
- `--enable-outro-card` *(optional, `flag`, default: `False`)*: Enable dedicated animated outro frame with subscribe sequence and soft zen notification chime.
- `--outro-duration` *(optional, `float`, default: `2.5`)*: Duration of the dedicated outro card in seconds.
- `--outro-channel-name` *(optional, `str`, default: `None`)*: Channel or brand name to display on the outro card.
- `--enable-polish` / `--no-enable-polish` *(optional, default: `True`)*: Enables broadcast hook pacing polish (dead-air trimming to ~0.10s) and anti-pop audio fades.

---

#### `run`: Full Pipeline Execution on Authorized Video
Executes the full pipeline for a verified video from highlight selection through rendering and publishing.
```bash
yt-clip run --video-id rsOiZE19RVo --layout active_speaker --subtitle-preset hormozi --enable-outro-card
```
**Arguments:**
- `--video-id` *(required, `str`)*: 11-character YouTube video ID.
- `--min-duration` *(optional, `float`, default: `15.0`)*: Minimum highlight duration in seconds.
- `--max-duration` *(optional, `float`, default: `60.0`)*: Maximum highlight duration in seconds.
- `--dry-run` / `--no-dry-run` *(optional, default: `True`)*: Simulates autopost delivery without webhook dispatches.
- `--layout` *(optional, choices: `blur_background`, `crop_center`, `split_screen`, `active_speaker`, default: `blur_background`)*:
  - `blur_background`: Fits widescreen 16:9 across 1080px with Gaussian-blurred backdrop.
  - `active_speaker`: YuNet facial detection with kinematic trajectory tracking.
  - `crop_center`: Direct 9:16 center crop (`607.5x1080` scaled to `1080x1920`).
  - `split_screen`: Dual 9:8 vertical stack for multi-subject footage.
- `--subtitle-preset` *(optional, choices: `hormozi`, `beast_bounce`, `neon_cyber`, `karaoke_gold`, `bold_social`, `karaoke`, `clean_editorial`, `classic`, default: `hormozi`)*: Subtitle styling preset.
- `--threshold` *(optional, `float`, default: `65.0`)*: Score threshold for auto-approval.
- `--gpu` *(optional, `flag`)*: Enables NVIDIA NVENC (`h264_nvenc`) hardware acceleration.
- `--vcodec` *(optional, choices: `libx264`, `h264_nvenc`, `hevc_nvenc`, default: `libx264`)*: Video encoder codec.
- `--output-dir` *(optional, `str`, default: `data/rendered_clips`)*: Directory for rendered clips.
- `--enable-deadair-pruning` *(optional, `flag`, default: `False`)*: Removes pauses >0.5s and conversational fillers.
- `--enable-broll` *(optional, `flag`, default: `False`)*: Contextual B-roll video overlay.
- `--broll-assets-dir` *(optional, `str`, default: `None`)*: Directory containing stock B-roll assets.
- `--enable-cta` *(optional, `flag`, default: `False`)*: Burns animated lower-third Call-to-Action overlay into video.
- `--cta-text` *(optional, `str`, default: `"Subscribe to this channel for more"`)*: CTA display text.
- `--cta-timing` *(optional, choices: `end`, `intro`, `persistent`, default: `end`)*: Timing window for CTA appearance.
- `--cta-style` *(optional, choices: `modern_pill`, `neon_banner`, `minimal`, default: `modern_pill`)*: Visual style preset.
- `--cta-margin-bottom` *(optional, `int`, default: `440`)*: Safe-zone bottom margin in px for CTA placement.
- `--enable-outro-card` *(optional, `flag`, default: `False`)*: Enable dedicated animated outro frame with subscribe sequence and soft zen notification chime.
- `--outro-duration` *(optional, `float`, default: `2.5`)*: Duration of the dedicated outro card in seconds.
- `--outro-channel-name` *(optional, `str`, default: `None`)*: Channel or brand name to display on the outro card.
- `--enable-polish` / `--no-enable-polish` *(optional, default: `True`)*: Broadcast hook pacing polish and anti-pop audio fades.

---

#### `preview`: Fast Highlight Inspection (No Render)
Scores highlights, displays hook and payoff metrics, and outputs suggested bounds without launching FFmpeg.
```bash
yt-clip preview --video-id rsOiZE19RVo --min-duration 20.0 --max-duration 45.0
```
**Arguments:**
- `--video-id` *(required, `str`)*: Video ID to inspect.
- `--min-duration` *(optional, `float`, default: `15.0`)*: Minimum highlight duration.
- `--max-duration` *(optional, `float`, default: `60.0`)*: Maximum highlight duration.

---

#### `podcast`: Broadcast-Grade Podcast Split-Screen Rendering
Renders broadcast-grade 9:8 stacked vertical Shorts from multi-speaker podcast footage.
```bash
yt-clip podcast --source "data/assets/interview.mp4" --out "data/rendered_clips/podcast.mp4" --duration 30.0 --mode hybrid --host-side left
```
**Arguments:**
- `--source`, `-s` *(required, `str`)*: Path to input podcast widescreen video.
- `--out`, `-o` *(required, `str`)*: Destination path for rendered 9:16 vertical MP4.
- `--start` *(optional, `float`, default: `0.0`)*: Start offset in seconds.
- `--duration`, `-d` *(optional, `float`, default: `30.0`)*: Clip duration in seconds.
- `--mode`, `-m` *(optional, choices: `hybrid`, `stacked_always`, default: `hybrid`)*: Visual layout mode.
- `--host-side` *(optional, choices: `left`, `right`, default: `left`)*: Host seat position in wide shot.
- `--preview` *(optional, `flag`)*: Fast preview mode (540x960 ultrafast resolution).
- `--no-subtitles` *(optional, `flag`)*: Disable subtitle burning.
- `--divider-thickness` *(optional, `int`, default: `4`)*: Split-screen divider bar thickness in pixels.
- `--divider-color` *(optional, `str`, default: `"0x202020"`)*: Split-screen divider bar color in hex format.
- `--enable-cta` *(optional, `flag`)*: Overlay animated Call-to-Action with safe-zone clearance above/below divider.
- `--cta-text` *(optional, `str`, default: `"Subscribe to this channel for more"`)*: Custom CTA text.
- `--cta-timing` *(optional, choices: `end`, `intro`, `persistent`, default: `end`)*: CTA appearance timing.
- `--cta-style` *(optional, choices: `modern_pill`, `neon_banner`, `minimal`, default: `modern_pill`)*: CTA style preset.

---

#### `rights`: Rights Audit Ledger Management
Registers and inspects permissions in the compliance ledger.
```bash
# Register authorized asset
yt-clip rights register --video-id rsOiZE19RVo --basis OPERATOR_ASSET --owner "Creator Name" --proof "AGREEMENT-001"

# Verify asset status
yt-clip rights check --video-id rsOiZE19RVo
```
**Subcommands:**
- `rights register`:
  - `--video-id` *(required, `str`)*: YouTube Video ID.
  - `--basis` *(required, choices: `OWNED`, `EXPLICIT_PERMISSION`, `CREATIVE_COMMONS`, `OPERATOR_ASSET`)*: Legal basis.
  - `--owner` *(required, `str`)*: Content owner or creator name.
  - `--license-url` *(optional, `str`, default: `""`)*: License documentation URL.
  - `--proof` *(optional, `str`, default: `""`)*: Proof reference / agreement ID.
  - `--valid-until` *(optional, `str`, default: `None`)*: Expiration date (ISO 8601).
  - `--notes` *(optional, `str`, default: `""`)*: Audit rationale.
  - `--ledger` *(optional, `str`, default: `data/rights_ledger.json`)*: Path to rights ledger.
- `rights check`:
  - `--video-id` *(required, `str`)*: YouTube Video ID.
  - `--ledger` *(optional, `str`, default: `data/rights_ledger.json`)*: Path to rights ledger.

---

#### `channels`: Creator Channel Registry Management
```bash
# Add creator
yt-clip channels add --channel-id UC2D2CMWXMOVWx7giW1n3LIg --name "Huberman Lab" --handle "@hubermanlab" --baseline 150000

# List monitored creators
yt-clip channels list --all

# Deactivate creator
yt-clip channels remove --channel-id UC2D2CMWXMOVWx7giW1n3LIg
```
**Subcommands:**
- `channels add`: `--channel-id` (req), `--name` (req), `--handle`, `--url`, `--baseline` (default: 10000.0), `--db` (default: `data/jobs.db`).
- `channels list`: `--all` (include inactive), `--db` (default: `data/jobs.db`).
- `channels remove`: `--channel-id` (req), `--db` (default: `data/jobs.db`).

---

#### `doctor`: Platform Health & Diagnostics
Inspects and diagnoses local dependencies, FFmpeg codecs, hardware acceleration, and SQLite connectivity.
```bash
yt-clip doctor --db data/jobs.db
```
**Arguments:**
- `--db` *(optional, `str`, default: `data/jobs.db`)*: Path to SQLite jobs database.

---

#### `config`: Configuration Inspection & Validation
```bash
yt-clip config validate
```
**Subcommands:**
- `config validate`: Validates active environment variables against schema and outputs safe masked configuration summary.

---

#### `cleanup`: Storage Lifecycle Pruner
Prunes intermediate rendering chunks, stale temp files, and expired cache artifacts.
```bash
yt-clip cleanup --days 7 --dry-run
yt-clip cleanup --temp-only --no-dry-run
```
**Arguments:**
- `--days` *(optional, `int`, default: `7`)*: Retention threshold in days.
- `--temp-only` *(optional, `flag`)*: Clean only temporary rendering directories.
- `--dry-run` / `--no-dry-run` *(optional, default: `True`)*: Preview deletions without executing.

---

#### `daemon`: Background Continuous Polling Daemon
Runs the continuous background channel polling service.
```bash
yt-clip daemon --interval 300 --max-iterations 10
```
**Arguments:**
- `--interval` *(optional, `int`, default: `300`)*: Polling cycle interval in seconds.
- `--max-iterations` *(optional, `int`, default: `None`)*: Stop after N iterations (for testing).

---

#### `queue`: Priority Job Queue Telemetry
```bash
yt-clip queue status --db data/jobs.db
```
**Subcommands:**
- `queue status`: Displays active queue size, priority breakdown, and worker lease status.

---

#### `dlq`: Webhook Dead-Letter Queue Management
Inspects and retries failed autopost webhook dispatches.
```bash
yt-clip dlq list
yt-clip dlq retry --item-id <ITEM_UUID>
```
**Subcommands:**
- `dlq list`: Lists failed webhook delivery records.
- `dlq retry`: `--item-id` *(required, `str`)*: Retries delivery for a specific dead-letter record.

---

#### `quota`: YouTube Data API v3 Quota Expenditure
Displays today's quota expenditure, remaining quota units, and cost breakdown.
```bash
yt-clip quota status
```
**Subcommands:**
- `quota status`: Shows daily quota usage (budget: 10,000 units/day).

---

#### `ingest`: Media Asset Ingestion & Header Probe
Downloads or verifies authorized media asset and inspects stream headers.
```bash
yt-clip ingest --video-id rsOiZE19RVo --ledger data/rights_ledger.json
```
**Arguments:**
- `--video-id` *(required, `str`)*: Video ID or YouTube URL to ingest.
- `--ledger` *(optional, `str`, default: `data/rights_ledger.json`)*: Path to rights ledger.
- `--assets-dir` *(optional, `str`, default: `data/assets`)*: Directory for source assets.
- `--db` *(optional, `str`, default: `data/jobs.db`)*: Path to SQLite database.

---

#### `jobs`: SQLite WAL Journal & Pipeline Status
Lists queued, running, succeeded, or failed jobs.
```bash
yt-clip jobs --status SUCCEEDED --db data/jobs.db
```
**Arguments:**
- `--status` *(optional, choices: `PENDING`, `IN_PROGRESS`, `SUCCEEDED`, `FAILED`, `RETRY_PENDING`)*: Filter by status.
- `--db` *(optional, `str`, default: `data/jobs.db`)*: Path to SQLite jobs database.

---

#### `tts`: Voiceover Speech Synthesis
Synthesizes speech audio tracks using local Edge-TTS or offline fallbacks.
```bash
yt-clip tts --text "Welcome back to the channel" --voice "en-US-ChristopherNeural" --output "data/assets/sample.mp3"
```
**Arguments:**
- `--text` *(required, `str`)*: Text to synthesize.
- `--voice` *(optional, `str`, default: `"en-US-ChristopherNeural"`)*: Neural voice name (`christopher`, `jenny`, `guy`, `aria`, `eric`).
- `--output` *(optional, `str`, default: auto-generated cache path)*: Output audio file path (.mp3/.wav).

---

#### `discovery`: Metric Discovery & Velocity Simulation
```bash
yt-clip discovery --channel-id UC_sample --avg-views 50000 --views 125000 --duration 720.0
```
**Arguments:**
- `--channel-id`, `--channel-name`, `--avg-views`, `--sample-video-id`, `--sample-title`, `--views`, `--duration`.

---

#### `heatmap`: Audience Retention Curve & ASCII Waveform
Extracts and visualizes the crowd-sourced replay curve.
```bash
yt-clip heatmap --video-id rsOiZE19RVo --visual
```
**Arguments:**
- `--video-id` *(required, `str`)*: YouTube Video ID.
- `--visual` *(optional, `flag`)*: Renders terminal ASCII retention waveform.
- `--cache-dir` *(optional, `str`, default: `data/heatmaps`)*: Cache directory.

---

#### `trends`: YouTube Macro Trends & Velocity
Queries regional trending charts or evaluates individual video virality velocity.
```bash
yt-clip trends --chart popular --region US --limit 10
yt-clip trends --video-id rsOiZE19RVo
```
**Arguments:**
- `--video-id`: Video ID to evaluate.
- `--chart` *(choices: `popular`)*: Fetch official YouTube Trending chart.
- `--region` *(default: `US`)*: ISO 3166-1 alpha-2 region code.
- `--category`: YouTube Video Category ID.
- `--limit` *(default: `10`)*: Maximum trending videos to display.

---

#### `mcp-server` & `mcp serve`: Native Model Context Protocol Server
Launches the MCP JSON-RPC 2.0 stdio server for agentic LLM orchestration.
```bash
yt-clip mcp-server --log-level INFO
# or alias:
yt-clip mcp serve --log-level INFO
```
**Arguments:**
- `--db` *(optional, default: `data/jobs.db`)*: Path to SQLite jobs database.
- `--assets-dir` *(optional, default: `data/assets`)*: Source assets directory.
- `--transcripts-dir` *(optional, default: `data/transcripts`)*: Transcripts directory.
- `--output-dir` *(optional, default: `data/rendered_clips`)*: Rendered output directory.
- `--log-level` *(optional, choices: `DEBUG`, `INFO`, `WARNING`, `ERROR`, default: `INFO`)*: Stderr logging level.

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
- `add`: `python channel_watcher.py add @hubermanlab --baseline 150000 --policy OPEN_AFFILIATE`
  - `identifier` *(required)*: `@handle`, channel URL, or canonical ID (`UC...`).
  - `--baseline` *(default: `20000`)*: Historical baseline view benchmark.
  - `--policy` *(choices: `OPEN_AFFILIATE`, `CREATIVE_COMMONS`, `PARTNER_PROGRAM`, `STRICT_COPYRIGHT`, default: `OPEN_AFFILIATE`)*.
- `list`: `python channel_watcher.py list`
- `scan`: `python channel_watcher.py scan` (Immediate live RSS discovery sweep).
- `test-feed`: `python channel_watcher.py test-feed @hubermanlab` (Validates live feed connectivity without saving).
- `pause`: `python channel_watcher.py pause UC2D2CMWXMOVWx7giW1n3LIg`
- `resume`: `python channel_watcher.py resume UC2D2CMWXMOVWx7giW1n3LIg`
- `remove`: `python channel_watcher.py remove UC2D2CMWXMOVWx7giW1n3LIg`

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
- `--interval <SECONDS>` *(default: `300`)*: Sleep duration between discovery sweeps.
- `--cycles <COUNT>` *(optional)*: Maximum poll cycles before halting (ideal for scheduled cron jobs).
- `--websub`: Starts background HTTP server for WebSub push alerts.
- `--websub-port <PORT>` *(default: `8088`)*: Port for WebSub HTTP listener.

---

## 4. Standalone Podcast Short Maker CLI (`python -m yt_clipping.podcast.cli`)

Dedicated standalone CLI for generating broadcast-quality 9:8 stacked split-screen vertical Shorts.

### Syntax
```bash
python -m yt_clipping.podcast.cli [OPTIONS]
```
- `--source`, `-s` *(required)*: Path to input podcast widescreen video.
- `--out`, `-o` *(required)*: Destination path for rendered 9:16 vertical MP4.
- `--start` *(default: `0.0`)*: Start offset in seconds.
- `--duration`, `-d` *(default: `30.0`)*: Clip duration in seconds.
- `--mode`, `-m` *(choices: `hybrid`, `stacked_always`, default: `hybrid`)*: Layout mode.
- `--host-side` *(choices: `left`, `right`, default: `left`)*: Side where host sits in wide shot.
- `--preview` *(flag)*: Fast preview mode (540x960 ultrafast resolution).
- `--no-subtitles` *(flag)*: Disable subtitle burning.
