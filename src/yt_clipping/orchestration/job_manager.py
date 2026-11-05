"""
Durable Background Job Management Service for Vertical Short Rendering.
Provides atomic state tracking, progress reporting, staged execution,
graceful job cancellation, failure isolation, and SQLite persistence.
"""

from __future__ import annotations
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from enum import Enum
import sqlite3
import json
import logging
import threading
import uuid
import os

logger = logging.getLogger(__name__)


class RenderJobStatus(str, Enum):
    QUEUED = "queued"
    DISCOVERING = "discovering"
    ANALYZING = "analyzing"
    GENERATING_CAPTION = "generating_caption"
    RENDERING = "rendering"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobRecord:
    job_id: str
    project_id: str
    video_id: str
    status: str = RenderJobStatus.QUEUED.value
    progress: int = 0
    current_stage: str = "queued"
    message: str = "Job queued..."
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    clips: List[Dict[str, Any]] = field(default_factory=list)
    request_params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> JobRecord:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class JobManager:
    """
    Durable Background Job Manager using SQLite.
    Survives server restarts and tracks active background thread cancellation tokens.
    """

    def __init__(self, db_path: str = "data/jobs.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._cancellation_events: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS render_jobs (
                            job_id TEXT PRIMARY KEY,
                            project_id TEXT NOT NULL,
                            video_id TEXT NOT NULL,
                            status TEXT NOT NULL,
                            progress INTEGER DEFAULT 0,
                            current_stage TEXT NOT NULL,
                            message TEXT,
                            error TEXT,
                            retry_count INTEGER DEFAULT 0,
                            max_retries INTEGER DEFAULT 3,
                            clips_json TEXT,
                            request_params_json TEXT,
                            created_at TEXT NOT NULL,
                            started_at TEXT,
                            completed_at TEXT
                        )
                        """
                    )
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_render_jobs_status ON render_jobs(status);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_render_jobs_video ON render_jobs(video_id);")
            finally:
                conn.close()

    def create_job(self, video_id: str, request_params: Dict[str, Any]) -> JobRecord:
        """Creates and stores a new queued render job."""
        job_id = f"job-{video_id}-{uuid.uuid4().hex[:6]}"
        project_id = f"proj_{video_id}"

        job = JobRecord(
            job_id=job_id,
            project_id=project_id,
            video_id=video_id,
            status=RenderJobStatus.QUEUED.value,
            progress=5,
            current_stage="queued",
            message="Render job initialized and queued.",
            request_params=request_params,
        )

        with self._lock:
            self._cancellation_events[job_id] = threading.Event()

        self.save_job(job)
        return job

    def save_job(self, job: JobRecord) -> None:
        """Persists job record to SQLite atomically."""
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO render_jobs (
                            job_id, project_id, video_id, status, progress, current_stage,
                            message, error, retry_count, max_retries, clips_json, request_params_json,
                            created_at, started_at, completed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(job_id) DO UPDATE SET
                            status=excluded.status,
                            progress=excluded.progress,
                            current_stage=excluded.current_stage,
                            message=excluded.message,
                            error=excluded.error,
                            retry_count=excluded.retry_count,
                            clips_json=excluded.clips_json,
                            started_at=excluded.started_at,
                            completed_at=excluded.completed_at
                        """,
                        (
                            job.job_id,
                            job.project_id,
                            job.video_id,
                            job.status,
                            job.progress,
                            job.current_stage,
                            job.message,
                            job.error,
                            job.retry_count,
                            job.max_retries,
                            json.dumps(job.clips),
                            json.dumps(job.request_params),
                            job.created_at,
                            job.started_at,
                            job.completed_at,
                        ),
                    )
            finally:
                conn.close()

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        """Retrieves job by job_id."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT job_id, project_id, video_id, status, progress, current_stage,
                       message, error, retry_count, max_retries, clips_json, request_params_json,
                       created_at, started_at, completed_at
                FROM render_jobs WHERE job_id = ?
                """,
                (job_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return JobRecord(
                job_id=row[0],
                project_id=row[1],
                video_id=row[2],
                status=row[3],
                progress=row[4],
                current_stage=row[5],
                message=row[6],
                error=row[7],
                retry_count=row[8],
                max_retries=row[9],
                clips=json.loads(row[10]) if row[10] else [],
                request_params=json.loads(row[11]) if row[11] else {},
                created_at=row[12],
                started_at=row[13],
                completed_at=row[14],
            )
        finally:
            conn.close()

    def update_progress(
        self,
        job_id: str,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        current_stage: Optional[str] = None,
        message: Optional[str] = None,
        error: Optional[str] = None,
        clips: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[JobRecord]:
        """Updates job progress and stage checkpoints."""
        job = self.get_job(job_id)
        if not job:
            return None

        # If job is already cancelled, ignore state overwrite unless setting cancelled
        if job.status == RenderJobStatus.CANCELLED.value and status != RenderJobStatus.CANCELLED.value:
            return job

        if status:
            job.status = status
            if status == RenderJobStatus.DISCOVERING.value and not job.started_at:
                job.started_at = datetime.now(timezone.utc).isoformat()
            elif status in (RenderJobStatus.COMPLETED.value, RenderJobStatus.FAILED.value, RenderJobStatus.CANCELLED.value):
                job.completed_at = datetime.now(timezone.utc).isoformat()

        if progress is not None:
            job.progress = max(0, min(100, progress))
        if current_stage:
            job.current_stage = current_stage
        if message:
            job.message = message
        if error is not None:
            job.error = error
        if clips is not None:
            job.clips = clips

        self.save_job(job)
        return job

    def cancel_job(self, job_id: str) -> bool:
        """Signals cancellation token and updates job status."""
        with self._lock:
            event = self._cancellation_events.get(job_id)
            if event:
                event.set()

        job = self.get_job(job_id)
        if not job:
            return False

        if job.status in (RenderJobStatus.COMPLETED.value, RenderJobStatus.FAILED.value):
            return False  # Already finished

        self.update_progress(
            job_id=job_id,
            status=RenderJobStatus.CANCELLED.value,
            progress=job.progress,
            current_stage="cancelled",
            message="Job cancelled by operator.",
        )
        return True

    def is_cancelled(self, job_id: str) -> bool:
        """Checks if cancellation has been requested for a job."""
        with self._lock:
            event = self._cancellation_events.get(job_id)
            if event and event.is_set():
                return True
        job = self.get_job(job_id)
        return bool(job and job.status == RenderJobStatus.CANCELLED.value)

    def list_jobs(self, limit: int = 50) -> List[JobRecord]:
        """Lists recent render jobs ordered by created_at descending."""
        jobs = []
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT job_id, project_id, video_id, status, progress, current_stage,
                       message, error, retry_count, max_retries, clips_json, request_params_json,
                       created_at, started_at, completed_at
                FROM render_jobs ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            )
            for row in cursor.fetchall():
                jobs.append(
                    JobRecord(
                        job_id=row[0],
                        project_id=row[1],
                        video_id=row[2],
                        status=row[3],
                        progress=row[4],
                        current_stage=row[5],
                        message=row[6],
                        error=row[7],
                        retry_count=row[8],
                        max_retries=row[9],
                        clips=json.loads(row[10]) if row[10] else [],
                        request_params=json.loads(row[11]) if row[11] else {},
                        created_at=row[12],
                        started_at=row[13],
                        completed_at=row[14],
                    )
                )
        finally:
            conn.close()
        return jobs
