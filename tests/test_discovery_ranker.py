"""
Tests for discovery view velocity calculation, channel normalization, and API quota budgets.
"""

import pytest
from datetime import datetime, timezone, timedelta
from src.yt_clipping.contracts.models import VideoCandidate, CreatorSource, MetricSnapshot
from src.yt_clipping.discovery.ranker import PublicMetricRanker
from src.yt_clipping.discovery.monitor import APIQuotaBudget, ChannelMonitor, parse_iso8601_duration


def test_api_quota_accounting():
    budget = APIQuotaBudget(daily_limit=100)
    assert budget.can_spend(50) is True
    budget.spend(50)
    assert budget.units_spent == 50

    # Remaining is 50, trying to spend 60 should raise
    assert budget.can_spend(60) is False
    with pytest.raises(RuntimeError) as exc_info:
        budget.spend(60)
    assert "quota exceeded" in str(exc_info.value)


def test_view_velocity_calculation():
    ranker = PublicMetricRanker()
    v_id = "test_vid_velocity"

    # Observation 1: 10,000 views at t0
    t0 = datetime(2026, 10, 29, 10, 0, 0, tzinfo=timezone.utc)
    s1 = MetricSnapshot(
        snapshot_id="s1",
        video_id=v_id,
        timestamp=t0.isoformat(),
        view_count=10000,
    )

    # Observation 2: 15,000 views 2 hours later at t0 + 2h
    # Velocity = (15,000 - 10,000) / 2 = 2,500 views/hour
    t1 = t0 + timedelta(hours=2)
    s2 = MetricSnapshot(
        snapshot_id="s2",
        video_id=v_id,
        timestamp=t1.isoformat(),
        view_count=15000,
    )

    velocity = ranker.calculate_view_velocity([s1, s2])
    assert abs(velocity - 2500.0) < 1.0


def test_channel_normalized_discovery_score():
    ranker = PublicMetricRanker()
    now = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)
    pub = now - timedelta(hours=6)

    creator_small = CreatorSource(
        creator_id="small_creator",
        name="Small Creator",
        channel_id="UC_SMALL",
        channel_url="https://youtube.com/@small",
        baseline_views=5000.0,
    )

    # 15,000 views on 5,000 baseline = 3x overperforming!
    candidate = VideoCandidate(
        video_id="v_overperforming",
        title="Breakout Tech Video",
        url="https://youtube.com/watch?v=v_overperforming",
        creator_id="small_creator",
        published_at=pub.isoformat(),
        retrieved_at=now.isoformat(),
        duration_seconds=300.0,
        view_count=15000,
        like_count=900,
    )

    score = ranker.compute_discovery_score(candidate, creator_small, as_of=now)
    assert score >= 50.0
    assert "velocity_ratio" in candidate.discovery_rationale


def test_channel_rss_feed_parsing():
    monitor = ChannelMonitor()
    rss_sample = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>yt:video:vid_rss_1</id>
        <yt:videoId>vid_rss_1</yt:videoId>
        <title>Engineering Deep Dive Episode 1</title>
        <published>2026-10-29T10:00:00+00:00</published>
      </entry>
      <entry>
        <id>yt:video:vid_rss_2</id>
        <yt:videoId>vid_rss_2</yt:videoId>
        <title>Engineering Deep Dive Episode 2</title>
        <published>2026-10-29T11:00:00+00:00</published>
      </entry>
    </feed>
    """
    candidates = monitor.parse_channel_rss(rss_sample, "UC_CHANNEL_TEST")
    assert len(candidates) == 2
    assert candidates[0].video_id == "vid_rss_1"
    assert candidates[0].title == "Engineering Deep Dive Episode 1"
    assert candidates[0].creator_id == "UC_CHANNEL_TEST"

    # Second parse should deduplicate seen video IDs
    second_pass = monitor.parse_channel_rss(rss_sample, "UC_CHANNEL_TEST")
    assert len(second_pass) == 0


def test_channel_monitor_fetch_and_quota():
    budget = APIQuotaBudget(daily_limit=5)
    monitor = ChannelMonitor(quota_budget=budget)

    cand = VideoCandidate(
        video_id="v_mock_1",
        title="Mock Upload",
        url="https://youtube.com/watch?v=v_mock_1",
        creator_id="UC_CHAN",
        published_at="2026-10-29T10:00:00Z",
        retrieved_at="2026-10-29T10:00:00Z",
        duration_seconds=120.0,
        view_count=500,
    )
    monitor.register_mock_video("UC_CHAN", cand)

    results = monitor.fetch_recent_videos("UC_CHAN", limit=5)
    assert len(results) == 1
    assert results[0].video_id == "v_mock_1"
    assert budget.units_spent == 1  # Spent 1 unit for playlistItems


def test_parse_iso8601_duration():
    assert parse_iso8601_duration("PT34M10S") == 2050.0
    assert parse_iso8601_duration("PT1H2M30S") == 3750.0
    assert parse_iso8601_duration("PT45S") == 45.0
    assert parse_iso8601_duration("PT2H") == 7200.0
    assert parse_iso8601_duration("INVALID") == 0.0


