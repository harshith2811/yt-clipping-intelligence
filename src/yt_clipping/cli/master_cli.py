"""
Master CLI Entrypoint & Router for YouTube Clipping Intelligence Platform.
Provides centralized routing, argument dispatching, and backward-compatible re-exports.
"""

import sys
from dotenv import load_dotenv

load_dotenv()

# Modular parser
from .parser import build_parser

# Modular command implementations (re-exported for 100% backward compatibility)
from .commands import (
    build_pipeline,
    cmd_run,
    cmd_discovery,
    cmd_heatmap,
    cmd_trends,
    cmd_channels,
    cmd_daemon,
    cmd_jobs_list,
    cmd_jobs_inspect,
    cmd_jobs_retry,
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

__all__ = [
    "main",
    "build_parser",
    "build_pipeline",
    "cmd_run",
    "cmd_discovery",
    "cmd_heatmap",
    "cmd_trends",
    "cmd_channels",
    "cmd_daemon",
    "cmd_jobs_list",
    "cmd_jobs_inspect",
    "cmd_jobs_retry",
    "cmd_jobs",
    "cmd_queue",
    "cmd_dlq",
    "cmd_doctor",
    "cmd_autoprobe",
    "cmd_config_validate",
    "cmd_rights_register",
    "cmd_rights_check",
    "cmd_ingest",
    "cmd_quota",
    "cmd_tts",
    "cmd_preview",
    "cmd_cleanup",
    "cmd_podcast",
    "cmd_mcp_server",
]


def main() -> None:
    """Main CLI execution router."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = build_parser()
    parsed = parser.parse_args()
    parsed.func(parsed)


if __name__ == "__main__":
    main()
