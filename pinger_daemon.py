"""
Root entrypoint for PingerDaemon.
Allows direct execution or import via `import pinger_daemon`.
"""

import sys
import argparse
from src.yt_clipping.discovery.pinger_daemon import PingerDaemon

__all__ = ["PingerDaemon"]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autonomous YouTube Upload Pinger & Virality Scraper Daemon")
    parser.add_argument("--interval", type=int, default=300, help="Polling interval in seconds (default: 300)")
    parser.add_argument("--cycles", type=int, default=None, help="Maximum poll cycles before stopping (optional)")
    parser.add_argument("--websub", action="store_true", help="Enable WebSub push notification HTTP server")
    parser.add_argument("--websub-port", type=int, default=8088, help="Port for WebSub push server (default: 8088)")
    args = parser.parse_args()

    daemon = PingerDaemon(
        poll_interval_seconds=args.interval,
        enable_websub=args.websub,
        websub_port=args.websub_port,
    )
    daemon.run_daemon(max_cycles=args.cycles)
