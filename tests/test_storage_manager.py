"""
Tests for StorageManager Lifecycle and Retention Pruning (FEATURE-10).
"""

import os
import time
import pytest
from src.yt_clipping.config import AppConfig
from src.yt_clipping.orchestration.storage_manager import StorageManager


def test_storage_manager_dry_run_and_prune(tmp_path):
    temp_dir = tmp_path / "temp"
    heatmaps_dir = tmp_path / "heatmaps"
    assets_dir = tmp_path / "assets"
    rendered_dir = tmp_path / "rendered"

    temp_dir.mkdir()
    heatmaps_dir.mkdir()
    assets_dir.mkdir()
    rendered_dir.mkdir()

    cfg = AppConfig(
        temp_dir=str(temp_dir),
        heatmaps_dir=str(heatmaps_dir),
        assets_dir=str(assets_dir),
        output_dir=str(rendered_dir),
    )
    manager = StorageManager(cfg)

    # 1. Create an old temp file (modified 2 hours ago)
    old_temp = temp_dir / "old_chunk.ts"
    old_temp.write_text("dummy chunk data 1234567890")
    two_hours_ago = time.time() - 7200
    os.utime(str(old_temp), (two_hours_ago, two_hours_ago))

    # 2. Create an old heatmap file (modified 10 days ago)
    old_heatmap = heatmaps_dir / "old_heatmap.json"
    old_heatmap.write_text('{"video_id": "test"}')
    ten_days_ago = time.time() - (10 * 86400)
    os.utime(str(old_heatmap), (ten_days_ago, ten_days_ago))

    # 3. Create a precious asset file (should NEVER be pruned)
    asset_file = assets_dir / "valuable_video.mp4"
    asset_file.write_text("precious source media")
    os.utime(str(asset_file), (ten_days_ago, ten_days_ago))

    # Test Dry-Run: should identify reclaimable files without deleting
    report_dry = manager.run_cleanup(retention_days=7, dry_run=True)
    assert report_dry.dry_run is True
    assert report_dry.total_reclaimable_bytes > 0
    assert len(report_dry.items) == 2
    assert old_temp.exists()
    assert old_heatmap.exists()
    assert asset_file.exists()

    # Test Live Run: deletes eligible temp & heatmap, never touches asset
    report_live = manager.run_cleanup(retention_days=7, dry_run=False)
    assert report_live.dry_run is False
    assert not old_temp.exists()
    assert not old_heatmap.exists()
    assert asset_file.exists()  # Source asset preserved!


def test_storage_usage_breakdown(tmp_path):
    cfg = AppConfig(
        temp_dir=str(tmp_path / "temp"),
        heatmaps_dir=str(tmp_path / "heatmaps"),
        assets_dir=str(tmp_path / "assets"),
        output_dir=str(tmp_path / "rendered"),
        transcripts_dir=str(tmp_path / "transcripts"),
        autopost_inbox=str(tmp_path / "inbox"),
    )
    manager = StorageManager(cfg)
    usage = manager.get_storage_usage()
    assert "assets" in usage
    assert "transcripts" in usage
    assert "total_mb" in usage
