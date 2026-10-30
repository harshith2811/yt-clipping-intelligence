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
