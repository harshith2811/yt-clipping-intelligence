"""Command-line operational interface for the YouTube Clipping Platform."""
from . import master_cli
from .master_cli import main, build_parser

__all__ = ["master_cli", "main", "build_parser"]
