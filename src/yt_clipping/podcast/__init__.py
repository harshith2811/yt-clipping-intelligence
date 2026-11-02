"""
Podcast Short Maker Package.
Dedicated decoupled module for detecting, reframing, and rendering
broadcast-grade 9:16 vertical Shorts from two-speaker podcast interviews.
"""

from .config import PodcastLayoutConfig
from .shot_detector import PodcastShotDetector, PodcastShot, PodcastShotType
from .layout import (
    build_podcast_split_filtergraph,
    build_podcast_closeup_filtergraph,
    escape_libass_path,
)
from .captions import PodcastSubtitleGenerator
from .pipeline import PodcastShortMaker
from .diarization import (
    SpeakerTurn,
    SpeakerDiarizer,
    AcousticEnergyDiarizer,
    PyannoteDiarizerAdapter,
    get_speaker_diarizer,
)

__all__ = [
    "PodcastLayoutConfig",
    "PodcastShotDetector",
    "PodcastShot",
    "PodcastShotType",
    "build_podcast_split_filtergraph",
    "build_podcast_closeup_filtergraph",
    "escape_libass_path",
    "PodcastSubtitleGenerator",
    "PodcastShortMaker",
    "SpeakerTurn",
    "SpeakerDiarizer",
    "AcousticEnergyDiarizer",
    "PyannoteDiarizerAdapter",
    "get_speaker_diarizer",
]
