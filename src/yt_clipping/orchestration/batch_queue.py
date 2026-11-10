"""
Overnight Multi-Video Batch Queue & Autonomous Processing Engine.
Manages sequential, resilient execution of multiple long-form videos
through the end-to-end clipping and rendering pipeline with failure isolation,
live progress tracking, and transactional SQLite + JSON persistence.
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
import time

logger = logging.getLogger(__name__)


class BatchItemStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class BatchStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class BatchVideoItem:
    video_id: str
    url: str
    title: str
    channel_name: str
    channel_subs: str
    thumbnail_url: str
    duration_seconds: float = 0.0
    status: BatchItemStatus = BatchItemStatus.QUEUED
    job_id: Optional[str] = None
    clips_count: int = 0
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value if isinstance(self.status, BatchItemStatus) else self.status
        return d


@dataclass
class BatchSession:
    batch_id: str
    name: str = "Overnight 10M+ Trending Batch"
    status: BatchStatus = BatchStatus.RUNNING
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    total_videos: int = 0
    completed_videos: int = 0
    failed_videos: int = 0
    total_clips_generated: int = 0
    current_index: int = 0
    current_video_id: Optional[str] = None
    current_stage: str = "initializing"
    current_progress: int = 0
    render_config: Dict[str, Any] = field(default_factory=lambda: {
        "max_clips": 3,
        "layout": "active_speaker",
        "subtitle_preset": "hormozi",
        "enable_polish": True,
        "enable_outro": True,
        "gpu": True,
    })
    items: List[BatchVideoItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value if isinstance(self.status, BatchStatus) else self.status
        d["items"] = [item.to_dict() for item in self.items]
        return d


class BatchQueueManager:
    """
    Manages overnight sequential batch runs of 10+ videos from 10M+ trending channels.
    Ensures safe GPU memory utilization by enforcing serial 1-at-a-time rendering,
    graceful per-video error containment, and persistent batch records.
    """

    def __init__(self, storage_dir: str = "data", db_path: Optional[str] = None):
        self.storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)
        self.db_path = db_path or os.path.join(storage_dir, "dashboard.db")
        self.json_path = os.path.join(storage_dir, "batch_sessions.json")
        self._lock = threading.Lock()
        self._active_worker_threads: Dict[str, threading.Thread] = {}
        self._cancelled_batches: set[str] = set()
        self._paused_batches: set[str] = set()

        self._init_db()

    def _init_db(self) -> None:
        """Initializes batch_sessions and batch_items tables."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS batch_sessions (
                        batch_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        started_at TEXT,
                        completed_at TEXT,
                        total_videos INTEGER DEFAULT 0,
                        completed_videos INTEGER DEFAULT 0,
                        failed_videos INTEGER DEFAULT 0,
                        total_clips_generated INTEGER DEFAULT 0,
                        current_index INTEGER DEFAULT 0,
                        current_video_id TEXT,
                        current_stage TEXT,
                        current_progress INTEGER DEFAULT 0,
                        render_config_json TEXT,
                        items_json TEXT
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.warning(f"BatchQueueManager DB initialization warning: {e}")

    def create_batch(
        self,
        videos: List[Dict[str, Any]],
        render_config: Optional[Dict[str, Any]] = None,
        name: str = "Overnight 10M+ Trending Run",
    ) -> BatchSession:
        """Creates and persists a new multi-video batch queue."""
        with self._lock:
            batch_id = f"batch_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
            items: List[BatchVideoItem] = []

            for v in videos:
                vid = v.get("video_id") or ""
                url = v.get("url") or f"https://www.youtube.com/watch?v={vid}"
                title = v.get("title") or "YouTube Video"
                channel_name = v.get("channel_name") or v.get("channel_title") or "10M+ Creator"
                channel_subs = v.get("channel_subscribers_formatted") or "10M+"
                thumb = v.get("thumbnail_url") or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
                dur = float(v.get("duration_seconds") or 0.0)

                items.append(BatchVideoItem(
                    video_id=vid,
                    url=url,
                    title=title,
                    channel_name=channel_name,
                    channel_subs=channel_subs,
                    thumbnail_url=thumb,
                    duration_seconds=dur,
                    status=BatchItemStatus.QUEUED,
                ))

            config = render_config or {
                "max_clips": 3,
                "layout": "active_speaker",
                "subtitle_preset": "hormozi",
                "enable_polish": True,
                "enable_outro": True,
                "gpu": True,
            }

            session = BatchSession(
                batch_id=batch_id,
                name=name,
                status=BatchStatus.RUNNING,
                total_videos=len(items),
                render_config=config,
                items=items,
            )

            self._save_session(session)
            return session

    def _save_session(self, session: BatchSession) -> None:
        """Persists session to SQLite and JSON ledger."""
        data = session.to_dict()

        # 1. Update SQLite
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO batch_sessions (
                        batch_id, name, status, created_at, started_at, completed_at,
                        total_videos, completed_videos, failed_videos, total_clips_generated,
                        current_index, current_video_id, current_stage, current_progress,
                        render_config_json, items_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    session.batch_id,
                    session.name,
                    session.status.value if isinstance(session.status, BatchStatus) else session.status,
                    session.created_at,
                    session.started_at,
                    session.completed_at,
                    session.total_videos,
                    session.completed_videos,
                    session.failed_videos,
                    session.total_clips_generated,
                    session.current_index,
                    session.current_video_id,
                    session.current_stage,
                    session.current_progress,
                    json.dumps(session.render_config),
                    json.dumps(data.get("items", [])),
                ))
                conn.commit()
        except Exception as e:
            logger.warning(f"Error persisting batch session to DB: {e}")

        # 2. Update JSON cache
        try:
            all_sessions: Dict[str, Any] = {}
            if os.path.exists(self.json_path):
                try:
                    with open(self.json_path, "r", encoding="utf-8") as f:
                        all_sessions = json.load(f)
                except Exception:
                    all_sessions = {}
            all_sessions[session.batch_id] = data
            with open(self.json_path, "w", encoding="utf-8") as f:
                json.dump(all_sessions, f, indent=2)
        except Exception as e:
            logger.warning(f"Error persisting batch session to JSON: {e}")

    def get_batch(self, batch_id: str) -> Optional[BatchSession]:
        """Loads batch session by ID."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM batch_sessions WHERE batch_id = ?", (batch_id,))
                row = cursor.fetchone()
                if row:
                    return self._row_to_session(dict(row))
        except Exception as e:
            logger.warning(f"Error loading batch from DB: {e}")

        # Fallback to JSON
        if os.path.exists(self.json_path):
            try:
                with open(self.json_path, "r", encoding="utf-8") as f:
                    all_sessions = json.load(f)
                if batch_id in all_sessions:
                    return self._dict_to_session(all_sessions[batch_id])
            except Exception:
                pass
        return None

    def get_active_batch(self) -> Optional[BatchSession]:
        """Returns the currently active RUNNING batch session, if any."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM batch_sessions WHERE status = 'running' ORDER BY created_at DESC LIMIT 1"
                )
                row = cursor.fetchone()
                if row:
                    return self._row_to_session(dict(row))
        except Exception:
            pass
        return None

    def list_batches(self, limit: int = 10) -> List[BatchSession]:
        """Returns list of recent batch sessions."""
        sessions: List[BatchSession] = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM batch_sessions ORDER BY created_at DESC LIMIT ?", (limit,)
                )
                for row in cursor.fetchall():
                    sessions.append(self._row_to_session(dict(row)))
        except Exception:
            pass
        return sessions

    def cancel_batch(self, batch_id: str) -> bool:
        """Flags batch for graceful cancellation."""
        with self._lock:
            self._cancelled_batches.add(batch_id)
            session = self.get_batch(batch_id)
            if session:
                session.status = BatchStatus.CANCELLED
                session.completed_at = datetime.now(timezone.utc).isoformat()
                self._save_session(session)
                return True
            return False

    def is_cancelled(self, batch_id: str) -> bool:
        """Checks if batch has been flagged for cancellation."""
        return batch_id in self._cancelled_batches

    def run_batch_worker(
        self,
        batch_id: str,
        render_function: Callable[[str, Dict[str, Any], Callable[[int, str], None]], List[Dict[str, Any]]],
    ) -> None:
        """
        Runs sequential processing loop over batch items in background.
        Ensures strict 1-at-a-time GPU allocation, records clips,
        and isolates individual video errors without stopping the run.
        """
        session = self.get_batch(batch_id)
        if not session:
            logger.error(f"Cannot run batch {batch_id}: not found.")
            return

        session.started_at = datetime.now(timezone.utc).isoformat()
        session.status = BatchStatus.RUNNING
        self._save_session(session)

        try:
            for idx, item in enumerate(session.items):
                if self.is_cancelled(batch_id):
                    logger.info(f"Batch {batch_id} cancelled at item {idx + 1}/{session.total_videos}.")
                    item.status = BatchItemStatus.SKIPPED
                    continue

                session.current_index = idx + 1
                session.current_video_id = item.video_id
                session.current_stage = f"Processing video {idx + 1}/{session.total_videos}: {item.title[:30]}"
                session.current_progress = int((idx / max(session.total_videos, 1)) * 100)

                item.status = BatchItemStatus.PROCESSING
                item.started_at = datetime.now(timezone.utc).isoformat()
                self._save_session(session)

                # Progress callback for individual video processing
                def progress_cb(sub_progress: int, sub_stage: str) -> None:
                    # Scale sub_progress to overall batch progress
                    base_pct = (idx / max(session.total_videos, 1)) * 100
                    step_pct = (sub_progress / 100.0) * (100.0 / max(session.total_videos, 1))
                    session.current_progress = int(base_pct + step_pct)
                    session.current_stage = f"[{idx + 1}/{session.total_videos}] {sub_stage}"
                    self._save_session(session)

                try:
                    # Execute full clipping + rendering for this video
                    rendered_clips = render_function(item.video_id, session.render_config, progress_cb)
                    item.status = BatchItemStatus.COMPLETED
                    item.clips_count = len(rendered_clips)
                    item.completed_at = datetime.now(timezone.utc).isoformat()
                    session.completed_videos += 1
                    session.total_clips_generated += len(rendered_clips)
                    logger.info(
                        f"Batch {batch_id}: Video {item.video_id} completed with {len(rendered_clips)} shorts."
                    )
                except Exception as e:
                    err_msg = str(e)
                    logger.error(f"Batch {batch_id}: Video {item.video_id} failed: {err_msg}")
                    item.status = BatchItemStatus.FAILED
                    item.error_message = err_msg
                    item.completed_at = datetime.now(timezone.utc).isoformat()
                    session.failed_videos += 1

                self._save_session(session)

            # Finalize batch state
            session.completed_at = datetime.now(timezone.utc).isoformat()
            if self.is_cancelled(batch_id):
                session.status = BatchStatus.CANCELLED
            elif session.completed_videos > 0:
                session.status = BatchStatus.COMPLETED
                session.current_progress = 100
                session.current_stage = f"Overnight run complete! {session.total_clips_generated} Shorts generated across {session.completed_videos} videos."
            else:
                session.status = BatchStatus.FAILED
                session.current_stage = "All queued videos encountered errors."

            self._save_session(session)
            logger.info(f"Batch {batch_id} finished: {session.status.value}")

        except Exception as e:
            logger.exception(f"Unexpected error in batch worker {batch_id}: {e}")
            session.status = BatchStatus.FAILED
            session.completed_at = datetime.now(timezone.utc).isoformat()
            session.current_stage = f"Batch worker error: {str(e)}"
            self._save_session(session)
        finally:
            with self._lock:
                self._cancelled_batches.discard(batch_id)

    def _row_to_session(self, row: Dict[str, Any]) -> BatchSession:
        """Deserializes SQLite row into BatchSession."""
        items_data = json.loads(row.get("items_json") or "[]")
        items = [
            BatchVideoItem(
                video_id=it.get("video_id", ""),
                url=it.get("url", ""),
                title=it.get("title", ""),
                channel_name=it.get("channel_name", ""),
                channel_subs=it.get("channel_subs", ""),
                thumbnail_url=it.get("thumbnail_url", ""),
                duration_seconds=float(it.get("duration_seconds", 0.0)),
                status=BatchItemStatus(it.get("status", "queued")),
                job_id=it.get("job_id"),
                clips_count=int(it.get("clips_count", 0)),
                error_message=it.get("error_message"),
                started_at=it.get("started_at"),
                completed_at=it.get("completed_at"),
            )
            for it in items_data
        ]
        status_val = row.get("status", "idle")
        try:
            status_enum = BatchStatus(status_val)
        except Exception:
            status_enum = BatchStatus.IDLE

        return BatchSession(
            batch_id=row.get("batch_id", ""),
            name=row.get("name", "Overnight Batch"),
            status=status_enum,
            created_at=row.get("created_at", ""),
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            total_videos=int(row.get("total_videos", 0)),
            completed_videos=int(row.get("completed_videos", 0)),
            failed_videos=int(row.get("failed_videos", 0)),
            total_clips_generated=int(row.get("total_clips_generated", 0)),
            current_index=int(row.get("current_index", 0)),
            current_video_id=row.get("current_video_id"),
            current_stage=row.get("current_stage", ""),
            current_progress=int(row.get("current_progress", 0)),
            render_config=json.loads(row.get("render_config_json") or "{}"),
            items=items,
        )

    def _dict_to_session(self, data: Dict[str, Any]) -> BatchSession:
        """Deserializes JSON dict into BatchSession."""
        items_data = data.get("items", [])
        items = [
            BatchVideoItem(
                video_id=it.get("video_id", ""),
                url=it.get("url", ""),
                title=it.get("title", ""),
                channel_name=it.get("channel_name", ""),
                channel_subs=it.get("channel_subs", ""),
                thumbnail_url=it.get("thumbnail_url", ""),
                duration_seconds=float(it.get("duration_seconds", 0.0)),
                status=BatchItemStatus(it.get("status", "queued")),
                job_id=it.get("job_id"),
                clips_count=int(it.get("clips_count", 0)),
                error_message=it.get("error_message"),
                started_at=it.get("started_at"),
                completed_at=it.get("completed_at"),
            )
            for it in items_data
        ]
        status_val = data.get("status", "idle")
        try:
            status_enum = BatchStatus(status_val)
        except Exception:
            status_enum = BatchStatus.IDLE

        return BatchSession(
            batch_id=data.get("batch_id", ""),
            name=data.get("name", "Overnight Batch"),
            status=status_enum,
            created_at=data.get("created_at", ""),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            total_videos=int(data.get("total_videos", 0)),
            completed_videos=int(data.get("completed_videos", 0)),
            failed_videos=int(data.get("failed_videos", 0)),
            total_clips_generated=int(data.get("total_clips_generated", 0)),
            current_index=int(data.get("current_index", 0)),
            current_video_id=data.get("current_video_id"),
            current_stage=data.get("current_stage", ""),
            current_progress=int(data.get("current_progress", 0)),
            render_config=data.get("render_config", {}),
            items=items,
        )
