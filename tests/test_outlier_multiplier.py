"""
Unit tests for OutlierMultiplier:
- Channel median calculations
- Baseline requirement (>= 4 videos per channel)
- Outlier virality multiplier: Multiple = Video Views / Median(Channel Views)
- Classification of proven algorithmic breakouts (>= 3.0x median)
- Invariance to channel size (small vs large channels)
- Integration with PublicMetricRanker
"""

import pytest
from src.yt_clipping.contracts.models import VideoCandidate, CreatorSource
from src.yt_clipping.discovery.outlier import (
    OutlierMultiplier,
    OutlierReport,
    OutlierClassification,
)
from src.yt_clipping.discovery.ranker import PublicMetricRanker


def test_channel_median_computation():
    multiplier = OutlierMultiplier()

    # Fewer than 4 videos -> returns None
    assert multiplier.compute_channel_median([1000, 2000, 3000]) is None

    # Exactly 4 videos -> median of [1000, 2000, 3000, 4000] = (2000 + 3000)/2 = 2500
    median_4 = multiplier.compute_channel_median([1000, 2000, 3000, 4000])
    assert median_4 == 2500.0

    # 5 videos -> median of [1000, 2000, 3000, 5000, 9000] = 3000
    median_5 = multiplier.compute_channel_median([1000, 2000, 3000, 5000, 9000])
    assert median_5 == 3000.0


def test_outlier_breakout_classification():
    multiplier = OutlierMultiplier()

    # Channel history: 4 videos with median 10,000 views
    history = [8000, 10000, 10000, 12000]
    # Candidate video with 35,000 views -> 3.5x median!
    report = multiplier.calculate_virality_multiple(
        video_views=35000,
        channel_views=history,
        video_id="v_breakout",
        channel_id="c_test",
    )

    assert report.sample_size == 4
    assert report.has_sufficient_baseline is True
    assert report.channel_median_views == 10000.0
    assert report.virality_multiple == 3.5
    assert report.is_outlier is True
    assert report.is_algorithmic_breakout is True
    assert report.classification == OutlierClassification.BREAKOUT_OUTLIER
    assert "Proven algorithmic breakout at 3.5x" in report.rationale


def test_insufficient_baseline_protection():
    multiplier = OutlierMultiplier()

    # Only 2 historical videos (< 4 required)
    history = [5000, 7000]
    report = multiplier.calculate_virality_multiple(
        video_views=30000,
        channel_views=history,
        video_id="v_unproven",
        channel_id="c_new",
    )

    assert report.sample_size == 2
    assert report.has_sufficient_baseline is False
    assert report.is_algorithmic_breakout is False
    assert report.classification == OutlierClassification.INSUFFICIENT_BASELINE
    assert "Insufficient channel history" in report.rationale


def test_channel_size_invariance():
    """
    Validates that a 3.0x multiplier on a 1k channel and a 3.0x multiplier
    on a 1M channel are both identified as breakout outliers equally.
    """
    multiplier = OutlierMultiplier()

    # Small Creator: Median = 1,000 views, upload = 3,200 views (3.2x)
    small_history = [800, 1000, 1000, 1200]
    small_rep = multiplier.calculate_virality_multiple(
        video_views=3200, channel_views=small_history, video_id="v_small"
    )

    # Large Creator: Median = 1,000,000 views, upload = 3,200,000 views (3.2x)
    large_history = [800000, 1000000, 1000000, 1200000]
    large_rep = multiplier.calculate_virality_multiple(
        video_views=3200000, channel_views=large_history, video_id="v_large"
    )

    assert small_rep.virality_multiple == 3.2
    assert large_rep.virality_multiple == 3.2
    assert small_rep.is_algorithmic_breakout is True
    assert large_rep.is_algorithmic_breakout is True
    assert small_rep.classification == large_rep.classification == OutlierClassification.BREAKOUT_OUTLIER


def test_rank_candidates_by_outlier():
    multiplier = OutlierMultiplier()

    cand1 = VideoCandidate(
        video_id="v_steady",
        title="Steady Video",
        url="https://youtube.com/watch?v=v_steady",
        creator_id="c1",
        published_at="2026-10-30T10:00:00Z",
        retrieved_at="2026-10-30T12:00:00Z",
        duration_seconds=120.0,
        view_count=10000,  # 1.0x median of 10k
    )
    cand2 = VideoCandidate(
        video_id="v_breakout",
        title="Breakout Video",
        url="https://youtube.com/watch?v=v_breakout",
        creator_id="c2",
        published_at="2026-10-30T10:00:00Z",
        retrieved_at="2026-10-30T12:00:00Z",
        duration_seconds=120.0,
        view_count=15000,  # 3.0x median of 5k!
    )

    histories = {
        "c1": [9000, 10000, 10000, 11000],  # median 10k
        "c2": [4000, 5000, 5000, 6000],     # median 5k
    }

    ranked = multiplier.rank_candidates_by_outlier([cand1, cand2], histories)
    # cand2 (3.0x) should rank above cand1 (1.0x)
    assert ranked[0][0].video_id == "v_breakout"
    assert ranked[0][1].is_algorithmic_breakout is True
    assert ranked[1][0].video_id == "v_steady"


def test_public_metric_ranker_integration():
    ranker = PublicMetricRanker()
    creator = CreatorSource(
        creator_id="c_test",
        name="Tester",
        channel_id="UC_TEST",
        channel_url="https://youtube.com/test",
        baseline_views=10000.0,
    )
    cand = VideoCandidate(
        video_id="v_int",
        title="Integration Test Video",
        url="https://youtube.com/watch?v=v_int",
        creator_id="c_test",
        published_at="2026-10-30T10:00:00Z",
        retrieved_at="2026-10-30T14:00:00Z",
        duration_seconds=180.0,
        view_count=30000,
        like_count=1500,
    )

    channel_views = [8000, 10000, 10000, 12000]  # Median = 10,000 -> 3.0x multiple
    score = ranker.compute_discovery_score(cand, creator, channel_views=channel_views)
    assert score > 60.0
    assert "Outlier=" in cand.discovery_rationale
    assert "median breakout" in cand.discovery_rationale


def test_trend_analyzer_channel_median_outlier_integration():
    from src.yt_clipping.discovery.trend_analyzer import TrendAnalyzer
    analyzer = TrendAnalyzer()

    channel_views = [1000, 2000, 2000, 3000]  # Median = 2,000
    report = analyzer.analyze_metrics(
        video_id="v_outlier_trend",
        title="Breakout Video",
        channel_id="c_trend",
        channel_title="Trend Channel",
        published_at_iso="2026-10-31T10:00:00Z",
        view_count=8000,  # 4.0x median -> algorithmic breakout!
        like_count=500,
        comment_count=80,
        channel_views=channel_views,
    )
    assert report.classification == "VIRAL_EXPLOSION"
    assert "Outlier breakout at 4.0x channel median" in report.rationale

