"""
YouTube Clipping Intelligence Platform - Master Repository.
Rights-aware video discovery, highlight intelligence, verified vertical clipping, and autopost handoff.
"""

from .config import AppConfig
from .cli.master_cli import main, build_parser

__version__ = "1.0.0"

__all__ = ["__version__", "AppConfig", "main", "build_parser"]
