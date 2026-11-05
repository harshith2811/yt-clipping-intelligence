"""
Unit tests for the Solid Shorts Decision Engine (SolidShortsDecider).
"""

import pytest
from src.yt_clipping.detection.solid_shorts import (
    SolidShortsDecider,
    SolidShortsConfig,
    SolidShortsDecision,
)
from src.yt_clipping.contracts.models import (
    HighlightCandidate,
    ScoreBreakdown,
    HeatmapData,
    HeatmapPeak,
)


def make_candidate(
    cid: str,
    start: float,
    end: float,
    score: float,
    hook: float = 7.5,
    moment: float = 7.0,
) -> HighlightCandidate:
    return HighlightCandidate(
        candidate_id=cid,
        video_id="test_vid",
        start_seconds=start,
        end_seconds=end,
        duration_seconds=end - start,
        score=score,
        breakdown=ScoreBreakdown(hook_score=hook, moment_score=moment),
        hook_title=f"Hook for {cid}",
    )


def test_capacity_scaling():
    decider = SolidShortsDecider()

    # Under 90s -> 1 clip
    cap, _ = decider.calculate_capacity_ceiling(60.0)
    assert cap == 1

    # 120s -> 2 clips
    cap, _ = decider.calculate_capacity_ceiling(120.0)
    assert cap == 2

    # 5 minutes (300s) -> 2 clips
    cap, _ = decider.calculate_capacity_ceiling(300.0)
    assert cap == 2

    # 10 minutes (600s) -> 3 clips
    cap, _ = decider.calculate_capacity_ceiling(600.0)
    assert cap == 3

    # 25 minutes (1500s) -> 6 clips
    cap, _ = decider.calculate_capacity_ceiling(1500.0)
    assert cap == 6

    # 60 minutes (3600s) -> 12 clips
    cap, _ = decider.calculate_capacity_ceiling(3600.0)
    assert cap == 12


def test_quality_floor_rejection():
    decider = SolidShortsDecider()
    candidates = [
        make_candidate("c1", 0.0, 30.0, score=85.0, hook=8.0),
        make_candidate("c2", 60.0, 90.0, score=65.0, hook=7.0), # Below 72.0 floor
        make_candidate("c3", 120.0, 150.0, score=55.0, hook=6.0),
    ]

    decision = decider.decide(candidates, duration_seconds=600.0)
    assert decision.recommended_count == 1
    assert decision.selected_candidates[0].candidate_id == "c1"
    assert any("Below solid quality floor" in r for r in decision.reasons)


def test_hook_floor_rejection():
    decider = SolidShortsDecider()
    candidates = [
        make_candidate("c1", 0.0, 30.0, score=85.0, hook=8.0),
        make_candidate("c2", 60.0, 90.0, score=82.0, hook=4.5), # Weak hook (< 6.0)
        make_candidate("c3", 120.0, 150.0, score=79.0, hook=7.5),
    ]

    decision = decider.decide(candidates, duration_seconds=600.0)
    assert decision.recommended_count == 2
    selected_ids = [c.candidate_id for c in decision.selected_candidates]
    assert selected_ids == ["c1", "c3"]
    assert any("Hook score 4.5/10 is below threshold" in r for r in decision.reasons)


def test_temporal_overlap_suppression():
    decider = SolidShortsDecider()
    candidates = [
        make_candidate("c1", 10.0, 50.0, score=85.0),
        make_candidate("c2", 20.0, 60.0, score=83.0), # Heavy overlap with c1
        make_candidate("c3", 100.0, 140.0, score=81.0), # Independent
    ]

    decision = decider.decide(candidates, duration_seconds=600.0)
    assert decision.recommended_count == 2
    selected_ids = [c.candidate_id for c in decision.selected_candidates]
    assert selected_ids == ["c1", "c3"]


def test_quality_cliff_detection():
    decider = SolidShortsDecider()
    candidates = [
        make_candidate("c1", 0.0, 30.0, score=88.0, hook=8.5),
        make_candidate("c2", 60.0, 90.0, score=86.0, hook=8.0),
        make_candidate("c3", 120.0, 150.0, score=73.0, hook=6.5), # Cliff: drop of 14 points
    ]

    decision = decider.decide(candidates, duration_seconds=600.0)
    assert decision.recommended_count == 2
    assert decision.quality_cliff_detected_at == 2
    assert any("Quality Cliff detected" in r for r in decision.reasons)


def test_heatmap_peak_boost():
    decider = SolidShortsDecider()
    # c2 has a lower base score (76 vs 78), but covers the global #1 peak at 75s
    c1 = make_candidate("c1", 0.0, 30.0, score=78.0)
    c2 = make_candidate("c2", 60.0, 90.0, score=76.0)

    heatmap = HeatmapData(
        video_id="test_vid",
        source="TEST",
        peaks=[
            HeatmapPeak(
                peak_id="p1",
                start_time=65.0,
                end_time=85.0,
                center_time=75.0,
                intensity=0.90,
                prominence=0.85,
                width_seconds=20.0,
                classification="GLOBAL_MAXIMA",
                suggested_clip_start=65.0,
                suggested_clip_end=85.0,
            )
        ]
    )

    decision = decider.decide([c1, c2], duration_seconds=600.0, heatmap_data=heatmap, target_count=1)
    # c2 receives a boost and overtakes c1
    assert decision.recommended_count == 1
    assert decision.selected_candidates[0].candidate_id == "c2"
