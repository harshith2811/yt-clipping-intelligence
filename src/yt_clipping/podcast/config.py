"""
Configuration and presets for Podcast Short generation.
Provides parameters for layout aspect ratios, stacked split-screen,
divider styling, and subtitle positioning.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class PodcastLayoutConfig:
    """
    Configuration for podcast short reframing and rendering.
    """
    width: int = 1080
    height: int = 1920
    split_mode: str = "hybrid"  # "hybrid" | "stacked_always" | "active_speaker"
    host_side: str = "left"     # "left" (Colin on left) or "right"
    divider_thickness: int = 4
    divider_color: str = "0x202020"
    burn_subtitles: bool = True
    subtitle_preset: str = "podcast"
    font_name: str = "Impact"
    font_size: int = 70
    margin_v: Optional[int] = None  # Defaults to height // 2 (exact center divider)
    preview: bool = False           # If True, scales down to 540x960 for fast iteration
    vcodec: str = "libx264"
    acodec: str = "aac"
    crf: int = 22
    apply_micro_jump_cuts: bool = False
    dead_air_threshold: float = 0.35
    enable_cta: bool = False
    cta_text: str = "Subscribe to this channel for more"
    cta_timing: str = "end"
    cta_style: str = "modern_pill"
    cta_duration: float = 3.5


    def __post_init__(self):
        if self.preview:
            self.width = 540
            self.height = 960
            self.font_size = 38

        # Ensure even dimensions for H.264
        if self.width % 2 != 0:
            self.width -= 1
        if self.height % 2 != 0:
            self.height -= 1

        if self.margin_v is None:
            # Place subtitles right on the dividing line
            self.margin_v = self.height // 2
