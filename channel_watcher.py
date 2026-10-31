"""
Root entrypoint for ChannelWatcher CLI tool.
Allows direct execution via `python channel_watcher.py <subcommand>`.
"""

import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.yt_clipping.discovery.channel_watcher import main

if __name__ == "__main__":
    main()
