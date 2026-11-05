"""
CLI argument parser schema and subparser declarations.
"""

import argparse

from .commands import (
    cmd_run,
    cmd_discovery,
    cmd_heatmap,
    cmd_trends,
    cmd_channels,
    cmd_daemon,
    cmd_jobs,
    cmd_queue,
    cmd_dlq,
    cmd_doctor,
    cmd_autoprobe,
    cmd_config_validate,
    cmd_rights_register,
    cmd_rights_check,
    cmd_ingest,
    cmd_quota,
    cmd_tts,
    cmd_preview,
    cmd_cleanup,
    cmd_podcast,
    cmd_mcp_server,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-clip",
        description="YouTube Clipping Intelligence Platform CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Doctor command
    p_doc = subparsers.add_parser("doctor", help="Inspect and diagnose local platform dependencies and environment")
    p_doc.add_argument("--db", default="data/jobs.db", help="Path to SQLite jobs database")
    p_doc.set_defaults(func=cmd_doctor)

    # Config command
    p_cfg = subparsers.add_parser("config", help="Inspect and validate active application configuration")
    cfg_sub = p_cfg.add_subparsers(dest="config_cmd", required=True)
    p_cfg_val = cfg_sub.add_parser("validate", help="Validate environment variables and print active config")
    p_cfg_val.set_defaults(func=cmd_config_validate)

    # Cleanup command
    p_clean = subparsers.add_parser("cleanup", help="Prune intermediate rendering chunks and cache artifacts")
    p_clean.add_argument("--days", type=int, default=7, help="Retention period in days (default: 7)")
    p_clean.add_argument("--temp-only", action="store_true", help="Clean only temporary rendering files")
    p_clean.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=True, help="Simulate cleanup without deleting (default true)")
    p_clean.set_defaults(func=cmd_cleanup)

    # Channels command
    p_chan = subparsers.add_parser("channels", help="Manage monitored YouTube creator channel registry")
    chan_sub = p_chan.add_subparsers(dest="channel_cmd", required=True)

    p_ch_add = chan_sub.add_parser("add", help="Add or update monitored channel")
    p_ch_add.add_argument("--channel-id", required=True, help="Canonical YouTube channel ID (UC...)")
    p_ch_add.add_argument("--name", required=True, help="Creator or channel name")
    p_ch_add.add_argument("--handle", default=None, help="Channel handle (@creator)")
    p_ch_add.add_argument("--url", default=None, help="Channel URL")
    p_ch_add.add_argument("--baseline", type=float, default=10000.0, help="Baseline view benchmark")
    p_ch_add.add_argument("--db", default="data/jobs.db", help="Path to SQLite database")

    p_ch_list = chan_sub.add_parser("list", help="List monitored channels")
    p_ch_list.add_argument("--all", action="store_true", help="Include inactive channels")
    p_ch_list.add_argument("--db", default="data/jobs.db", help="Path to SQLite database")

    p_ch_rem = chan_sub.add_parser("remove", help="Deactivate monitored channel")
    p_ch_rem.add_argument("--channel-id", required=True, help="Channel ID or handle to remove")
    p_ch_rem.add_argument("--db", default="data/jobs.db", help="Path to SQLite database")
    p_chan.set_defaults(func=cmd_channels)

    # Daemon command
    p_daemon = subparsers.add_parser("daemon", help="Run continuous background channel polling daemon")
    p_daemon.add_argument("--interval", type=int, default=300, help="Polling cycle interval in seconds (default: 300)")
    p_daemon.add_argument("--max-iterations", type=int, default=None, help="Stop after N cycles (for testing)")
    p_daemon.set_defaults(func=cmd_daemon)

    # Queue command
    p_queue = subparsers.add_parser("queue", help="Inspect priority job queue status")
    queue_sub = p_queue.add_subparsers(dest="queue_cmd", required=True)
    p_q_stat = queue_sub.add_parser("status", help="Display job queue status and counts")
    p_q_stat.add_argument("--db", default="data/jobs.db", help="Path to SQLite jobs database")

    p_q_work = queue_sub.add_parser("worker", help="Run 24/7 background job queue worker")
    p_q_work.add_argument("--db", default="data/jobs.db", help="Path to SQLite jobs database")
    p_q_work.add_argument("--poll-interval", type=float, default=5.0, help="Poll interval in seconds")
    p_q_work.add_argument("--max-jobs", type=int, default=None, help="Max jobs to process before exiting (optional)")
    p_q_work.add_argument("--output-dir", default="data/rendered_clips", help="Output directory for rendered clips")
    p_queue.set_defaults(func=cmd_queue)

    # DLQ command
    p_dlq = subparsers.add_parser("dlq", help="Inspect and retry webhook dead-letter queue records")
    dlq_sub = p_dlq.add_subparsers(dest="dlq_cmd", required=True)
    p_dlq_list = dlq_sub.add_parser("list", help="List failed webhook deliveries")
    p_dlq_list.add_argument("--db", default="data/jobs.db", help="Path to SQLite database")
    p_dlq_retry = dlq_sub.add_parser("retry", help="Retry delivery for a dead-letter item")
    p_dlq_retry.add_argument("--item-id", required=True, help="DLQ Item ID to retry")
    p_dlq_retry.add_argument("--db", default="data/jobs.db", help="Path to SQLite database")
    p_dlq.set_defaults(func=cmd_dlq)

    # Quota command
    p_quota = subparsers.add_parser("quota", help="Inspect daily YouTube Data API quota expenditure")
    quota_sub = p_quota.add_subparsers(dest="quota_cmd", required=True)
    p_quota_stat = quota_sub.add_parser("status", help="Show today's quota usage, limits, and cost control")
    p_quota_stat.add_argument("--db", default="data/jobs.db", help="Path to SQLite database")
    p_quota.set_defaults(func=cmd_quota)

    # Ingest command
    p_ing = subparsers.add_parser("ingest", help="Ingest and probe authorized video asset")
    p_ing.add_argument("--video-id", required=True, help="Video ID or URL to ingest")
    p_ing.add_argument("--ledger", default="data/rights_ledger.json", help="Path to rights ledger")
    p_ing.add_argument("--assets-dir", default="data/assets", help="Directory for source assets")
    p_ing.add_argument("--db", default="data/jobs.db", help="Path to SQLite database")
    p_ing.set_defaults(func=cmd_ingest)

    # Rights command
    p_rights = subparsers.add_parser("rights", help="Inspect and register content rights")
    rights_sub = p_rights.add_subparsers(dest="rights_cmd", required=True)

    p_r_reg = rights_sub.add_parser("register", help="Register verified rights for a video")
    p_r_reg.add_argument("--video-id", required=True, help="YouTube Video ID")
    p_r_reg.add_argument("--basis", required=True, choices=["OWNED", "EXPLICIT_PERMISSION", "CREATIVE_COMMONS", "OPERATOR_ASSET"])
    p_r_reg.add_argument("--owner", required=True, help="Content owner or creator name")
    p_r_reg.add_argument("--license-url", default="", help="License documentation URL")
    p_r_reg.add_argument("--proof", default="", help="Proof reference / agreement ID")
    p_r_reg.add_argument("--valid-until", default=None, help="Expiration date (ISO 8601)")
    p_r_reg.add_argument("--notes", default="", help="Audit rationale")
    p_r_reg.add_argument("--ledger", default="data/rights_ledger.json", help="Path to rights ledger")
    p_r_reg.set_defaults(func=cmd_rights_register)

    p_r_chk = rights_sub.add_parser("check", help="Check rights status for a video")
    p_r_chk.add_argument("--video-id", required=True, help="YouTube Video ID")
    p_r_chk.add_argument("--ledger", default="data/rights_ledger.json", help="Path to rights ledger")
    p_r_chk.set_defaults(func=cmd_rights_check)

    # Autoprobe command (Unified end-to-end channel scan, virality evaluation, and clipping)
    p_auto = subparsers.add_parser("autoprobe", help="Autonomous end-to-end channel scan, virality evaluation, and clipping")
    p_auto.add_argument("--channel", required=True, help="YouTube channel ID, @handle, or URL")
    p_auto.add_argument("--max-videos", type=int, default=1, help="Max recent uploads to evaluate (default: 1)")
    p_auto.add_argument("--baseline", type=float, default=10000.0, help="Channel baseline view velocity benchmark")
    p_auto.add_argument("--min-duration", type=float, default=15.0, help="Minimum highlight clip duration in seconds (default: 15.0)")
    p_auto.add_argument("--max-duration", type=float, default=60.0, help="Maximum highlight clip duration in seconds (default: 60.0)")
    p_auto.add_argument("--render", action="store_true", help="Render top candidate to vertical 9:16 short")
    p_auto.add_argument("--layout", default="auto", choices=["auto", "blur_background", "crop_center", "split_screen", "active_speaker"], help="Visual layout profile (default auto)")
    p_auto.add_argument("--subtitle-preset", default="hormozi", choices=["hormozi", "beast_bounce", "neon_cyber", "karaoke_gold", "bold_social", "karaoke", "clean_editorial", "classic"], help="Subtitle aesthetic preset")
    p_auto.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=True, help="Dry-run autopost handoff simulation (default true)")
    p_auto.add_argument("--db", default="data/jobs.db", help="Path to SQLite database")
    p_auto.add_argument("--output-dir", default="data/rendered_clips", help="Directory for rendered clips and report.html")
    p_auto.add_argument(
        "--enable-deadair-pruning",
        action="store_true",
        default=False,
        help="Enable DeadAirPruner micro-cuts during rendering (removes pauses >0.5s and filler words)",
    )
    p_auto.add_argument(
        "--enable-broll",
        action="store_true",
        default=False,
        help="Enable BRollOverlayEngine stock video overlays during rendering",
    )
    p_auto.add_argument(
        "--broll-assets-dir",
        default=None,
        help="Directory containing stock B-roll video assets (default: assets/broll)",
    )
    p_auto.add_argument(
        "--enable-cta",
        action="store_true",
        default=False,
        help="Enable animated lower-third Call-to-Action overlay",
    )
    p_auto.add_argument(
        "--cta-text",
        default="Subscribe to this channel for more",
        help="Call-to-Action display text",
    )
    p_auto.add_argument(
        "--cta-timing",
        choices=["end", "intro", "persistent"],
        default="end",
        help="Call-to-Action display timing window",
    )
    p_auto.add_argument(
        "--cta-style",
        choices=["modern_pill", "neon_banner", "minimal"],
        default="modern_pill",
        help="Call-to-Action visual style preset",
    )
    p_auto.add_argument(
        "--cta-margin-bottom",
        type=int,
        default=440,
        help="Safe-zone bottom margin in px for CTA overlay placement (default: 440)",
    )
    p_auto.add_argument(
        "--enable-outro-card",
        action="store_true",
        default=False,
        help="Enable dedicated animated outro frame with subscribe sequence and bell chime sound",
    )
    p_auto.add_argument(
        "--outro-duration",
        type=float,
        default=2.5,
        help="Duration of the dedicated outro card in seconds (default: 2.5)",
    )
    p_auto.add_argument(
        "--outro-channel-name",
        default=None,
        help="Channel or brand name to display on the outro card",
    )
    p_auto.add_argument(
        "--enable-polish",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable broadcast hook pacing and anti-pop audio transitions (default true)",
    )
    p_auto.set_defaults(func=cmd_autoprobe)

    # Run command
    p_run = subparsers.add_parser("run", help="Run end-to-end clipping pipeline on authorized asset")
    p_run.add_argument("--video-id", required=True, help="Video ID to process")
    p_run.add_argument("--min-duration", type=float, default=15.0, help="Minimum highlight clip duration in seconds (default: 15.0)")
    p_run.add_argument("--max-duration", type=float, default=60.0, help="Maximum highlight clip duration in seconds (default: 60.0)")
    p_run.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=True, help="Simulate autopost handoff (default true)")
    p_run.add_argument("--layout", default="blur_background", choices=["blur_background", "crop_center", "split_screen", "active_speaker"], help="Visual layout profile")
    p_run.add_argument("--subtitle-preset", default="hormozi", choices=["hormozi", "beast_bounce", "neon_cyber", "karaoke_gold", "bold_social", "karaoke", "clean_editorial", "classic"], help="Subtitle animation and aesthetic styling preset")
    p_run.add_argument("--threshold", type=float, default=65.0, help="Score threshold for auto-approval")
    p_run.add_argument("--gpu", action="store_true", help="Enable NVIDIA NVENC GPU hardware acceleration")
    p_run.add_argument("--vcodec", default="libx264", choices=["libx264", "h264_nvenc", "hevc_nvenc"], help="Video encoder codec")
    p_run.add_argument("--output-dir", default="data/rendered_clips", help="Directory for rendered clips")
    p_run.add_argument("--autopost-mode", default="watched_folder", choices=["watched_folder", "webhook", "omnipost"], help="Autopost handoff distribution mode (default: watched_folder)")
    p_run.add_argument("--omnipost-url", default=None, help="Base URL for OmniPost social publishing engine (default: http://localhost:3300)")
    p_run.add_argument("--omnipost-key", default=None, help="API Secret Key for OmniPost authentication")
    p_run.add_argument("--omnipost-platforms", default="youtube,instagram", help="Target social platforms (e.g. youtube,instagram,facebook,linkedin)")
    p_run.add_argument(
        "--enable-deadair-pruning",
        action="store_true",
        default=False,
        help="Enable DeadAirPruner micro-cuts during rendering (removes pauses >0.5s and filler words)",
    )
    p_run.add_argument(
        "--enable-broll",
        action="store_true",
        default=False,
        help="Enable BRollOverlayEngine stock video overlays during rendering",
    )
    p_run.add_argument(
        "--broll-assets-dir",
        default=None,
        help="Directory containing stock B-roll video assets (default: assets/broll)",
    )
    p_run.add_argument(
        "--enable-cta",
        action="store_true",
        default=False,
        help="Enable animated lower-third Call-to-Action overlay",
    )
    p_run.add_argument(
        "--cta-text",
        default="Subscribe to this channel for more",
        help="Call-to-Action display text",
    )
    p_run.add_argument(
        "--cta-timing",
        choices=["end", "intro", "persistent"],
        default="end",
        help="Call-to-Action display timing window",
    )
    p_run.add_argument(
        "--cta-style",
        choices=["modern_pill", "neon_banner", "minimal"],
        default="modern_pill",
        help="Call-to-Action visual style preset",
    )
    p_run.add_argument(
        "--cta-margin-bottom",
        type=int,
        default=440,
        help="Safe-zone bottom margin in px for CTA overlay placement (default: 440)",
    )
    p_run.add_argument(
        "--enable-outro-card",
        action="store_true",
        default=False,
        help="Enable dedicated animated outro frame with subscribe sequence and bell chime sound",
    )
    p_run.add_argument(
        "--outro-duration",
        type=float,
        default=2.5,
        help="Duration of the dedicated outro card in seconds (default: 2.5)",
    )
    p_run.add_argument(
        "--outro-channel-name",
        default=None,
        help="Channel or brand name to display on the outro card",
    )
    p_run.add_argument(
        "--enable-polish",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable broadcast hook pacing and anti-pop audio transitions (default true)",
    )
    p_run.set_defaults(func=cmd_run)

    # TTS command
    p_tts = subparsers.add_parser("tts", help="Synthesize AI voiceover speech from text")
    p_tts.add_argument("--text", required=True, help="Text to speak")
    p_tts.add_argument("--voice", default="en-US-ChristopherNeural", help="Voice identifier (e.g. christopher, jenny, guy, aria)")
    p_tts.add_argument("--output", default=None, help="Output audio file path (.mp3 or .wav)")
    p_tts.set_defaults(func=cmd_tts)

    # Jobs command
    p_jobs = subparsers.add_parser("jobs", help="List and inspect pipeline jobs")
    p_jobs.add_argument("--status", choices=["PENDING", "IN_PROGRESS", "SUCCEEDED", "FAILED", "RETRY_PENDING"], help="Filter by job status")
    p_jobs.add_argument("--db", default="data/jobs.db", help="Path to SQLite jobs database")
    p_jobs.set_defaults(func=cmd_jobs)

    # Preview command
    p_prev = subparsers.add_parser("preview", help="Preview highlight candidates and scorecards without rendering")
    p_prev.add_argument("--video-id", required=True, help="Video ID to inspect")
    p_prev.add_argument("--min-duration", type=float, default=15.0, help="Minimum highlight clip duration in seconds (default: 15.0)")
    p_prev.add_argument("--max-duration", type=float, default=60.0, help="Maximum highlight clip duration in seconds (default: 60.0)")
    p_prev.set_defaults(func=cmd_preview)

    # Discovery command
    p_disc = subparsers.add_parser("discovery", help="Simulate or query channel discovery and observed view velocity")
    p_disc.add_argument("--channel-id", default="UC_sample_channel", help="Channel ID")
    p_disc.add_argument("--channel-name", default="Tech Innovators", help="Channel Name")
    p_disc.add_argument("--avg-views", type=float, default=50000.0, help="Channel average views baseline")
    p_disc.add_argument("--sample-video-id", default="vid_sample_01", help="Sample Video ID")
    p_disc.add_argument("--sample-title", default="Deep Learning Systems in 2026", help="Sample Video Title")
    p_disc.add_argument("--views", type=int, default=125000, help="Public view count")
    p_disc.add_argument("--duration", type=float, default=720.0, help="Duration in seconds")
    p_disc.set_defaults(func=cmd_discovery)

    # Heatmap command
    p_hm = subparsers.add_parser("heatmap", help="Analyze YouTube 'Most Replayed' retention curve & peak moments")
    p_hm.add_argument("--video-id", required=True, help="YouTube Video ID")
    p_hm.add_argument("--visual", action="store_true", help="Render ASCII retention waveform in terminal")
    p_hm.add_argument("--cache-dir", default="data/heatmaps", help="Heatmap cache directory")
    p_hm.set_defaults(func=cmd_heatmap)

    # Trends command
    p_tr = subparsers.add_parser("trends", help="Analyze real-time video virality or official YouTube Trending Charts")
    p_tr.add_argument("--video-id", default=None, help="Video ID to evaluate")
    p_tr.add_argument("--chart", choices=["popular"], default=None, help="Fetch official YouTube Trending chart")
    p_tr.add_argument("--region", default="US", help="ISO 3166-1 alpha-2 region code (e.g. US, GB, IN)")
    p_tr.add_argument("--category", default=None, help="YouTube Video Category ID (e.g. 24 for Entertainment, 20 for Gaming)")
    p_tr.add_argument("--limit", type=int, default=10, help="Maximum number of trending videos to display")
    p_tr.set_defaults(func=cmd_trends)

    # MCP Server command
    p_mcp = subparsers.add_parser(
        "mcp-server",
        description="Launch Model Context Protocol (MCP) JSON-RPC 2.0 stdio server",
        help="Launch Model Context Protocol (MCP) JSON-RPC 2.0 stdio server",
    )
    p_mcp.add_argument("--db", default="data/jobs.db", help="Path to SQLite jobs database")
    p_mcp.add_argument("--assets-dir", default="data/assets", help="Source assets directory")
    p_mcp.add_argument("--transcripts-dir", default="data/transcripts", help="Transcripts directory")
    p_mcp.add_argument("--output-dir", default="data/rendered_clips", help="Rendered output directory")
    p_mcp.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Stderr logging level")
    p_mcp.set_defaults(func=cmd_mcp_server)

    # Alias: mcp serve
    p_mcp_sub = subparsers.add_parser("mcp", help="Model Context Protocol management")
    mcp_subs = p_mcp_sub.add_subparsers(dest="mcp_subcmd", required=True)
    p_mcp_serve = mcp_subs.add_parser("serve", help="Start stdio MCP server")
    p_mcp_serve.add_argument("--db", default="data/jobs.db", help="Path to SQLite jobs database")
    p_mcp_serve.add_argument("--assets-dir", default="data/assets", help="Source assets directory")
    p_mcp_serve.add_argument("--transcripts-dir", default="data/transcripts", help="Transcripts directory")
    p_mcp_serve.add_argument("--output-dir", default="data/rendered_clips", help="Rendered output directory")
    p_mcp_serve.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Stderr logging level")
    p_mcp_serve.set_defaults(func=cmd_mcp_server)

    # Podcast command
    p_pod = subparsers.add_parser(
        "podcast",
        description="Render broadcast-grade vertical Shorts from podcast footage",
        help="Render broadcast-grade vertical Shorts from podcast footage",
    )
    p_pod.add_argument("--source", "-s", required=True, help="Path to input podcast video")
    p_pod.add_argument("--out", "-o", required=True, help="Path to save output vertical MP4")
    p_pod.add_argument("--start", type=float, default=0.0, help="Start offset in seconds (default: 0.0)")
    p_pod.add_argument("--duration", "-d", type=float, default=30.0, help="Duration in seconds (default: 30.0)")
    p_pod.add_argument("--mode", "-m", choices=["hybrid", "stacked_always"], default="hybrid", help="Layout mode: hybrid or stacked_always")
    p_pod.add_argument("--host-side", choices=["left", "right"], default="left", help="Host seat position in wide shot (left or right)")
    p_pod.add_argument("--preview", action="store_true", help="Fast preview mode (540x960 ultrafast)")
    p_pod.add_argument("--no-subtitles", action="store_true", help="Disable subtitle burning")
    p_pod.add_argument("--divider-thickness", type=int, default=4, help="Divider bar thickness in pixels (default: 4)")
    p_pod.add_argument("--divider-color", default="0x202020", help="Divider bar color in hex (default: 0x202020)")
    p_pod.add_argument("--enable-cta", action="store_true", help="Enable animated Call-to-Action overlay")
    p_pod.add_argument("--cta-text", default="Subscribe to this channel for more", help="Custom Call-to-Action text")
    p_pod.add_argument("--cta-timing", choices=["end", "intro", "persistent"], default="end", help="CTA appearance timing (default: end)")
    p_pod.add_argument("--cta-style", choices=["modern_pill", "neon_banner", "minimal"], default="modern_pill", help="CTA visual style preset")
    p_pod.set_defaults(func=cmd_podcast)

    return parser
