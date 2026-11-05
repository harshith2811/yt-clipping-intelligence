"""
Studio command for launching the interactive Web Studio Dashboard and REST API.
"""

import sys
from yt_clipping.web.server import start_server


def cmd_studio(args) -> int:
    """Launch the Web Studio Dashboard and REST API."""
    host = getattr(args, "host", "0.0.0.0")
    port = getattr(args, "port", 8000)
    print(f"[*] Starting YouTube Clipping Intelligence Web Studio on http://{host}:{port}")
    try:
        start_server(host=host, port=port)
        return 0
    except KeyboardInterrupt:
        print("\n[*] Studio server stopped by operator.")
        return 0
    except Exception as e:
        print(f"[!] Studio server failed to start: {e}", file=sys.stderr)
        return 1
