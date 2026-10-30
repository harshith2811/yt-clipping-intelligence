"""
Tests for TrendAnalyzer: velocity modeling, channel baseline normalization,
engagement ratios, and Composite Virality Index (CVI).
"""

import pytest
from datetime import datetime, timezone, timedelta
from src.yt_clipping.contracts.models import CreatorSource, TrendReport
from src.yt_clipping.discovery.trend_analyzer import TrendAnalyzer


def test_trend_velocity_and_outlier_classification():
    analyzer = TrendAnalyzer()

    # Creator with baseline of 24,000 views per 48h (~500 views/hour)
    creator = CreatorSource(
        creator_id="c_tech",
        name="Tech Creator",
        channel_id="UC_TECH",
        channel_url="https://youtube.com/c/tech",
        baseline_views=24000.0,
    )

    now = datetime.now(timezone.utc)
    # Published 4 hours ago
    pub_iso = (now - timedelta(hours=4)).isoformat()

    # Video with 20,000 views in 4 hours -> 5,000 views/hr (10x baseline multiplier!)
    # 1,200 likes (6.0% LVR), 100 comments (0.5% CVR)
    report = analyzer.analyze_metrics(
        video_id="v_viral_1",
        title="Viral Outlier Video",
        channel_id="UC_TECH",
        channel_title="Tech Creator",
        published_at_iso=pub_iso,
        view_count=20000,
        like_count=1200,
        comment_count=100,
        creator=creator,
    )

    assert report.view_velocity_per_hour == 5000.0
    assert report.velocity_multiplier >= 9.0
    assert report.like_ratio_pct == 6.0
    assert report.comment_ratio_pct == 0.5
    assert report.virality_index >= 90.0
    assert report.classification == "VIRAL_EXPLOSION"
    assert "Breakout outlier" in report.rationale


def test_underperforming_video_classification():
    analyzer = TrendAnalyzer()

    creator = CreatorSource(
        creator_id="c_top",
        name="Top Creator",
        channel_id="UC_TOP",
        channel_url="https://youtube.com/c/top",
        baseline_views=100000.0,  # ~2,083 views/hr
    )

    now = datetime.now(timezone.utc)
    # Published 10 hours ago
    pub_iso = (now - timedelta(hours=10)).isoformat()

    # Only 5,000 views in 10 hours -> 500 views/hr (0.24x baseline)
    report = analyzer.analyze_metrics(
        video_id="v_low",
        title="Slow Day Video",
        channel_id="UC_TOP",
        channel_title="Top Creator",
        published_at_iso=pub_iso,
        view_count=5000,
        like_count=50,
        comment_count=5,
        creator=creator,
    )

    assert report.velocity_multiplier < 0.5
    assert report.classification == "UNDERPERFORMING"
    assert report.virality_index < 40.0


def test_steady_pace_video_classification():
    analyzer = TrendAnalyzer()

    creator = CreatorSource(
        creator_id="c_steady",
        name="Steady Creator",
        channel_id="UC_STEADY",
        channel_url="https://youtube.com/c/steady",
        baseline_views=48000.0,  # ~1,000 views/hr
    )

    now = datetime.now(timezone.utc)
    pub_iso = (now - timedelta(hours=6)).isoformat()

    # 6,000 views in 6 hours -> 1,000 views/hr (1.0x baseline)
    report = analyzer.analyze_metrics(
        video_id="v_steady",
        title="Standard Upload",
        channel_id="UC_STEADY",
        channel_title="Steady Creator",
        published_at_iso=pub_iso,
        view_count=6000,
        like_count=200,
        comment_count=15,
        creator=creator,
    )

    assert abs(report.velocity_multiplier - 1.0) < 0.1
    assert report.classification == "STEADY"
