"""
Modular subcommand execution modules for YouTube Clipping Intelligence Platform CLI.
"""

from .pipeline import build_pipeline, cmd_run
from .discovery import cmd_discovery, cmd_heatmap, cmd_trends, cmd_channels, cmd_daemon
from .jobs import cmd_jobs_list, cmd_jobs_inspect, cmd_jobs_retry, cmd_jobs, cmd_queue, cmd_dlq
from .diagnostics import cmd_doctor, cmd_autoprobe, cmd_config_validate
from .assets import (
    cmd_rights_register,
    cmd_rights_check,
    cmd_ingest,
    cmd_quota,
    cmd_tts,
    cmd_preview,
    cmd_cleanup,
)
from .podcast import cmd_podcast, cmd_mcp_server
from .studio import cmd_studio

__all__ = [
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
    "cmd_studio",
]
