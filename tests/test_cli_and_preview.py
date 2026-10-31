"""
Tests for Master CLI commands and candidate preview functionality.
"""

import pytest
import os
import json
from src.yt_clipping.contracts.models import (
    RightsManifest,
    RightsBasis,
    RightsStatus,
    RenderProfile,
)
from src.yt_clipping.cli.master_cli import build_pipeline, cmd_preview, cmd_discovery
from src.yt_clipping.orchestration.pipeline import ClippingPipeline
from src.yt_clipping.contracts.interfaces import RightsPolicyViolationError
import argparse


def test_pipeline_get_candidates_without_rendering(tmp_path):
    ledger_file = tmp_path / "rights.json"
    assets_dir = tmp_path / "assets"
    transcripts_dir = tmp_path / "transcripts"
    output_dir = tmp_path / "rendered"
    inbox_dir = tmp_path / "inbox"
    db_file = tmp_path / "jobs.db"

    assets_dir.mkdir()
    transcripts_dir.mkdir()
    output_dir.mkdir()
    inbox_dir.mkdir()

    video_id = "test_prev_vid"

    # Setup valid rights
    manifest = RightsManifest(
        rights_id=f"rights-{video_id}",
        video_id=video_id,
        basis=RightsBasis.OPERATOR_ASSET,
        status=RightsStatus.VERIFIED,
        owner_name="Test Owner",
    )
    with open(ledger_file, "w", encoding="utf-8") as f:
        json.dump([manifest.to_dict()], f)

    # Setup mock asset
    asset_file = assets_dir / f"{video_id}.mp4"
    asset_file.write_text("ftypisom mock mp4 data content")

    pipeline = build_pipeline(
        ledger_path=str(ledger_file),
        assets_dir=str(assets_dir),
        transcripts_dir=str(transcripts_dir),
        output_dir=str(output_dir),
        autopost_inbox=str(inbox_dir),
        db_path=str(db_file),
    )

    candidates = pipeline.get_candidates(video_id)
    assert len(candidates) > 0
    top = candidates[0]
    assert top.score > 0
    assert top.breakdown.hook_score >= 0.0
    assert top.duration_seconds > 0

    # Ensure no render files or handoff files were created
    assert len(list(output_dir.glob("*.mp4"))) == 0
    assert len(list(inbox_dir.glob("*.json"))) == 0


def test_pipeline_get_candidates_blocks_unauthorized(tmp_path):
    ledger_file = tmp_path / "rights.json"
    with open(ledger_file, "w", encoding="utf-8") as f:
        json.dump({}, f)

    pipeline = build_pipeline(ledger_path=str(ledger_file))
    with pytest.raises(RightsPolicyViolationError):
        pipeline.get_candidates("unregistered_vid")


def test_cli_doctor_and_config(tmp_path, capsys):
    from src.yt_clipping.cli.master_cli import cmd_doctor, cmd_config_validate, cmd_quota
    db_file = str(tmp_path / "jobs.db")
    
    # Test doctor
    args_doc = argparse.Namespace(db=db_file)
    cmd_doctor(args_doc)
    captured = capsys.readouterr()
    assert "Environment Doctor" in captured.out
    assert "Python Version" in captured.out

    # Test config validate
    args_cfg = argparse.Namespace()
    cmd_config_validate(args_cfg)
    captured_cfg = capsys.readouterr()
    assert "Active Configuration" in captured_cfg.out

    # Test quota
    args_quota = argparse.Namespace(db=db_file)
    cmd_quota(args_quota)
    captured_q = capsys.readouterr()
    assert "Quota Governor Status" in captured_q.out


def test_cli_channels_and_queue(tmp_path, capsys):
    from src.yt_clipping.cli.master_cli import cmd_channels, cmd_queue
    db_file = str(tmp_path / "jobs.db")

    # Add channel
    args_add = argparse.Namespace(
        channel_cmd="add",
        channel_id="UC_CLI_TEST",
        name="CLI Test Channel",
        handle="@cli_test",
        url="https://youtube.com/@cli_test",
        baseline=12000.0,
        db=db_file,
    )
    cmd_channels(args_add)
    cap = capsys.readouterr()
    assert "Added/Updated monitored channel" in cap.out

    # List channels
    args_list = argparse.Namespace(channel_cmd="list", all=False, db=db_file)
    cmd_channels(args_list)
    cap_list = capsys.readouterr()
    assert "CLI Test Channel" in cap_list.out

    # Queue status
    args_q = argparse.Namespace(queue_cmd="status", db=db_file)
    cmd_queue(args_q)
    cap_q = capsys.readouterr()
    assert "Job Queue Status" in cap_q.out
