"""
Command-line interface for the Podcast Short Maker.
Provides one-command rendering of podcast shorts:
python -m yt_clipping.podcast --source video.mp4 --out short.mp4 --mode hybrid --preview
"""

import argparse
import sys
import os

from .config import PodcastLayoutConfig
from .pipeline import PodcastShortMaker


def main():
    parser = argparse.ArgumentParser(
        description="Render broadcast-grade vertical Shorts from podcast footage."
    )
    parser.add_argument("--source", "-s", required=True, help="Path to input podcast video")
    parser.add_argument("--out", "-o", required=True, help="Path to save output vertical MP4")
    parser.add_argument("--start", type=float, default=0.0, help="Start offset in seconds (default: 0.0)")
    parser.add_argument("--duration", "-d", type=float, default=30.0, help="Duration in seconds (default: 30.0)")
    parser.add_argument("--mode", "-m", choices=["hybrid", "stacked_always"], default="hybrid",
                        help="Layout mode: 'hybrid' (dynamic cuts) or 'stacked_always' (pure split)")
    parser.add_argument("--host-side", choices=["left", "right"], default="left",
                        help="Side where host sits in wide shot (default: left)")
    parser.add_argument("--preview", action="store_true",
                        help="Fast preview mode (renders 540x960 ultrafast)")
    parser.add_argument("--no-subtitles", action="store_true",
                        help="Disable subtitle burning")

    args = parser.parse_args()

    config = PodcastLayoutConfig(
        split_mode=args.mode,
        host_side=args.host_side,
        preview=args.preview,
        burn_subtitles=not args.no_subtitles,
    )

    maker = PodcastShortMaker(config=config)
    print(f"🎬 Processing podcast video: {args.source}")
    print(f"⏱️ Window: {args.start:.1f}s to {args.start + args.duration:.1f}s (duration: {args.duration:.1f}s)")
    print(f"📐 Layout mode: {config.split_mode} | Resolution: {config.width}x{config.height}")

    res = maker.create_short(
        video_path=args.source,
        start_sec=args.start,
        duration_sec=args.duration,
        output_path=args.out
    )

    print("\n✅ Successfully rendered Podcast Short!")
    print(f"📁 Output file: {res['output_path']}")
    print(f"📊 Shots detected: {res['shots_detected']} ({', '.join(res['shot_breakdown'])})")
    print(f"💾 File size: {res['file_size_bytes'] / (1024*1024):.2f} MB")


if __name__ == "__main__":
    main()
