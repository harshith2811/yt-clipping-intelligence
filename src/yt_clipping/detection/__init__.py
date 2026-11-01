"""Candidate moment segmentation and deduplication."""
from .segmenter import ContextAwareSegmenter
from .dedupe import suppress_overlapping_candidates
from .audio_energy import AudioEnergyAnalyzer, MotionEnergyAnalyzer, AdaptiveCadenceScorer

__all__ = [
    "ContextAwareSegmenter",
    "suppress_overlapping_candidates",
    "AudioEnergyAnalyzer",
    "MotionEnergyAnalyzer",
    "AdaptiveCadenceScorer",
]
