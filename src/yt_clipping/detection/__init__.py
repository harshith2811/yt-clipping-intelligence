"""Candidate moment segmentation and deduplication."""
from .segmenter import ContextAwareSegmenter
from .dedupe import suppress_overlapping_candidates

__all__ = ["ContextAwareSegmenter", "suppress_overlapping_candidates"]
