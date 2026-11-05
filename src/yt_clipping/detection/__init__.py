"""Candidate moment segmentation and deduplication."""
from .segmenter import ContextAwareSegmenter
from .dedupe import (
    suppress_overlapping_candidates,
    calculate_temporal_iou,
    calculate_containment,
)
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
from .solid_shorts import (
    SolidShortsDecider,
    SolidShortsConfig,
    SolidShortsDecision,
)
from .arc_detector import ArcDetector
from .sentence_classifier import (
    SentenceClassifier,
    ClassifiedSentence,
    HOOK,
    CONTEXT,
    ESCALATION,
    REVELATION,
    PAYOFF,
    FILLER,
    SPONSOR,
)

__all__ = [
    "ContextAwareSegmenter",
    "suppress_overlapping_candidates",
    "calculate_temporal_iou",
    "calculate_containment",
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
    "SolidShortsDecider",
    "SolidShortsConfig",
    "SolidShortsDecision",
    "ArcDetector",
    "SentenceClassifier",
    "ClassifiedSentence",
    "HOOK",
    "CONTEXT",
    "ESCALATION",
    "REVELATION",
    "PAYOFF",
    "FILLER",
    "SPONSOR",
]
