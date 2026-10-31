"""
Centralized SQLite Database Manager with WAL Mode and Schema Migrations.
Provides transactional storage for jobs, rights manifests, publishing receipts,
metric snapshots, API quota telemetry, and dead-letter queues.
"""

from typing import Optional, Dict, Any, List
import sqlite3
import os
import json
from datetime import datetime, timezone


class DatabaseManager:
    """
    Thread-safe SQLite manager using WAL mode, busy timeouts, and robust schema migrations.
    """

    def __init__(self, db_path: str = "data/jobs.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self.init_schema()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def init_schema(self) -> None:
        conn = self.get_connection()
        try:
            with conn:
                # 1. Pipeline Jobs Table
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
                conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_video_id ON jobs(video_id);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);")

                # 2. Rights Ledger Table
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS rights_ledger (
                        rights_id TEXT PRIMARY KEY,
                        video_id TEXT NOT NULL UNIQUE,
                        basis TEXT NOT NULL,
                        status TEXT NOT NULL,
                        owner_name TEXT NOT NULL,
                        license_url TEXT,
                        proof_reference TEXT,
                        valid_until TEXT,
                        verified_at TEXT,
                        audit_notes TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_rights_video ON rights_ledger(video_id);")

                # 3. Publishing Receipts Table (Unique idempotency key prevents concurrent duplicate delivery)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS publishing_receipts (
                        receipt_id TEXT PRIMARY KEY,
                        clip_id TEXT NOT NULL,
                        idempotency_key TEXT UNIQUE NOT NULL,
                        status TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        target_mode TEXT NOT NULL,
                        dry_run INTEGER NOT NULL,
                        response_payload_json TEXT
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_rcpt_idemp ON publishing_receipts(idempotency_key);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_rcpt_clip ON publishing_receipts(clip_id);")

                # 4. Metric Snapshots Table (Durable historical views, likes, comments)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS metric_snapshots (
                        snapshot_id TEXT PRIMARY KEY,
                        video_id TEXT NOT NULL,
                        channel_id TEXT,
                        timestamp TEXT NOT NULL,
                        view_count INTEGER NOT NULL,
                        like_count INTEGER DEFAULT 0,
                        comment_count INTEGER DEFAULT 0,
                        calculated_velocity REAL DEFAULT 0.0,
                        source TEXT DEFAULT 'api'
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_snaps_vid_ts ON metric_snapshots(video_id, timestamp);")

                # 5. Monitored Channels Table
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS monitored_channels (
                        channel_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        channel_url TEXT,
                        handle TEXT,
                        baseline_views REAL DEFAULT 10000.0,
                        active INTEGER DEFAULT 1,
                        last_polled_at TEXT,
                        created_at TEXT NOT NULL
                    )
                    """
                )

                # 6. API Quota Log Table
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS api_quota_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        endpoint TEXT NOT NULL,
                        units_spent INTEGER NOT NULL,
                        timestamp TEXT NOT NULL,
                        success INTEGER DEFAULT 1,
                        details TEXT
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_quota_ts ON api_quota_log(timestamp);")

                # 7. Webhook Dead-Letter Queue (DLQ)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS webhook_dlq (
                        item_id TEXT PRIMARY KEY,
                        clip_id TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        target_url TEXT NOT NULL,
                        attempt_count INTEGER DEFAULT 0,
                        max_attempts INTEGER DEFAULT 4,
                        next_retry_at TEXT,
                        last_error TEXT,
                        status TEXT DEFAULT 'PENDING',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_dlq_status ON webhook_dlq(status, next_retry_at);")

                # 8. Discovered Uploads Table (Real-time Pinger & Scraper Ingestion)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS discovered_uploads (
                        video_id TEXT PRIMARY KEY,
                        channel_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        published_at TEXT NOT NULL,
                        discovered_at TEXT NOT NULL,
                        initial_views INTEGER DEFAULT 0,
                        latest_views INTEGER DEFAULT 0,
                        hourly_velocity REAL DEFAULT 0.0,
                        velocity_multiplier REAL DEFAULT 0.0,
                        virality_classification TEXT DEFAULT 'STEADY',
                        like_ratio REAL DEFAULT 0.0,
                        comment_ratio REAL DEFAULT 0.0,
                        status TEXT DEFAULT 'DISCOVERED',
                        attribution_text TEXT,
                        source_url TEXT,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(channel_id) REFERENCES monitored_channels(channel_id)
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_uploads_velocity ON discovered_uploads(velocity_multiplier DESC);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_uploads_status ON discovered_uploads(status);")

                # 9. Velocity Snapshots Table (Early-Hour Velocity Tracking)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS velocity_snapshots (
                        snapshot_id TEXT PRIMARY KEY,
                        video_id TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        age_hours REAL NOT NULL,
                        view_count INTEGER NOT NULL,
                        like_count INTEGER DEFAULT 0,
                        comment_count INTEGER DEFAULT 0,
                        hourly_velocity REAL NOT NULL,
                        velocity_multiplier REAL NOT NULL,
                        classification TEXT NOT NULL,
                        source TEXT DEFAULT 'rss_pinger'
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_vsnaps_vid_ts ON velocity_snapshots(video_id, timestamp);")

                # 10. Creator Permissions & Attribution Policies
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS creator_permissions (
                        channel_id TEXT PRIMARY KEY,
                        channel_name TEXT NOT NULL,
                        policy_type TEXT NOT NULL,
                        attribution_template TEXT,
                        allowed_commercial INTEGER DEFAULT 1,
                        disclaimer_required INTEGER DEFAULT 1,
                        notes TEXT,
                        updated_at TEXT NOT NULL
                    )
                    """
                )

                # Schema migration helper: ensure monitored_channels has policy and etag columns
                try:
                    conn.execute("ALTER TABLE monitored_channels ADD COLUMN clipping_policy TEXT DEFAULT 'OPEN_AFFILIATE'")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE monitored_channels ADD COLUMN etag TEXT")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE monitored_channels ADD COLUMN last_modified TEXT")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE monitored_channels ADD COLUMN paused INTEGER DEFAULT 0")
                except sqlite3.OperationalError:
                    pass

        finally:
            conn.close()
