"""
Comprehensive Unit and Integration Tests for:
- Autonomous YouTube Upload Pinger Daemon (pinger_daemon.py)
- Statistical Virality & Early-Hour Velocity Scraper (trend_scorer.py)
- Attribution & Legal Compliance Engine (attribution_engine.py)
- Channel Watcher CLI Manager (channel_watcher.py)
"""

import os
import tempfile
import sqlite3
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import urllib.error

from src.yt_clipping.discovery.trend_scorer import (
    TrendScorer,
    ViralityClassification,
    VelocityTelemetry,
)
from src.yt_clipping.discovery.attribution_engine import (
    AttributionEngine,
    CreatorPolicy,
    AttributionPackage,
)
from src.yt_clipping.discovery.pinger_daemon import PingerDaemon
from src.yt_clipping.discovery.channel_watcher import (
    ChannelWatcher,
    resolve_channel_identifier,
)
from src.yt_clipping.orchestration.db import DatabaseManager
from src.yt_clipping.orchestration.queue import JobQueue, JobPriority


# ==============================================================================
# SAMPLE TEST FIXTURES & DATA
# ==============================================================================

SAMPLE_YT_ATOM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">
  <link rel="self" href="http://www.youtube.com/feeds/videos.xml?channel_id=UC_x5XG1OV2P6uZZ5FSM9Ttw"/>
  <id>yt:channel:UC_x5XG1OV2P6uZZ5FSM9Ttw</id>
  <title>Google Developers</title>
  <author>
    <name>Google Developers</name>
    <uri>https://www.youtube.com/channel/UC_x5XG1OV2P6uZZ5FSM9Ttw</uri>
  </author>
  <entry>
    <id>yt:video:demoVid12345</id>
    <yt:videoId>demoVid12345</yt:videoId>
    <yt:channelId>UC_x5XG1OV2P6uZZ5FSM9Ttw</yt:channelId>
    <title>Accelerate shipping to scale with Google Antigravity</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=demoVid12345"/>
    <author>
      <name>Google Developers</name>
      <uri>https://www.youtube.com/channel/UC_x5XG1OV2P6uZZ5FSM9Ttw</uri>
    </author>
    <published>2026-10-31T10:00:00+00:00</published>
    <updated>2026-10-31T10:05:00+00:00</updated>
  </entry>
  <entry>
    <id>yt:video:demoVid67890</id>
    <yt:videoId>demoVid67890</yt:videoId>
    <yt:channelId>UC_x5XG1OV2P6uZZ5FSM9Ttw</yt:channelId>
    <title>Building real-time vision with Gemini Live</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=demoVid67890"/>
    <author>
      <name>Google Developers</name>
    </author>
    <published>2026-10-30T15:00:00+00:00</published>
    <updated>2026-10-30T15:02:00+00:00</updated>
  </entry>
</feed>
"""


@pytest.fixture
def temp_db():
    """Provides a fresh isolated SQLite database with migrations applied."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    db_mgr = DatabaseManager(db_path)
    db_mgr.init_schema()
    yield db_path
    
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass


# ==============================================================================
# 1. TREND SCORER & EARLY-HOUR VELOCITY TESTS
# ==============================================================================

class TestTrendScorer:
    """Tests view velocity calculation, age clamping, and virality classification."""

    def test_hourly_velocity_calculation_and_age_clamp(self):
        scorer = TrendScorer()
        
        # Test 1: Video published 15 minutes ago (0.25 hrs), 5,000 views
        # V_hourly = 5,000 / 0.25 = 20,000 views/hr
        published_15m = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
        res = scorer.evaluate_video(
            video_id="v1",
            channel_id="c1",
            title="Fast Growth Video",
            published_at_iso=published_15m,
            view_count=5000,
            like_count=500,
            comment_count=50,
            baseline_views=10000.0,
        )
        assert abs(res.hourly_velocity - 20000.0) < 50.0
        assert res.age_hours >= 0.25

        # Test 2: Video published 5 minutes ago (<0.25 hrs) must clamp age to 0.25
        published_5m = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        res_clamp = scorer.evaluate_video(
            video_id="v2",
            channel_id="c1",
            title="Brand New Video",
            published_at_iso=published_5m,
            view_count=2500,
            like_count=250,
            comment_count=25,
            baseline_views=10000.0,
        )
        # 2500 / 0.25 = 10,000 views/hr
        assert abs(res_clamp.hourly_velocity - 10000.0) < 50.0

    def test_virality_classifications(self):
        scorer = TrendScorer()
        # Baseline = 48,000 views over 48h -> baseline velocity = 1,000 views/hr
        baseline = 48000.0
        now = datetime.now(timezone.utc)

        # 1. VIRAL_EXPLOSION: Velocity >= 3.0x baseline (>= 3000 views/hr)
        res_viral = scorer.evaluate_video(
            video_id="v_viral",
            channel_id="c1",
            title="Exploding Video",
            published_at_iso=(now - timedelta(hours=2)).isoformat(),
            view_count=8000,  # 8000 / 2 = 4,000 views/hr (4.0x baseline)
            like_count=800,
            comment_count=80,
            baseline_views=baseline,
        )
        assert res_viral.classification == ViralityClassification.VIRAL_EXPLOSION
        assert res_viral.velocity_multiplier >= 3.0

        # 2. TRENDING_HIGH: 1.5x <= Velocity < 3.0x (1,500 - 3,000 views/hr)
        res_trending = scorer.evaluate_video(
            video_id="v_trend",
            channel_id="c1",
            title="Trending Video",
            published_at_iso=(now - timedelta(hours=2)).isoformat(),
            view_count=4000,  # 4000 / 2 = 2,000 views/hr (2.0x baseline)
            like_count=400,
            comment_count=40,
            baseline_views=baseline,
        )
        assert res_trending.classification == ViralityClassification.TRENDING_HIGH
        assert 1.5 <= res_trending.velocity_multiplier < 3.0

        # 3. STEADY: 0.8x <= Velocity < 1.5x (800 - 1,500 views/hr)
        res_steady = scorer.evaluate_video(
            video_id="v_steady",
            channel_id="c1",
            title="Steady Video",
            published_at_iso=(now - timedelta(hours=2)).isoformat(),
            view_count=2000,  # 2000 / 2 = 1,000 views/hr (1.0x baseline)
            like_count=200,
            comment_count=20,
            baseline_views=baseline,
        )
        assert res_steady.classification == ViralityClassification.STEADY
        assert 0.8 <= res_steady.velocity_multiplier < 1.5

        # 4. UNDERPERFORMING: Velocity < 0.8x (< 800 views/hr)
        res_under = scorer.evaluate_video(
            video_id="v_under",
            channel_id="c1",
            title="Slow Video",
            published_at_iso=(now - timedelta(hours=2)).isoformat(),
            view_count=600,  # 600 / 2 = 300 views/hr (0.3x baseline)
            like_count=60,
            comment_count=6,
            baseline_views=baseline,
        )
        assert res_under.classification == ViralityClassification.UNDERPERFORMING
        assert res_under.velocity_multiplier < 0.8

    def test_resonance_filtering_rejection_of_clickbait_and_bots(self):
        scorer = TrendScorer()
        baseline = 10000.0
        now = datetime.now(timezone.utc)

        # High views (10,000 in 1h) but abysmally low likes (10 likes = 0.1% LVR, required >= 1.2%)
        res_bot = scorer.evaluate_video(
            video_id="v_bot",
            channel_id="c1",
            title="Suspicious Bot Spike",
            published_at_iso=(now - timedelta(hours=1)).isoformat(),
            view_count=10000,
            like_count=10,
            comment_count=1,
            baseline_views=baseline,
        )
        assert res_bot.is_resonant is False
        assert "LOW_LIKE_RATIO" in res_bot.resonance_flag

        # Resonant upload: 5% LVR and 0.5% CVR
        res_good = scorer.evaluate_video(
            video_id="v_good",
            channel_id="c1",
            title="High Engagement Video",
            published_at_iso=(now - timedelta(hours=1)).isoformat(),
            view_count=10000,
            like_count=500,
            comment_count=50,
            baseline_views=baseline,
        )
        assert res_good.is_resonant is True
        assert res_good.resonance_flag == "HEALTHY_ORGANIC_ENGAGEMENT"


# ==============================================================================
# 2. ATTRIBUTION & LEGAL COMPLIANCE ENGINE TESTS
# ==============================================================================

class TestAttributionEngine:
    """Tests caption formatting, sponsor ad removal, and creator policy governance."""

    def test_attribution_formatting(self, temp_db):
        engine = AttributionEngine(db_path=temp_db)
        pkg = engine.format_attribution(
            video_id="abc123XYZ",
            creator_name="Andrew Huberman",
            creator_handle="@hubermanlab",
            category_tags=["neuroscience", "sleep", "health"],
        )

        # Verify mandatory elements
        assert "@hubermanlab" in pkg.caption_credit
        assert "Andrew Huberman" in pkg.caption_credit
        assert "https://youtu.be/abc123XYZ" in pkg.caption_credit
        assert "Curated for educational discussion" in pkg.disclaimer
        
        # Verify full description composition
        desc = pkg.full_description
        assert "Original Content by: @hubermanlab (Andrew Huberman)" in desc
        assert "Watch the full episode: https://youtu.be/abc123XYZ" in desc
        assert "#neuroscience" in pkg.hashtags
        assert "#sleep" in pkg.hashtags

    def test_sponsor_segment_purging(self, temp_db):
        engine = AttributionEngine(db_path=temp_db)
        raw_description = (
            "In this episode we talk about dopamine and focus.\n"
            "This video is sponsored by NordVPN! Get 70% off at nordvpn.com/huberman with code HUBERMAN.\n"
            "Also special thanks to our sponsors at Displate! Use link for 20% discount.\n"
            "Visit betterhelp.com/huberman for 10% off therapy.\n"
            "00:00 Introduction\n02:30 Dopamine Dynamics"
        )
        cleaned, has_sponsor, found_keywords = engine.purge_sponsor_segments(raw_description)
        assert has_sponsor is True
        assert "nordvpn" not in cleaned.lower()
        assert "displate" not in cleaned.lower()
        assert "betterhelp" not in cleaned.lower()
        assert "Dopamine Dynamics" in cleaned

    def test_creator_policy_classification_and_dmca_skip(self, temp_db):
        engine = AttributionEngine(db_path=temp_db)
        
        # Test 1: Open Affiliate creator
        engine.set_creator_policy(
            channel_id="UC_open",
            channel_name="Open Creator",
            creator_handle="@open_creator",
            policy=CreatorPolicy.OPEN_AFFILIATE,
            notes="Open clipping permitted",
        )
        pkg_open = engine.format_attribution(
            video_id="vid1",
            creator_name="Open Creator",
            creator_handle="@open_creator",
            channel_id="UC_open",
        )
        assert pkg_open.is_safe_to_clip is True

        # Test 2: Strict Copyright creator (Zero tolerance DMCA)
        engine.set_creator_policy(
            channel_id="UC_strict",
            channel_name="Strict Creator",
            creator_handle="@strict_creator",
            policy=CreatorPolicy.STRICT_COPYRIGHT,
            notes="Active DMCA strikes issued",
        )
        pkg_strict = engine.format_attribution(
            video_id="vid2",
            creator_name="Strict Creator",
            creator_handle="@strict_creator",
            channel_id="UC_strict",
        )
        assert pkg_strict.is_safe_to_clip is False
        assert "BLOCKED" in pkg_strict.compliance_notes


# ==============================================================================
# 3. PINGER DAEMON & ZERO-QUOTA POLLING TESTS
# ==============================================================================

class TestPingerDaemon:
    """Tests Atom XML parsing, ETag/304 caching, and job queuing."""

    def test_atom_feed_xml_parsing(self):
        daemon = PingerDaemon()
        videos = daemon.parse_atom_feed(SAMPLE_YT_ATOM_FEED)
        
        assert len(videos) == 2
        v1 = videos[0]
        assert v1["video_id"] == "demoVid12345"
        assert v1["channel_id"] == "UC_x5XG1OV2P6uZZ5FSM9Ttw"
        assert v1["title"] == "Accelerate shipping to scale with Google Antigravity"
        assert v1["author"] == "Google Developers"
        assert v1["published_at"] == "2026-10-31T10:00:00+00:00"

        v2 = videos[1]
        assert v2["video_id"] == "demoVid67890"
        assert v2["title"] == "Building real-time vision with Gemini Live"

    def test_conditional_get_http_304_caching(self):
        daemon = PingerDaemon()
        
        # Mock HTTP 304 Not Modified
        with patch("urllib.request.urlopen") as mock_urlopen:
            error = urllib.error.HTTPError(
                url="https://www.youtube.com/feeds/videos.xml?channel_id=UC123",
                code=304,
                msg="Not Modified",
                hdrs={},
                fp=None,
            )
            mock_urlopen.side_effect = error

            xml_data, modified, etag, last_mod = daemon.fetch_channel_feed(
                channel_id="UC123",
                etag='"test-etag-123"',
                last_modified="Fri, 31 Oct 2026 10:00:00 GMT",
            )
            assert modified is False
            assert xml_data is None
            assert daemon.telemetry["http_304_cache_hits"] == 1

    def test_process_video_delta_queuing_viral_upload(self, temp_db):
        daemon = PingerDaemon(db_path=temp_db)
        
        # Ensure creator policy is open
        daemon.attribution_engine.set_creator_policy(
            channel_id="UC_x5XG1OV2P6uZZ5FSM9Ttw",
            channel_name="Google Developers",
            creator_handle="@GoogleDevelopers",
            policy=CreatorPolicy.OPEN_AFFILIATE,
        )

        # Mock metrics to simulate a viral explosion upload (50,000 views in 1 hour)
        with patch.object(daemon, "get_video_public_metrics") as mock_metrics:
            mock_metrics.return_value = {
                "views": 50000,
                "likes": 3500,
                "comments": 400,
            }

            now_iso = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            job_id = daemon.process_video_delta(
                v_id="viral_vid_001",
                ch_id="UC_x5XG1OV2P6uZZ5FSM9Ttw",
                title="Viral Breakthrough AI Release",
                pub_at=now_iso,
                author="Google Developers",
                baseline_views=10000.0,
            )

            assert job_id is not None
            assert daemon.telemetry["jobs_queued"] == 1

            # Verify it landed in SQLite queue
            conn = sqlite3.connect(temp_db)
            try:
                row = conn.execute("SELECT job_id, video_id, priority, status FROM jobs WHERE video_id = 'viral_vid_001'").fetchone()
                assert row is not None
                assert row[0] == job_id
                assert row[1] == "viral_vid_001"
                assert row[2] == int(JobPriority.CRITICAL)  # Multiplier >= 3.0x -> CRITICAL priority
                assert row[3] == "PENDING"
            finally:
                conn.close()


# ==============================================================================
# 4. CHANNEL WATCHER CLI TESTS
# ==============================================================================

class TestChannelWatcher:
    """Tests channel registry management, handle resolution, and status tracking."""

    def test_resolve_channel_identifier_canonical(self):
        # Canonical UC ID passes directly
        cid, handle, name = resolve_channel_identifier("UC2D2CMWXMOVWx7giW1n3LIg")
        assert cid == "UC2D2CMWXMOVWx7giW1n3LIg"
        assert handle == "@UC2D2CMWXMOVWx7giW1n3LIg"

    def test_channel_crud_operations(self, temp_db):
        watcher = ChannelWatcher(db_path=temp_db)
        
        # 1. Add channel
        res = watcher.add_channel(
            identifier="UC_test12345",
            baseline_views=25000.0,
            policy=CreatorPolicy.OPEN_AFFILIATE,
        )
        assert res["channel_id"] == "UC_test12345"

        # 2. List channels
        channels = watcher.list_channels()
        assert len(channels) == 1
        assert channels[0]["channel_id"] == "UC_test12345"
        assert channels[0]["baseline_views"] == 25000.0
        assert channels[0]["clipping_policy"] == CreatorPolicy.OPEN_AFFILIATE.value
        assert channels[0]["paused"] == 0

        # 3. Pause channel
        watcher.set_pause("UC_test12345", paused=True)
        channels = watcher.list_channels()
        assert channels[0]["paused"] == 1

        # 4. Resume channel
        watcher.set_pause("UC_test12345", paused=False)
        channels = watcher.list_channels()
        assert channels[0]["paused"] == 0

        # 5. Remove channel (deactivates active status)
        watcher.remove_channel("UC_test12345")
        assert len(watcher.list_channels(active_only=True)) == 0
        all_channels = watcher.list_channels()
        assert len(all_channels) == 1
        assert all_channels[0]["active"] == 0
