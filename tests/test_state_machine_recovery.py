"""
Tests for state machine checkpoint journaling, crash recovery, and status transitions.
"""

import pytest
from src.yt_clipping.contracts.models import ClipJob, JobStage, JobStatus
from src.yt_clipping.orchestration.state_machine import JobJournal


def test_job_journal_persists_checkpoints_and_recovers(tmp_path):
    db_file = str(tmp_path / "jobs.db")
    journal = JobJournal(db_file)

    job = ClipJob(
        job_id="job_recovery_100",
        video_id="vid_recovery_100",
        current_stage=JobStage.DISCOVERED,
        status=JobStatus.IN_PROGRESS,
    )
    journal.save_job(job)

    # Record checkpoints
    journal.record_stage_checkpoint(job, JobStage.RIGHTS_CHECKED, {"verified": True})
    journal.record_stage_checkpoint(job, JobStage.TRANSCRIBED, {"segments_count": 8})

    # Simulate process termination and re-instantiation of journal
    new_journal_instance = JobJournal(db_file)
    recovered = new_journal_instance.get_job("job_recovery_100")

    assert recovered is not None
    assert recovered.video_id == "vid_recovery_100"
    assert recovered.current_stage == JobStage.TRANSCRIBED
    assert JobStage.RIGHTS_CHECKED.value in recovered.checkpoints
    assert JobStage.TRANSCRIBED.value in recovered.checkpoints
    assert recovered.checkpoints[JobStage.TRANSCRIBED.value]["data"]["segments_count"] == 8


def test_job_journal_mark_failed(tmp_path):
    db_file = str(tmp_path / "jobs.db")
    journal = JobJournal(db_file)

    job = ClipJob(
        job_id="job_fail_1",
        video_id="vid_fail_1",
        current_stage=JobStage.RENDERED,
        status=JobStatus.IN_PROGRESS,
    )
    journal.save_job(job)

    journal.mark_failed(job, "Subprocess exit code 1: OOM")
    recovered = journal.get_job("job_fail_1")

    assert recovered.status == JobStatus.FAILED
    assert recovered.current_stage == JobStage.FAILED
    assert "OOM" in recovered.error_message


def test_stage_resumption_invalidation_on_missing_artifact(tmp_path):
    from src.yt_clipping.orchestration.pipeline import ClippingPipeline
    from src.yt_clipping.contracts.models import RenderedClip

    db_file = str(tmp_path / "jobs.db")
    journal = JobJournal(db_file)

    # Job claims to have completed RENDERED stage, but file does not exist
    missing_file = str(tmp_path / "nonexistent_clip.mp4")
    from src.yt_clipping.contracts.models import RightsManifest, RightsBasis, RightsStatus
    manifest = RightsManifest(
        rights_id="r1", video_id="vid_resume", basis=RightsBasis.OPERATOR_ASSET, status=RightsStatus.VERIFIED, owner_name="Owner"
    )
    job = ClipJob(
        job_id="job_resume_test",
        video_id="vid_resume",
        current_stage=JobStage.RENDERED,
        status=JobStatus.IN_PROGRESS,
        rights_manifest=manifest,
        checkpoints={
            JobStage.RIGHTS_CHECKED.value: {"timestamp": "2026-01-01T00:00:00Z", "data": {}},
            JobStage.ASSET_INGESTED.value: {"timestamp": "2026-01-01T00:00:00Z", "data": {"asset_path": str(tmp_path / "source.mp4")}},
            JobStage.RENDERED.value: {"timestamp": "2026-01-01T00:00:00Z", "data": {}},
        },
        rendered_clip=RenderedClip(
            clip_id="c_missing",
            job_id="job_resume_test",
            candidate_id="cand_1",
            file_path=missing_file,
            file_hash="hash",
            duration_seconds=30.0,
            width=1080,
            height=1920,
            manifest_path="manifest.json",
            rendered_at="2026-01-01T00:00:00Z",
        ),
    )

    # Create dummy source so asset ingestion stage is valid
    with open(str(tmp_path / "source.mp4"), "w") as f:
        f.write("content")

    pipeline = ClippingPipeline(
        rights_policy=None,
        asset_provider=None,
        transcriber=None,
        detector=None,
        scorer=None,
        renderer=None,
        verifier=None,
        publisher=None,
        journal=journal,
        output_dir=str(tmp_path / "out"),
    )

    # Reconcile checkpoints
    pipeline.reconcile_job_checkpoints(job)

    # RENDERED checkpoint must be invalidated because the rendered file does not exist on disk
    assert JobStage.RENDERED.value not in job.checkpoints
    assert job.rendered_clip is None
    # Prior stages remain valid
    assert JobStage.RIGHTS_CHECKED.value in job.checkpoints
    assert JobStage.ASSET_INGESTED.value in job.checkpoints
