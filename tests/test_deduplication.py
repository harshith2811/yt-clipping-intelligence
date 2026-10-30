"""
Tests for temporal IoU deduplication and candidate overlap suppression.
"""

import pytest
from src.yt_clipping.contracts.models import HighlightCandidate, ScoreBreakdown
from src.yt_clipping.detection.dedupe import (
    calculate_temporal_iou,
    calculate_containment,
    suppress_overlapping_candidates,
)


def test_temporal_iou_calculations():
    # Disjoint intervals
    assert calculate_temporal_iou(0.0, 10.0, 20.0, 30.0) == 0.0

    # Identical intervals
    assert calculate_temporal_iou(10.0, 30.0, 10.0, 30.0) == 1.0

    # Partial overlap: [10, 30] and [20, 40]
    # Intersection = 30 - 20 = 10
    # Union = 40 - 10 = 30
    # IoU = 10 / 30 = 0.3333
    iou = calculate_temporal_iou(10.0, 30.0, 20.0, 40.0)
    assert abs(iou - (10.0 / 30.0)) < 0.001


def test_containment_calculations():
    # Complete containment: [15, 25] inside [10, 30]
    # Shorter = 10, intersection = 10 -> containment = 1.0
    c = calculate_containment(15.0, 25.0, 10.0, 30.0)
    assert c == 1.0


def test_suppress_overlapping_candidates():
    breakdown = ScoreBreakdown()

    # Candidate A: 10s to 40s, Score 85.0 (Higher)
    cand_a = HighlightCandidate(
        candidate_id="cand-A",
        video_id="v1",
        start_seconds=10.0,
        end_seconds=40.0,
        duration_seconds=30.0,
        score=85.0,
        breakdown=breakdown,
        hook_title="Candidate A",
    )

    # Candidate B: 12s to 42s, Score 65.0 (Heavy overlap with A, lower score)
    cand_b = HighlightCandidate(
        candidate_id="cand-B",
        video_id="v1",
        start_seconds=12.0,
        end_seconds=42.0,
        duration_seconds=30.0,
        score=65.0,
        breakdown=breakdown,
        hook_title="Candidate B",
    )

    # Candidate C: 60s to 90s, Score 75.0 (Disjoint interval)
    cand_c = HighlightCandidate(
        candidate_id="cand-C",
        video_id="v1",
        start_seconds=60.0,
        end_seconds=90.0,
        duration_seconds=30.0,
        score=75.0,
        breakdown=breakdown,
        hook_title="Candidate C",
    )

    suppressed = suppress_overlapping_candidates([cand_a, cand_b, cand_c], iou_threshold=0.40)

    # cand_b should be suppressed because it heavily overlaps cand_a and has lower score
    ids = [c.candidate_id for c in suppressed]
    assert "cand-A" in ids
    assert "cand-C" in ids
    assert "cand-B" not in ids
    assert len(suppressed) == 2


def test_segmenter_handles_oversized_unpunctuated_segment():
    from src.yt_clipping.detection.segmenter import ContextAwareSegmenter
    from src.yt_clipping.contracts.models import Transcript, TranscriptSegment, WordTimestamp

    # Continuous monologue: 75 seconds without sentence break
    words = [
        WordTimestamp(word=f"word{i}", start=round(i * 0.75, 2), end=round((i + 1) * 0.75, 2))
        for i in range(100)
    ]
    seg = TranscriptSegment(
        segment_id=1,
        start=0.0,
        end=75.0,
        text=" ".join(w.word for w in words),
        words=words,
    )
    transcript = Transcript(
        video_id="v_long_segment",
        language="en",
        duration_seconds=75.0,
        text=seg.text,
        segments=[seg],
    )

    segmenter = ContextAwareSegmenter(default_min_duration=20.0, default_max_duration=60.0, target_duration=35.0)
    candidates = segmenter.detect_candidates(transcript)

    # Must produce valid candidates instead of failing or returning empty list
    assert len(candidates) > 0
    for c in candidates:
        assert 20.0 <= c.duration_seconds <= 60.0

