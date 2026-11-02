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


def test_cli_run_help_exposes_enhancement_flags():
    """Verify that 'yt-clip run --help' exits with code 0 and exposes enhancement flags."""
    import sys
    import subprocess
    res = subprocess.run(
        [sys.executable, "-m", "yt_clipping.cli.master_cli", "run", "--help"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "--enable-deadair-pruning" in res.stdout
    assert "--enable-broll" in res.stdout
    assert "--broll-assets-dir" in res.stdout


def test_cli_parser_run_subcommand_arguments():
    """Verify that the master CLI parser accurately parses all documented run subcommand flags."""
    from src.yt_clipping.cli.master_cli import build_parser
    parser = build_parser()
    args = parser.parse_args([
        "run",
        "--video-id", "rsOiZE19RVo",
        "--layout", "active_speaker",
        "--enable-deadair-pruning",
        "--enable-broll",
        "--broll-assets-dir", "custom/assets/broll",
    ])
    assert args.video_id == "rsOiZE19RVo"
    assert args.layout == "active_speaker"
    assert args.enable_deadair_pruning is True
    assert args.enable_broll is True
    assert args.broll_assets_dir == "custom/assets/broll"


def test_cli_cmd_run_forwards_enhancement_flags(monkeypatch):
    """Verify that cmd_run extracts and forwards enhancement flags to pipeline.process_video."""
    from unittest.mock import MagicMock
    from src.yt_clipping.cli.master_cli import cmd_run
    from src.yt_clipping.contracts.models import ClipJob, JobStage, JobStatus

    captured_kwargs = {}

    class FakePipeline:
        def process_video(self, **kwargs):
            captured_kwargs.update(kwargs)
            fake_job = MagicMock(spec=ClipJob)
            fake_job.job_id = "test-job-remed"
            fake_job.current_stage = JobStage.RENDERED
            fake_job.status = JobStatus.SUCCEEDED
            fake_job.candidate = None
            fake_job.rendered_clip = None
            fake_job.qa_report = None
            fake_job.handoff_receipt = None
            fake_job.checkpoints = {}
            return fake_job

    monkeypatch.setattr("src.yt_clipping.cli.master_cli.build_pipeline", lambda **k: FakePipeline())

    args = argparse.Namespace(
        video_id="rsOiZE19RVo",
        video_id_pos=None,
        min_duration=15.0,
        max_duration=60.0,
        dry_run=True,
        layout="active_speaker",
        subtitle_preset="hormozi",
        threshold=65.0,
        gpu=False,
        vcodec="libx264",
        output_dir="data/rendered_clips",
        enable_deadair_pruning=True,
        enable_broll=True,
        broll_assets_dir="custom/assets/broll",
    )
    cmd_run(args)

    assert captured_kwargs.get("enable_deadair_pruning") is True
    assert captured_kwargs.get("enable_broll") is True
    assert captured_kwargs.get("broll_assets_dir") == "custom/assets/broll"


def test_cli_cmd_run_forwards_cta_and_polish_profile(monkeypatch):
    """Verify that cmd_run configures RenderProfile with CTA and polish parameters."""
    from unittest.mock import MagicMock
    from src.yt_clipping.cli.master_cli import cmd_run
    from src.yt_clipping.contracts.models import ClipJob, JobStage, JobStatus

    captured_profile = None

    class FakePipeline:
        def process_video(self, **kwargs):
            nonlocal captured_profile
            captured_profile = kwargs.get("profile")
            fake_job = MagicMock(spec=ClipJob)
            fake_job.job_id = "test-job-cta"
            fake_job.current_stage = JobStage.RENDERED
            fake_job.status = JobStatus.SUCCEEDED
            fake_job.candidate = None
            fake_job.rendered_clip = None
            fake_job.qa_report = None
            fake_job.handoff_receipt = None
            fake_job.checkpoints = {}
            return fake_job

    monkeypatch.setattr("src.yt_clipping.cli.master_cli.build_pipeline", lambda **k: FakePipeline())

    args = argparse.Namespace(
        video_id="test_cta_vid",
        video_id_pos=None,
        min_duration=15.0,
        max_duration=60.0,
        dry_run=True,
        layout="blur_background",
        subtitle_preset="neon_cyber",
        threshold=65.0,
        gpu=False,
        vcodec="libx264",
        output_dir="data/rendered_clips",
        enable_deadair_pruning=False,
        enable_broll=False,
        broll_assets_dir=None,
        enable_cta=True,
        cta_text="Subscribe now",
        cta_timing="intro",
        cta_style="neon_banner",
        enable_polish=True,
    )
    cmd_run(args)

    assert captured_profile is not None
    assert captured_profile.enable_cta is True
    assert captured_profile.cta_text == "Subscribe now"
    assert captured_profile.cta_timing == "intro"
    assert captured_profile.cta_style == "neon_banner"
    assert captured_profile.enable_pacing_polish is True


def test_cli_podcast_command(monkeypatch):
    """Verify that cmd_podcast instantiates PodcastShortMaker and calls create_short."""
    from unittest.mock import MagicMock
    from src.yt_clipping.cli.master_cli import cmd_podcast

    captured_calls = {}

    class FakeMaker:
        def __init__(self, config=None):
            captured_calls["config"] = config

        def create_short(self, **kwargs):
            captured_calls["args"] = kwargs
            return {
                "output_path": kwargs.get("output_path"),
                "shots_detected": 2,
                "shot_breakdown": ["WIDE", "CLOSEUP"],
                "file_size_bytes": 1024 * 1024,
            }

    monkeypatch.setattr("src.yt_clipping.podcast.pipeline.PodcastShortMaker", FakeMaker)

    args = argparse.Namespace(
        source="podcast_src.mp4",
        out="podcast_out.mp4",
        start=5.0,
        duration=25.0,
        mode="hybrid",
        host_side="right",
        preview=True,
        no_subtitles=True,
        divider_thickness=8,
        divider_color="0x303030",
        enable_cta=True,
        cta_text="Subscribe to the podcast",
        cta_timing="persistent",
        cta_style="minimal",
    )
    cmd_podcast(args)

    assert captured_calls["config"].split_mode == "hybrid"
    assert captured_calls["config"].host_side == "right"
    assert captured_calls["config"].preview is True
    assert captured_calls["config"].burn_subtitles is False
    assert captured_calls["config"].divider_thickness == 8
    assert captured_calls["config"].divider_color == "0x303030"
    assert captured_calls["config"].enable_cta is True
    assert captured_calls["config"].cta_text == "Subscribe to the podcast"
    assert captured_calls["config"].cta_timing == "persistent"
    assert captured_calls["config"].cta_style == "minimal"
    assert captured_calls["args"]["video_path"] == "podcast_src.mp4"
    assert captured_calls["args"]["start_sec"] == 5.0
    assert captured_calls["args"]["duration_sec"] == 25.0
    assert captured_calls["args"]["output_path"] == "podcast_out.mp4"
