"""
FFmpeg Filtergraph Builder for Podcast Layouts.
Generates production-grade FFmpeg filter graphs for:
- Stacked Split-Screen (Host on top 9:8, Guest on bottom 9:8).
- Single Close-up (Centered 9:16 active speaker).
- Dividing border line and libass subtitle integration.
"""

from typing import Optional, Dict, Any
import os
import re
from .config import PodcastLayoutConfig


def escape_libass_path(path: str) -> str:
    """Escapes subtitle file paths for FFmpeg libass filter on Windows and POSIX."""
    norm = path.replace("\\", "/")
    norm = norm.replace(":", "\\:")
    norm = norm.replace("'", "'\\''")
    norm = norm.replace("[", "\\[").replace("]", "\\]")
    return norm


def build_podcast_split_filtergraph(
    src_w: int,
    src_h: int,
    config: PodcastLayoutConfig,
    host_cx: Optional[float] = None,
    guest_cx: Optional[float] = None,
    subtitle_ass_path: Optional[str] = None,
    select_filter_expr: Optional[str] = None,
) -> str:
    """
    Constructs an FFmpeg filtergraph for a 9:16 vertical stacked layout.
    - Top half: Host crop (aspect ratio 9:8).
    - Bottom half: Guest crop (aspect ratio 9:8).
    - Stacks both vertically with vstack.
    - Burns word-synced ASS subtitles directly onto the composite video stream.
    - Optionally applies micro-jump-cut select filter expression.
    """
    w, h = config.width, config.height
    half_h = (h // 2) if (h // 2) % 2 == 0 else (h // 2) - 1

    # In source frame, a 9:8 crop from height src_h:
    crop_w = int(src_h * 9.0 / 8.0)
    if crop_w % 2 != 0:
        crop_w -= 1
    crop_w = min(crop_w, src_w)

    # Calculate Host X coordinate (default left side)
    default_host_cx = src_w * 0.28 if config.host_side == "left" else src_w * 0.72
    h_cx = host_cx if host_cx is not None else default_host_cx
    top_x = int(max(0, min(src_w - crop_w, h_cx - crop_w // 2)))
    if top_x % 2 != 0:
        top_x -= 1

    # Calculate Guest X coordinate (default right side)
    default_guest_cx = src_w * 0.72 if config.host_side == "left" else src_w * 0.28
    g_cx = guest_cx if guest_cx is not None else default_guest_cx
    bot_x = int(max(0, min(src_w - crop_w, g_cx - crop_w // 2)))
    if bot_x % 2 != 0:
        bot_x -= 1

    escaped_sub = ""
    should_burn = config.burn_subtitles or getattr(config, "enable_cta", False)
    if subtitle_ass_path and should_burn and os.path.exists(subtitle_ass_path):
        sub_esc = escape_libass_path(subtitle_ass_path)
        escaped_sub = f",subtitles='{sub_esc}'"

    # Sleek dividing line
    div_filter = ""
    if config.divider_thickness > 0:
        # Draw a horizontal line right at Y=half_h across width w
        t = config.divider_thickness
        y0 = half_h - t // 2
        div_filter = f",drawbox=x=0:y={y0}:w={w}:h={t}:color={config.divider_color}:t=fill"

    select_filter = ""
    if select_filter_expr:
        select_filter = f",select='{select_filter_expr}',setpts=N/FRAME_RATE/TB"

    filtergraph = (
        f"[0:v]split=2[in_top][in_bot];"
        f"[in_top]crop={crop_w}:{src_h}:{top_x}:0,scale={w}:{half_h}[top];"
        f"[in_bot]crop={crop_w}:{src_h}:{bot_x}:0,scale={w}:{half_h}[bot];"
        f"[top][bot]vstack=inputs=2[stacked];"
        f"[stacked]setsar=1{div_filter}{escaped_sub}{select_filter}[v]"
    )
    return filtergraph


def build_podcast_closeup_filtergraph(
    src_w: int,
    src_h: int,
    config: PodcastLayoutConfig,
    speaker_cx: Optional[float] = None,
    subtitle_ass_path: Optional[str] = None,
) -> str:
    """
    Constructs an FFmpeg filtergraph for a 9:16 vertical close-up shot.
    Centers the frame on the active speaker.
    """
    w, h = config.width, config.height

    # In source frame, a 9:16 crop from height src_h:
    crop_w = int(src_h * 9.0 / 16.0)
    if crop_w % 2 != 0:
        crop_w -= 1
    crop_w = min(crop_w, src_w)

    cx = speaker_cx if speaker_cx is not None else (src_w / 2.0)
    crop_x = int(max(0, min(src_w - crop_w, cx - crop_w // 2)))
    if crop_x % 2 != 0:
        crop_x -= 1

    escaped_sub = ""
    should_burn = config.burn_subtitles or getattr(config, "enable_cta", False)
    if subtitle_ass_path and should_burn and os.path.exists(subtitle_ass_path):
        sub_esc = escape_libass_path(subtitle_ass_path)
        escaped_sub = f",subtitles='{sub_esc}'"

    filtergraph = f"crop={crop_w}:{src_h}:{crop_x}:0,scale={w}:{h},setsar=1{escaped_sub}"
    return filtergraph
