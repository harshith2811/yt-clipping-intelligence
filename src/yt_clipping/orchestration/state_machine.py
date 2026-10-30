"""
Durable Job State Machine and Crash-Resilient Checkpoint Journal.
Adapted from ClippyMe's checkpointing architecture.
Stores stage transitions, supports restart/recovery without reprocessing,
and maintains dead-letter queue records.
"""

from typing import Dict, Any, Optional, List
import sqlite3
import json
import os
from datetime import datetime, timezone
from ..contracts.models import ClipJob, JobStage, JobStatus


class JobJournal:
    """
    SQLite-backed durable job journal with WAL mode for concurrent safety.
    Guarantees that job transitions and checkpoints survive process restarts.
    """

    def __init__(self, db_path: str = "data/jobs.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS jobs (
                        job_id TEXT PRIMARY KEY,
                        video_id TEXT NOT NULL,
                        current_stage TEXT NOT NULL,
                        status TEXT NOT NULL,
                        retry_count INTEGER DEFAULT 0,
                        max_retries INTEGER DEFAULT 3,
                        data_json TEXT NOT NULL,
                        error_message TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_video_id ON jobs(video_id);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON jobs(status);")
        finally:
            conn.close()

    def save_job(self, job: ClipJob) -> None:
        """Inserts or updates job state atomically."""
        job.updated_at = datetime.now(timezone.utc).isoformat()
        data_json = json.dumps(job.to_dict())

        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO jobs (job_id, video_id, current_stage, status, retry_count, max_retries, data_json, error_message, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_id) DO UPDATE SET
                        current_stage=excluded.current_stage,
                        status=excluded.status,
                        retry_count=excluded.retry_count,
                        data_json=excluded.data_json,
                        error_message=excluded.error_message,
                        updated_at=excluded.updated_at
                    """,
                    (
                        job.job_id,
                        job.video_id,
                        job.current_stage.value,
                        job.status.value,
                        job.retry_count,
                        job.max_retries,
                        data_json,
                        job.error_message,
                        job.created_at,
                        job.updated_at,
                    ),
                )
        finally:
            conn.close()

    def get_job(self, job_id: str) -> Optional[ClipJob]:
        """Retrieves a job by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT data_json FROM jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            if row:
                data = json.loads(row[0])
                return ClipJob.from_dict(data)
            return None
        finally:
            conn.close()

    def find_by_video_id(self, video_id: str) -> List[ClipJob]:
        """Retrieves all jobs associated with a video ID."""
        jobs: List[ClipJob] = []
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT data_json FROM jobs WHERE video_id = ? ORDER BY created_at DESC", (video_id,))
            for row in cursor.fetchall():
                jobs.append(ClipJob.from_dict(json.loads(row[0])))
            return jobs
        finally:
            conn.close()

    def list_jobs(self, status: Optional[JobStatus] = None, limit: int = 50) -> List[ClipJob]:
        """Lists jobs optionally filtered by status."""
        jobs: List[ClipJob] = []
        conn = self._get_connection()
        try:
            if status:
                cursor = conn.execute(
                    "SELECT data_json FROM jobs WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                    (status.value, limit),
                )
            else:
                cursor = conn.execute(
                    "SELECT data_json FROM jobs ORDER BY updated_at DESC LIMIT ?", (limit,)
                )
            for row in cursor.fetchall():
                jobs.append(ClipJob.from_dict(json.loads(row[0])))
            return jobs
        finally:
            conn.close()

    def record_stage_checkpoint(
        self, job: ClipJob, stage: JobStage, data: Dict[str, Any]
    ) -> None:
        """Records a completed stage checkpoint and persists to disk."""
        job.record_checkpoint(stage, data)
        self.save_job(job)

    def mark_failed(self, job: ClipJob, error: str) -> None:
        """Marks a job failed and stores diagnostic error message."""
        job.status = JobStatus.FAILED
        job.error_message = error
        job.current_stage = JobStage.FAILED
        self.save_job(job)
