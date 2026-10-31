"""
Tests for JobQueue Priority Scheduling and Retry Policies (FEATURE-07).
"""

import pytest
from src.yt_clipping.orchestration.queue import JobQueue, JobPriority
from src.yt_clipping.contracts.models import JobStatus


def test_job_queue_priority_ordering(tmp_path):
    db_file = str(tmp_path / "jobs.db")
    queue = JobQueue(db_file)

    # Enqueue low priority job first
    id_low = queue.enqueue("vid_low", priority=JobPriority.LOW)
    # Enqueue high priority job second
    id_high = queue.enqueue("vid_high", priority=JobPriority.HIGH)
    # Enqueue normal priority job third
    id_normal = queue.enqueue("vid_normal", priority=JobPriority.NORMAL)

    # First dequeue should return the HIGH priority job
    job1 = queue.dequeue()
    assert job1 is not None
    assert job1.job_id == id_high
    assert job1.status == JobStatus.IN_PROGRESS

    # Second dequeue should return NORMAL priority job
    job2 = queue.dequeue()
    assert job2 is not None
    assert job2.job_id == id_normal

    # Third dequeue should return LOW priority job
    job3 = queue.dequeue()
    assert job3 is not None
    assert job3.job_id == id_low

    # Empty queue should return None
    assert queue.dequeue() is None


def test_job_queue_retry_and_exhaustion(tmp_path):
    db_file = str(tmp_path / "jobs.db")
    queue = JobQueue(db_file)

    job_id = queue.enqueue("vid_retry", max_retries=2)
    job = queue.dequeue()
    assert job is not None

    # First failure -> should be requeued (retry 1 < 2)
    requeued = queue.mark_failed_or_retry(job_id, "Temporary network timeout")
    assert requeued is True

    # Job is available for dequeue again
    job_re = queue.dequeue()
    assert job_re is not None
    assert job_re.job_id == job_id

    # Second failure -> retries exhausted (retry 2 >= 2)
    requeued_second = queue.mark_failed_or_retry(job_id, "Fatal network failure")
    assert requeued_second is False

    # Status should reflect failure
    status = queue.get_status()
    assert status["counts_by_status"].get(JobStatus.FAILED.value, 0) == 1
