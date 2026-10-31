"""
Durable Priority Queue and Job Scheduler Service (FEATURE-07).
Manages prioritized job execution, worker concurrency, and bounded retry policies.
Persisted in SQLite for resilience across process crashes.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
import json
import sqlite3
import os
from datetime import datetime, timezone

from .db import DatabaseManager
from ..contracts.models import ClipJob, JobStage, JobStatus


class JobPriority(int, Enum):
    LOW = 1
    NORMAL = 5
    HIGH = 10
    CRITICAL = 20


@dataclass
class QueueItem:
    job_id: str
    video_id: str
    priority: int
    status: str
    retry_count: int
    max_retries: int
    created_at: str
    updated_at: str
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "video_id": self.video_id,
            "priority": self.priority,
            "status": self.status,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error_message": self.error_message,
        }


class JobQueue:
    """
    SQLite-backed priority job queue with concurrency leasing and retry tracking.
    """

    def __init__(self, db_path: str = "data/jobs.db"):
        self.db = DatabaseManager(db_path)
        self._ensure_priority_column()

    def _ensure_priority_column(self) -> None:
        """Adds priority column to jobs table if not present."""
        conn = self.db.get_connection()
        try:
            with conn:
                try:
                    conn.execute("ALTER TABLE jobs ADD COLUMN priority INTEGER DEFAULT 5")
                except sqlite3.OperationalError:
                    pass  # Column already exists
        finally:
            conn.close()

    def enqueue(
        self,
        video_id: str,
        priority: JobPriority = JobPriority.NORMAL,
        job_id: Optional[str] = None,
        max_retries: int = 3,
        metadata: Optional[Dict[str, Any]] = None,
        initial_stage: Optional[Any] = None,
    ) -> str:
        """Enqueues a new clipping job."""
        actual_job_id = job_id or f"job-{video_id}-{int(datetime.now(timezone.utc).timestamp())}"
        now = datetime.now(timezone.utc).isoformat()
        stage = initial_stage if isinstance(initial_stage, JobStage) else JobStage.DISCOVERED
        initial_job = ClipJob(
            job_id=actual_job_id,
            video_id=video_id,
            current_stage=stage,
            status=JobStatus.PENDING,
            max_retries=max_retries,
        )
        if metadata:
            initial_job.record_checkpoint(stage, metadata)
        data_json = json.dumps(initial_job.to_dict())

        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO jobs (
                        job_id, video_id, current_stage, status, priority, retry_count, max_retries, data_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                    ON CONFLICT(job_id) DO UPDATE SET
                        priority=excluded.priority,
                        status=excluded.status,
                        updated_at=excluded.updated_at
                    """,
                    (
                        actual_job_id,
                        video_id,
                        stage.value,
                        JobStatus.PENDING.value,
                        int(priority),
                        max_retries,
                        data_json,
                        now,
                        now,
                    ),
                )
            return actual_job_id
        finally:
            conn.close()

    # Alias for API compatibility
    enqueue_job = enqueue

    def dequeue(self) -> Optional[ClipJob]:
        """
        Atomically leases the highest-priority pending job.
        Orders by priority DESC, then created_at ASC.
        """
        conn = self.db.get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    SELECT job_id, data_json, retry_count, max_retries
                    FROM jobs
                    WHERE status = ?
                    ORDER BY priority DESC, created_at ASC
                    LIMIT 1
                    """,
                    (JobStatus.PENDING.value,),
                )
                row = cursor.fetchone()
                if not row:
                    return None

                job_id, data_json, retry_count, max_retries = row
                now = datetime.now(timezone.utc).isoformat()

                # Mark as IN_PROGRESS
                conn.execute(
                    "UPDATE jobs SET status = ?, updated_at = ? WHERE job_id = ?",
                    (JobStatus.IN_PROGRESS.value, now, job_id),
                )

                job = ClipJob.from_dict(json.loads(data_json))
                job.status = JobStatus.IN_PROGRESS
                return job
        finally:
            conn.close()

    def mark_completed(self, job_id: str) -> None:
        """Marks a job as succeeded."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    "UPDATE jobs SET status = ?, current_stage = ?, updated_at = ? WHERE job_id = ?",
                    (JobStatus.SUCCEEDED.value, JobStage.HANDED_OFF.value, now, job_id),
                )
        finally:
            conn.close()

    def mark_failed_or_retry(self, job_id: str, error_message: str) -> bool:
        """
        Increments retry count. If retries remain, returns to PENDING.
        If retries exhausted, marks as FAILED.
        Returns True if requeued for retry, False if marked failed permanently.
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = self.db.get_connection()
        try:
            with conn:
                cursor = conn.execute("SELECT retry_count, max_retries FROM jobs WHERE job_id = ?", (job_id,))
                row = cursor.fetchone()
                if not row:
                    return False

                retry_count, max_retries = row
                new_retry = retry_count + 1

                if new_retry < max_retries:
                    # Requeue for retry
                    conn.execute(
                        """
                        UPDATE jobs SET
                            status = ?,
                            retry_count = ?,
                            error_message = ?,
                            updated_at = ?
                        WHERE job_id = ?
                        """,
                        (JobStatus.PENDING.value, new_retry, f"Retry {new_retry}/{max_retries}: {error_message}", now, job_id),
                    )
                    return True
                else:
                    # Mark permanently failed
                    conn.execute(
                        """
                        UPDATE jobs SET
                            status = ?,
                            current_stage = ?,
                            retry_count = ?,
                            error_message = ?,
                            updated_at = ?
                        WHERE job_id = ?
                        """,
                        (JobStatus.FAILED.value, JobStage.FAILED.value, new_retry, error_message, now, job_id),
                    )
                    return False
        finally:
            conn.close()

    def get_status(self) -> Dict[str, Any]:
        """Provides status breakdown of all jobs in the queue."""
        conn = self.db.get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT status, COUNT(*)
                FROM jobs
                GROUP BY status
                """
            )
            counts_by_status = {r[0]: r[1] for r in cursor.fetchall()}

            cursor = conn.execute(
                """
                SELECT current_stage, COUNT(*)
                FROM jobs
                GROUP BY current_stage
                """
            )
            counts_by_stage = {r[0]: r[1] for r in cursor.fetchall()}

            cursor = conn.execute(
                """
                SELECT job_id, video_id, COALESCE(priority, 5), status, retry_count, max_retries, created_at, updated_at, error_message
                FROM jobs
                ORDER BY updated_at DESC
                LIMIT 10
                """
            )
            recent_items = [
                QueueItem(
                    job_id=r[0],
                    video_id=r[1],
                    priority=r[2],
                    status=r[3],
                    retry_count=r[4],
                    max_retries=r[5],
                    created_at=r[6],
                    updated_at=r[7],
                    error_message=r[8],
                ).to_dict()
                for r in cursor.fetchall()
            ]

            return {
                "total_jobs": sum(counts_by_status.values()),
                "counts_by_status": counts_by_status,
                "counts_by_stage": counts_by_stage,
                "recent_jobs": recent_items,
            }
        finally:
            conn.close()
