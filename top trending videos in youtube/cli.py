"""
Command-Line Interface for Top Trending YouTube Videos from 10M+ Channels.
Provides commands to list, refresh, and stream quality videos directly to the clipper.
"""

import argparse
import sys
import os
import json

from .channels import VERIFIED_10M_CHANNELS
from .fetcher import TopTrending10MFetcher
from .streamer import ClipperStreamer

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def format_views(v: int) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    elif v >= 1_000:
        return f"{v / 1_000:.1f}K"
    return str(v)


def main():
    parser = argparse.ArgumentParser(
        prog="python -m top_trending_videos_in_youtube",
        description="Top Trending Videos from 10M+ Subscriber Channels for Autonomous YouTube Clipping.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # Command: list
    list_p = subparsers.add_parser("list", help="List discovered top trending videos from 10M+ channels")
    list_p.add_argument("--limit", type=int, default=10, help="Maximum number of videos to display")
    list_p.add_argument("--refresh", action="store_true", help="Fetch fresh data from YouTube API before listing")

    # Command: fetch
    fetch_p = subparsers.add_parser("fetch", help="Refresh and export trending 10M+ video links to JSON and TXT")
    fetch_p.add_argument("--limit", type=int, default=20, help="Number of videos to export")

    # Command: stream
    stream_p = subparsers.add_parser("stream", help="Stream a top trending video directly into the YouTube Clipper")
    stream_p.add_argument("--url", type=str, default=None, help="Specific video URL or ID to stream (defaults to #1 trending)")
    stream_p.add_argument("--clips", type=int, default=3, help="Number of vertical shorts to generate")
    stream_p.add_argument("--layout", type=str, default="active_speaker", help="Camera framing (active_speaker, split_screen, center_crop)")
    stream_p.add_argument("--preset", type=str, default="hormozi", help="Subtitle preset style")
    stream_p.add_argument("--no-gpu", action="store_true", help="Disable GPU NVENC hardware acceleration")

    # Command: channels
    subparsers.add_parser("channels", help="List all verified 10M+ subscriber channels currently monitored")

    args = parser.parse_args()
    if not args.command:
        # Default to listing top videos
        args.command = "list"
        args.limit = 10
        args.refresh = False

    fetcher = TopTrending10MFetcher()
    streamer = ClipperStreamer()

    if args.command == "channels":
        print("\n=== Verified YouTube Channels (> 10,000,000 Subscribers) ===")
        print(f"{'Channel Name':<30} | {'Handle':<18} | {'Subscribers':<12} | {'Category':<24}")
        print("-" * 90)
        sorted_channels = sorted(VERIFIED_10M_CHANNELS, key=lambda c: c.subscriber_count, reverse=True)
        for ch in sorted_channels:
            print(f"{ch.title:<30} | {ch.handle:<18} | {ch.subscriber_count_formatted:<12} | {ch.category:<24}")
        print(f"\nTotal Monitored: {len(sorted_channels)} premier channels.")

    elif args.command in ("list", "fetch"):
        print(f"[*] Discovering top trending videos from 10M+ subscriber channels...")
        videos = streamer.export_fresh_links(limit=args.limit)

        print(f"\n=== Top Trending Videos from 10M+ Channels ({len(videos)} Quality Candidates) ===\n")
        print(f"{'#':<3} | {'Score':<5} | {'Creator (Subs)':<28} | {'Duration':<8} | {'Views':<8} | {'Title'}")
        print("-" * 110)
        for idx, v in enumerate(videos, 1):
            creator_str = f"{v.channel_name[:18]} ({v.channel_subscribers_formatted})"
            title_str = v.title[:45] + ("..." if len(v.title) > 45 else "")
            print(f"{idx:<3} | {v.virality_score:<5.1f} | {creator_str:<28} | {v.duration_formatted:<8} | {format_views(v.view_count):<8} | {title_str}")
            print(f"    -> Link: {v.url}")
            print(f"    -> Suitability: {v.clipping_suitability}")
            print()

        print(f"[OK] Exported clean links to:")
        print(f"     JSON: top_trending_videos_in_youtube/video_links.json")
        print(f"     TXT:  top_trending_videos_in_youtube/video_links.txt")

    elif args.command == "stream":
        target_url = args.url
        if not target_url:
            print("[*] No URL provided. Auto-selecting #1 highest-ranked video from 10M+ channels...")
            res = streamer.stream_top_video(
                max_clips=args.clips,
                layout=args.layout,
                subtitle_preset=args.preset,
                gpu=not args.no_gpu,
            )
        else:
            print(f"[*] Streaming custom video to clipper: {target_url}")
            res = streamer.stream_to_studio(
                video_url_or_id=target_url,
                max_clips=args.clips,
                layout=args.layout,
                subtitle_preset=args.preset,
                gpu=not args.no_gpu,
            )

        print(f"\n[STREAM RESULT] {res.get('message', 'Completed')}")
        if res.get("job_id"):
            print(f"  Job ID: {res['job_id']}")
            print(f"  Status: {res.get('status')}")
            print(f"  Web Studio: {res.get('studio_url', 'http://localhost:8000')}")


if __name__ == "__main__":
    main()
