"""
Tests for 24/7 Cloud Worker, Docker Configuration, and Model Prebake Suite.
Verifies prebake scripts, entrypoint dispatch, queue worker execution, and compose specs.
"""

import pytest
import os
import threading
import time
from yt_clipping.orchestration.queue import JobQueue, JobPriority
from yt_clipping.contracts.models import ClipJob, JobStage, JobStatus
from yt_clipping.scripts.prebake_models import ensure_yunet_model


def test_docker_entrypoint_file_exists():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    entrypoint_path = os.path.join(root_dir, "docker-entrypoint.sh")
    assert os.path.exists(entrypoint_path), "docker-entrypoint.sh must exist in repository root"
    content = open(entrypoint_path, "r", encoding="utf-8").read()
    assert "daemon)" in content
    assert "worker)" in content
    assert "mcp)" in content


def test_dockerfiles_and_compose_specs():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    dockerfile_path = os.path.join(root_dir, "Dockerfile")
    compose_path = os.path.join(root_dir, "docker-compose.yml")
    compose_gpu_path = os.path.join(root_dir, "docker-compose.gpu.yml")

    assert os.path.exists(dockerfile_path)
    assert os.path.exists(compose_path)
    assert os.path.exists(compose_gpu_path)

    df_content = open(dockerfile_path, "r", encoding="utf-8").read()
    assert "nvidia/cuda" in df_content or "python:" in df_content
    assert "prebake_models" in df_content
    assert "HEALTHCHECK" in df_content

    gpu_content = open(compose_gpu_path, "r", encoding="utf-8").read()
    assert "capabilities: [gpu, video, compute]" in gpu_content


def test_model_prebake_yunet_verification():
    path = ensure_yunet_model()
    assert os.path.exists(path)
    assert os.path.getsize(path) > 100_000


def test_queue_run_worker_execution(tmp_path):
    db_file = tmp_path / "test_worker_jobs.db"
    queue = JobQueue(str(db_file))

    # Enqueue a dummy job
    job_id = queue.enqueue(
        video_id="test_worker_vid_01",
        priority=JobPriority.HIGH,
        initial_stage=JobStage.DISCOVERED,
    )
    assert job_id is not None

    processed_jobs = []

    def mock_runner(job):
        processed_jobs.append(job.job_id)
        # queue.mark_completed is handled automatically by run_worker

    # Run worker for max 1 job
    count = queue.run_worker(
        pipeline_runner=mock_runner,
        poll_interval=0.05,
        max_jobs=1,
    )

    assert count == 1
    assert len(processed_jobs) == 1
    assert processed_jobs[0] == job_id
