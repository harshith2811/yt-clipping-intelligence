"""Candidate moment segmentation and deduplication."""
from .segmenter import ContextAwareSegmenter
from .dedupe import suppress_overlapping_candidates
from .audio_energy import AudioEnergyAnalyzer, MotionEnergyAnalyzer, AdaptiveCadenceScorer
from .deadair import (
    DeadAirPruner,
    DeadAirGap,
    FillerOccurrence,
    SentenceRestart,
    PruneResult,
)
from .short_viability import (
    ShortViabilityValidator,
    ViabilityCheckResult,
)

__all__ = [
    "ContextAwareSegmenter",
    "suppress_overlapping_candidates",
    "AudioEnergyAnalyzer",
    "MotionEnergyAnalyzer",
    "AdaptiveCadenceScorer",
    "DeadAirPruner",
    "DeadAirGap",
    "FillerOccurrence",
    "SentenceRestart",
    "PruneResult",
    "ShortViabilityValidator",
    "ViabilityCheckResult",
]
