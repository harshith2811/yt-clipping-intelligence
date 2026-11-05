"""
Podcast multi-speaker short maker and Model Context Protocol (MCP) server commands for CLI.
"""

import argparse


def cmd_mcp_server(args: argparse.Namespace) -> None:
    from ...mcp.server import MCPServer
    server = MCPServer(
        db_path=getattr(args, "db", "data/jobs.db"),
        assets_dir=getattr(args, "assets_dir", "data/assets"),
        transcripts_dir=getattr(args, "transcripts_dir", "data/transcripts"),
        output_dir=getattr(args, "output_dir", "data/rendered_clips"),
        log_level=getattr(args, "log_level", "INFO"),
    )
    server.run_stdio()


def cmd_podcast(args: argparse.Namespace) -> None:
    from ...podcast.config import PodcastLayoutConfig
    from ...podcast.pipeline import PodcastShortMaker

    cfg = PodcastLayoutConfig(
        split_mode=getattr(args, "mode", "hybrid"),
        host_side=getattr(args, "host_side", "left"),
        preview=getattr(args, "preview", False),
        burn_subtitles=not getattr(args, "no_subtitles", False),
        divider_thickness=getattr(args, "divider_thickness", 4),
        divider_color=getattr(args, "divider_color", "0x202020"),
        enable_cta=getattr(args, "enable_cta", False),
        cta_text=getattr(args, "cta_text", "Subscribe to this channel for more"),
        cta_timing=getattr(args, "cta_timing", "end"),
        cta_style=getattr(args, "cta_style", "modern_pill"),
    )
    maker = PodcastShortMaker(config=cfg)
    print(f"[*] Processing podcast video: {args.source}")
    print(f"[*] Window: {args.start:.1f}s to {args.start + args.duration:.1f}s (duration: {args.duration:.1f}s)")
    print(f"[*] Layout mode: {cfg.split_mode} | Resolution: {cfg.width}x{cfg.height}")

    res = maker.create_short(
        video_path=args.source,
        start_sec=args.start,
        duration_sec=args.duration,
        output_path=args.out,
    )
    print("\n[SUCCESS] Successfully rendered Podcast Short!")
    print(f"Output file: {res['output_path']}")
    print(f"Shots detected: {res['shots_detected']} ({', '.join(res['shot_breakdown'])})")
    print(f"File size: {res['file_size_bytes'] / (1024*1024):.2f} MB")
