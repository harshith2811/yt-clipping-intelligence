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
```
- `--channel` *(required)*: YouTube channel ID (`UC...`), `@handle`, or channel URL.
- `--max-videos` *(optional, default: 1)*: Maximum recent uploads to evaluate.
- `--baseline` *(optional, default: 10000.0)*: Channel baseline view velocity benchmark.
- `--render` *(optional)*: Enables full vertical 9:16 rendering.
- `--layout` *(optional, default: `auto`)*: Dynamic layout selection (`auto`, `blur_background`, `split_screen`, `active_speaker`, `crop_center`).
- `--subtitle-preset` *(optional, default: `hormozi`)*: Subtitle style preset.

#### `run`: Full Pipeline Execution
Executes the full pipeline for a verified video from highlight selection through rendering and publishing.
```bash
python -m src.yt_clipping run --video-id <ID> [OPTIONS]
```
- `--video-id` *(required)*: 11-character YouTube video ID.
- `--layout` *(optional, default: `blur_background`)*:
  - `blur_background`: Fits widescreen 16:9 across 1080px with Gaussian-blurred top/bottom backdrop.
  - `active_speaker`: YuNet facial detection with EMA camera tracking centering active subjects.
  - `crop_center`: Direct 9:16 center crop (`607.5x1080` scaled to `1080x1920`).
  - `split_screen`: Dual 9:8 vertical stack for multi-subject podcasts.
- `--preset` *(optional, default: `hormozi`)*:
  - `hormozi`: Bold yellow uppercase font with black outline and active word highlight.
  - `beast_bounce`: High-contrast green-yellow pop aesthetic.
  - `neon_cyber`: Cyan/magenta cyber-glow with drop shadow.
  - `karaoke_gold`: Subtle karaoke progressive fill.
  - `bold_social`: Clean, minimalist white text with black border.
- `--gpu` *(optional)*: Enables hardware NVIDIA NVENC (`h264_nvenc`) encoding.
- `--dry-run` / `--no-dry-run` *(optional, default: `--dry-run`)*: Simulates autopost delivery without webhook dispatches.

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
