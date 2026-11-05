"""Media rendering, vertical reframing, and caption generation."""
from .captions import SubtitleGenerator
from .renderer import FFmpegRenderer, RenderingError
from .cta_overlay import CTAOverlayEngine, CTAConfig, CTAStyle, CTATiming, CTATimingWindow
from .outro_card import OutroCardEngine, OutroCardConfig, synthesize_bell_chime
from .face_tracker import FaceFocusedFramer
from .trajectory import (
    TrajectoryConfig,
    KinematicSegment,
    TrajectoryResult,
    ConstrainedTrajectoryOptimizer,
)
from .b_roll import (
    BRollOverlayEngine,
    BRollConfig,
    MonologueInterval,
    BRollOverlayResult,
)
from .subject_segmenter import SubjectSegmenter

__all__ = [
    "SubtitleGenerator",
    "FFmpegRenderer",
    "RenderingError",
    "CTAOverlayEngine",
    "CTAConfig",
    "CTAStyle",
    "CTATiming",
    "CTATimingWindow",
    "OutroCardEngine",
    "OutroCardConfig",
    "synthesize_bell_chime",
    "FaceFocusedFramer",
    "TrajectoryConfig",
    "KinematicSegment",
    "TrajectoryResult",
    "ConstrainedTrajectoryOptimizer",
    "BRollOverlayEngine",
    "BRollConfig",
    "MonologueInterval",
    "BRollOverlayResult",
    "SubjectSegmenter",
]
