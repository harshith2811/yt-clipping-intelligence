"""
Tests for explainable multi-signal highlight scoring and composite calculations.
"""

import pytest
from src.yt_clipping.contracts.models import (
    HighlightCandidate,
    ScoreBreakdown,
    Transcript,
    TranscriptSegment,
    WordTimestamp,
)
from src.yt_clipping.scoring.scorecard import ExplainableScorecardScorer


def test_scorecard_composite_formula():
    # Test formula weights directly
    breakdown = ScoreBreakdown(
        hook_score=10.0,         # 10.0 * 3.0 = 30.0
        moment_score=10.0,       # 10.0 * 2.5 = 25.0
        coherence_score=10.0,    # 10.0 * 2.0 = 20.0
        pacing_score=10.0,       # 10.0 * 1.0 = 10.0
        audio_energy_score=10.0, # 10.0 * 1.0 = 10.0
        visual_score=10.0,       # 10.0 * 0.5 = 5.0 -> Sum = 100.0
        confidence=1.0,
    )
    score = breakdown.compute_composite_score()
    assert score == 100.0


def test_explainable_scorer_hook_detection():
    scorer = ExplainableScorecardScorer()
    transcript = Transcript(
        video_id="v1",
        language="en",
        duration_seconds=60.0,
        text="The secret to scaling AI models is surprisingly simple.",
    )

    candidate = HighlightCandidate(
        candidate_id="c1",
        video_id="v1",
        start_seconds=0.0,
        end_seconds=30.0,
        duration_seconds=30.0,
        score=0.0,
        breakdown=ScoreBreakdown(),
        hook_title="Opening hook test",
        transcript_text="The secret to scaling AI models is surprisingly simple. Most teams fail because they rush.",
    )

    scored = scorer.score_candidate(candidate, transcript)
    assert scored.breakdown.hook_score >= 7.0  # contains "secret" keyword
    assert "Hook=" in scored.rationale
    assert scored.score > 50.0


def test_coherence_penalty_for_dangling_starts():
    scorer = ExplainableScorecardScorer()
    transcript = Transcript(video_id="v1", language="en", duration_seconds=60.0, text="")

    # Starts with dangling "and so he said"
    candidate = HighlightCandidate(
        candidate_id="c2",
        video_id="v1",
        start_seconds=10.0,
        end_seconds=40.0,
        duration_seconds=30.0,
        score=0.0,
        breakdown=ScoreBreakdown(),
        hook_title="Dangling start",
        transcript_text="and so he said that we should wait.",
    )

    scored = scorer.score_candidate(candidate, transcript)
    assert scored.breakdown.coherence_score < 6.0
