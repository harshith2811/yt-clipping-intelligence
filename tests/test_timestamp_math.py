"""
Tests for timestamp boundary mathematics, durations, and half-open intervals.
"""

import pytest
from src.yt_clipping.contracts.models import HighlightCandidate, ScoreBreakdown


def test_candidate_boundary_validation():
    breakdown = ScoreBreakdown()
    valid_cand = HighlightCandidate(
        candidate_id="c1",
        video_id="v1",
        start_seconds=10.0,
        end_seconds=45.0,
        duration_seconds=35.0,
        score=80.0,
        breakdown=breakdown,
        hook_title="Valid Moment",
    )
    # Valid within 60s video
    assert valid_cand.validate_bounds(source_duration=60.0) is True

    # Negative start
    neg_cand = HighlightCandidate(
        candidate_id="c2",
        video_id="v1",
        start_seconds=-2.0,
        end_seconds=30.0,
        duration_seconds=32.0,
        score=80.0,
        breakdown=breakdown,
        hook_title="Negative start",
    )
    assert neg_cand.validate_bounds(source_duration=60.0) is False

    # End before start
    inverted_cand = HighlightCandidate(
        candidate_id="c3",
        video_id="v1",
        start_seconds=40.0,
        end_seconds=30.0,
        duration_seconds=-10.0,
        score=80.0,
        breakdown=breakdown,
        hook_title="Inverted bounds",
    )
    assert inverted_cand.validate_bounds(source_duration=60.0) is False

    # Exceeding source duration
    exceeding_cand = HighlightCandidate(
        candidate_id="c4",
        video_id="v1",
        start_seconds=10.0,
        end_seconds=75.0,
        duration_seconds=65.0,
        score=80.0,
        breakdown=breakdown,
        hook_title="Exceeds video length",
    )
    assert exceeding_cand.validate_bounds(source_duration=60.0) is False


def test_floating_point_rounding_precision():
    start = 12.3456
    end = 45.6789
    dur = round(end - start, 2)
    assert dur == 33.33


def test_subtitle_timestamp_rollover_boundaries():
    from src.yt_clipping.rendering.captions import SubtitleGenerator

    # Test ASS rollover when fraction rounds to 100cs
    assert SubtitleGenerator._format_timestamp_ass(0.0) == "0:00:00.00"
    assert SubtitleGenerator._format_timestamp_ass(1.996) == "0:00:02.00"
    assert SubtitleGenerator._format_timestamp_ass(59.999) == "0:01:00.00"
    assert SubtitleGenerator._format_timestamp_ass(3661.05) == "1:01:01.05"

    # Test SRT rollover when fraction rounds to 1000ms
    assert SubtitleGenerator._format_timestamp_srt(0.0) == "00:00:00,000"
    assert SubtitleGenerator._format_timestamp_srt(1.9996) == "00:00:02,000"
    assert SubtitleGenerator._format_timestamp_srt(59.9996) == "00:01:00,000"
    assert SubtitleGenerator._format_timestamp_srt(3661.05) == "01:01:01,050"

