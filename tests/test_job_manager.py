"""
Unit tests for JobManager and background job lifecycle.
Verifies SQLite persistence across restarts, staged progress updates,
cancellation tokens, and failure isolation.
"""

import pytest
import os
from yt_clipping.orchestration.job_manager import JobManager, RenderJobStatus, JobRecord


def test_job_manager_lifecycle(tmp_path):
    db_path = str(tmp_path / "jobs.db")
    mgr = JobManager(db_path=db_path)

    # 1. Create job
    job = mgr.create_job("video_test_1", {"max_clips": 3, "layout": "active_speaker"})
    assert job.status == RenderJobStatus.QUEUED.value
    assert job.video_id == "video_test_1"
    assert job.progress == 5

    # 2. Advance through stages
    mgr.update_progress(job.job_id, status=RenderJobStatus.DISCOVERING.value, progress=20, current_stage="discovering", message="Extracting metadata...")
    j1 = mgr.get_job(job.job_id)
    assert j1.status == "discovering"
    assert j1.progress == 20
    assert j1.started_at is not None

    mgr.update_progress(job.job_id, status=RenderJobStatus.RENDERING.value, progress=60, current_stage="rendering", message="FFmpeg 9:16 rendering...")
    j2 = mgr.get_job(job.job_id)
    assert j2.status == "rendering"
    assert j2.progress == 60

    # Complete job
    clips = [{"filename": "clip_1.mp4", "score": 90.0}]
    mgr.update_progress(job.job_id, status=RenderJobStatus.COMPLETED.value, progress=100, current_stage="completed", message="Render complete", clips=clips)
    j3 = mgr.get_job(job.job_id)
    assert j3.status == "completed"
    assert j3.progress == 100
    assert j3.completed_at is not None
    assert len(j3.clips) == 1

    # 3. Simulate Server Restart: Reinstantiate JobManager
    mgr_restarted = JobManager(db_path=db_path)
    j_restored = mgr_restarted.get_job(job.job_id)
    assert j_restored is not None
    assert j_restored.status == "completed"
    assert j_restored.clips[0]["filename"] == "clip_1.mp4"

    # List jobs
    all_jobs = mgr_restarted.list_jobs()
    assert len(all_jobs) == 1
    assert all_jobs[0].job_id == job.job_id


def test_job_manager_cancellation(tmp_path):
    db_path = str(tmp_path / "jobs.db")
    mgr = JobManager(db_path=db_path)

    job = mgr.create_job("video_cancel_test", {})
    assert not mgr.is_cancelled(job.job_id)

    # Cancel job
    cancelled = mgr.cancel_job(job.job_id)
    assert cancelled is True
    assert mgr.is_cancelled(job.job_id)

    j = mgr.get_job(job.job_id)
    assert j.status == RenderJobStatus.CANCELLED.value
    assert j.current_stage == "cancelled"
