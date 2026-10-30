"""
Candidate Interval Deduplication and Overlap Suppression.
Calculates temporal Intersection-over-Union (IoU) and containment ratios
to suppress redundant clips covering the same underlying moment.
"""

from typing import List
from ..contracts.models import HighlightCandidate


def calculate_temporal_iou(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    """Calculates temporal Intersection-over-Union between two time intervals."""
    intersection = max(0.0, min(end_a, end_b) - max(start_a, start_b))
    union = max(end_a, end_b) - min(start_a, start_b)
    if union <= 0.0:
        return 0.0
    return intersection / union


def calculate_containment(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    """Calculates what fraction of the shorter interval is contained in the longer interval."""
    intersection = max(0.0, min(end_a, end_b) - max(start_a, start_b))
    dur_a = max(end_a - start_a, 0.001)
    dur_b = max(end_b - start_b, 0.001)
    shorter = min(dur_a, dur_b)
    return intersection / shorter


def suppress_overlapping_candidates(
    candidates: List[HighlightCandidate],
    iou_threshold: float = 0.40,
    containment_threshold: float = 0.70,
) -> List[HighlightCandidate]:
    """
    Suppresses redundant candidate intervals.
    Sorts candidates by score descending, keeps the highest-scoring candidate,
    and discards any lower-scoring candidate that heavily overlaps with an accepted one.
    """
    if not candidates:
        return []

    # Sort descending by score
    sorted_candidates = sorted(candidates, key=lambda c: c.score, reverse=True)
    accepted: List[HighlightCandidate] = []

    for cand in sorted_candidates:
        is_redundant = False
        for acc in accepted:
            iou = calculate_temporal_iou(
                cand.start_seconds, cand.end_seconds, acc.start_seconds, acc.end_seconds
            )
            containment = calculate_containment(
                cand.start_seconds, cand.end_seconds, acc.start_seconds, acc.end_seconds
            )
            if iou > iou_threshold or containment > containment_threshold:
                is_redundant = True
                break

        if not is_redundant:
            accepted.append(cand)

    # Sort final accepted list chronologically by start_seconds
    return sorted(accepted, key=lambda c: c.start_seconds)
