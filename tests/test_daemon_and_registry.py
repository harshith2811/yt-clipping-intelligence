"""
Tests for Channel Registry and Discovery Daemon (FEATURE-01).
"""

import pytest
from src.yt_clipping.discovery.channel_registry import ChannelRegistry
from src.yt_clipping.discovery.daemon import DiscoveryDaemon
from src.yt_clipping.discovery.monitor import ChannelMonitor
from src.yt_clipping.contracts.models import VideoCandidate, RightsStatus


def test_channel_registry_crud(tmp_path):
    db_file = str(tmp_path / "jobs.db")
    registry = ChannelRegistry(db_file)

    # 1. Add channel
    registry.add_channel(
        channel_id="UC_TECH_1",
        name="Tech Channel",
        handle="@techchannel",
        channel_url="https://youtube.com/@techchannel",
        baseline_views=25000.0,
    )

    channels = registry.list_channels(active_only=True)
    assert len(channels) == 1
    assert channels[0]["channel_id"] == "UC_TECH_1"
    assert channels[0]["name"] == "Tech Channel"
    assert channels[0]["baseline_views"] == 25000.0

    # 2. Get creator source
    creator = registry.get_creator_source("UC_TECH_1")
    assert creator is not None
    assert creator.baseline_views == 25000.0

    # 3. Remove channel
    removed = registry.remove_channel("UC_TECH_1")
    assert removed is True
    assert len(registry.list_channels(active_only=True)) == 0
    assert len(registry.list_channels(active_only=False)) == 1


def test_discovery_daemon_single_cycle(tmp_path):
    db_file = str(tmp_path / "jobs.db")
    registry = ChannelRegistry(db_file)
    registry.add_channel("UC_MOCK_CHAN", "Mock Creator", baseline_views=5000.0)

    monitor = ChannelMonitor(db_path=db_file)
    cand = VideoCandidate(
        video_id="v_daemon_1",
        title="Daemon Test Upload",
        url="https://youtube.com/watch?v=v_daemon_1",
        creator_id="UC_MOCK_CHAN",
        published_at="2026-10-31T00:00:00Z",
        retrieved_at="2026-10-31T00:00:00Z",
        duration_seconds=180.0,
        view_count=12000,
    )
    monitor.register_mock_video("UC_MOCK_CHAN", cand)

    daemon = DiscoveryDaemon(
        interval_seconds=1,
        monitor=monitor,
        registry=registry,
    )

    telemetry = daemon.run(max_iterations=1)
    assert telemetry["cycles_completed"] == 1
    assert telemetry["total_discovered"] == 1
    assert len(telemetry["discovered_videos_sample"]) == 1
    assert telemetry["discovered_videos_sample"][0]["video_id"] == "v_daemon_1"
