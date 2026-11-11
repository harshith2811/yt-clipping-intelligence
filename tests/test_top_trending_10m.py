"""
Tests for Top Trending Videos from 10M+ Subscriber Channels.
Verifies channel verification, quality scoring, link export, and clipper streaming.
"""

import pytest
import os
import json
from unittest.mock import patch, MagicMock

from top_trending_videos_in_youtube import (
    VERIFIED_10M_CHANNELS,
    MIN_SUBSCRIBER_THRESHOLD,
    ChannelInfo,
    TopTrending10MFetcher,
    QualityTrendingVideo,
    ClipperStreamer,
    get_channel_by_id,
    verify_channels_batch,
)
from top_trending_videos_in_youtube.fetcher import parse_duration_to_seconds


def test_channel_registry_thresholds():
    """Ensures all channels in the verified registry meet the >= 10M threshold."""
    assert len(VERIFIED_10M_CHANNELS) >= 10
    for ch in VERIFIED_10M_CHANNELS:
        assert ch.subscriber_count >= MIN_SUBSCRIBER_THRESHOLD
        assert ch.channel_id.startswith("UC")
        assert ch.handle.startswith("@")
        assert ch.uploads_playlist_id.startswith("UU")
        assert "M" in ch.subscriber_count_formatted or "B" in ch.subscriber_count_formatted


def test_get_channel_by_id():
    """Verifies channel lookup by ID."""
    mrbeast = get_channel_by_id("UCX6OQ3DkcsbYNE6H8uQQuVA")
    assert mrbeast is not None
    assert mrbeast.title == "MrBeast"

    unknown = get_channel_by_id("UC_non_existent")
    assert unknown is None


def test_parse_duration_to_seconds():
    """Verifies ISO 8601 duration parser."""
    assert parse_duration_to_seconds("PT15M30S") == 930.0
    assert parse_duration_to_seconds("PT1H2M10S") == 3730.0
    assert parse_duration_to_seconds("PT45S") == 45.0
    assert parse_duration_to_seconds("") == 0.0


def test_fetcher_clipping_score_calculation():
    """Tests the virality and suitability scoring algorithm."""
    fetcher = TopTrending10MFetcher(api_key=None)
    # High resonance, optimal duration (15m = 900s)
    score_high = fetcher._compute_clipping_score(
        duration=900.0,
        views=10_000_000,
        likes=500_000,
        comments=40_000,
        subs=20_000_000,
    )
    assert score_high >= 70.0
    suitability = fetcher._assess_suitability(900.0, score_high)
    assert "High Potential" in suitability or "Tier-1" in suitability

    # Short/low volume
    score_low = fetcher._compute_clipping_score(
        duration=60.0,
        views=1000,
        likes=10,
        comments=1,
        subs=10_000_000,
    )
    assert score_low < score_high


def test_fetcher_fallback_returns_10m_quality_videos():
    """Ensures fallback returns pre-verified videos when offline."""
    fetcher = TopTrending10MFetcher(api_key=None)
    videos = fetcher.get_top_trending_10m_list(limit=5)
    assert len(videos) == 5
    for v in videos:
        assert v.channel_subscribers >= MIN_SUBSCRIBER_THRESHOLD
        assert v.url.startswith("https://www.youtube.com/watch?v=")
        assert v.duration_seconds >= 180.0
        assert v.virality_score > 50.0


def test_streamer_export_links(tmp_path):
    """Verifies that streamer exports both valid JSON and clean plain TXT URLs."""
    streamer = ClipperStreamer()
    json_file = str(tmp_path / "test_links.json")
    txt_file = str(tmp_path / "test_links.txt")

    mock_vids = streamer.fetcher._get_fallback_10m_videos()[:4]
    with patch.object(streamer.fetcher, "get_top_trending_10m_list", return_value=mock_vids):
        videos = streamer.export_fresh_links(json_path=json_file, txt_path=txt_file, limit=4)
        assert len(videos) == 4
        assert os.path.exists(json_file)
        assert os.path.exists(txt_file)

        # Verify JSON
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 4
        assert data[0]["channel_subscribers"] >= MIN_SUBSCRIBER_THRESHOLD

        # Verify TXT
        with open(txt_file, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 4
        assert lines[0].startswith("https://www.youtube.com/watch?v=")



def test_streamer_stream_to_studio_offline_fallback():
    """Verifies in-process fallback when web studio server is offline or unreachable."""
    streamer = ClipperStreamer(studio_url="http://127.0.0.1:59999")  # Unused port
    with patch("top_trending_videos_in_youtube.streamer.ClipperStreamer.stream_in_process") as mock_in_proc:
        mock_in_proc.return_value = {"success": True, "mode": "in_process"}
        res = streamer.stream_to_studio(video_url_or_id="https://www.youtube.com/watch?v=0e3GPea1Tyg")
        assert res["success"] is True
        mock_in_proc.assert_called_once()


def test_streamer_stream_and_publish():
    """Verifies stream_and_publish workflow dispatch."""
    streamer = ClipperStreamer(studio_url="http://127.0.0.1:59999")
    with patch("top_trending_videos_in_youtube.streamer.ClipperStreamer.stream_in_process") as mock_in_proc:
        mock_in_proc.return_value = {"success": True, "mode": "in_process"}
        res = streamer.stream_and_publish(
            video_url_or_id="https://www.youtube.com/watch?v=0e3GPea1Tyg",
            max_clips=1,
            auto_publish=True,
        )
        assert res["success"] is True
        mock_in_proc.assert_called_once()


def test_streamer_stream_and_publish_auto_publish_false():
    """Verifies stream_and_publish respects auto_publish=False flag in API payload."""
    streamer = ClipperStreamer(studio_url="http://127.0.0.1:8000")
    captured_payload = {}

    def fake_urlopen(req, timeout=12):
        nonlocal captured_payload
        captured_payload = json.loads(req.data.decode("utf-8"))
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"success": True, "job_id": "test_j1", "status": "QUEUED"}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        res = streamer.stream_and_publish(
            video_url_or_id="https://www.youtube.com/watch?v=0e3GPea1Tyg",
            max_clips=2,
            auto_publish=False,
        )
        assert res["success"] is True
        assert captured_payload.get("auto_publish") is False
        assert captured_payload.get("enable_flux") is True

