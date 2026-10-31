"""
Channel Registry Service for Managing Monitored YouTube Creators.
Persists monitored creators and baseline performance models to SQLite.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from ..orchestration.db import DatabaseManager
from ..contracts.models import CreatorSource


class ChannelRegistry:
    """
    CRUD management for monitored YouTube channels stored in SQLite.
    """

    def __init__(self, db_path: str = "data/jobs.db"):
        self.db = DatabaseManager(db_path)

    def add_channel(
        self,
        channel_id: str,
        name: str,
        handle: Optional[str] = None,
        channel_url: Optional[str] = None,
        baseline_views: float = 10000.0,
    ) -> bool:
        """Adds or updates a monitored channel in the registry."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO monitored_channels (
                        channel_id, name, channel_url, handle, baseline_views, active, created_at
                    ) VALUES (?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(channel_id) DO UPDATE SET
                        name=excluded.name,
                        channel_url=COALESCE(excluded.channel_url, monitored_channels.channel_url),
                        handle=COALESCE(excluded.handle, monitored_channels.handle),
                        baseline_views=excluded.baseline_views,
                        active=1
                    """,
                    (channel_id, name, channel_url, handle, baseline_views, now),
                )
            return True
        finally:
            conn.close()

    def remove_channel(self, channel_id: str) -> bool:
        """Deactivates/removes a channel from active monitoring."""
        conn = self.db.get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    "UPDATE monitored_channels SET active = 0 WHERE channel_id = ? OR handle = ?",
                    (channel_id, channel_id),
                )
                return cursor.rowcount > 0
        finally:
            conn.close()

    def list_channels(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """Lists monitored channels."""
        conn = self.db.get_connection()
        try:
            query = (
                "SELECT channel_id, name, channel_url, handle, baseline_views, active, last_polled_at, created_at "
                "FROM monitored_channels"
            )
            if active_only:
                query += " WHERE active = 1"
            query += " ORDER BY name ASC"

            cursor = conn.execute(query)
            rows = cursor.fetchall()
            return [
                {
                    "channel_id": r[0],
                    "name": r[1],
                    "channel_url": r[2],
                    "handle": r[3],
                    "baseline_views": float(r[4]),
                    "active": bool(r[5]),
                    "last_polled_at": r[6],
                    "created_at": r[7],
                }
                for r in rows
            ]
        finally:
            conn.close()

    def update_last_polled(self, channel_id: str) -> None:
        """Records polling timestamp for a channel."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    "UPDATE monitored_channels SET last_polled_at = ? WHERE channel_id = ?",
                    (now, channel_id),
                )
        finally:
            conn.close()

    def get_creator_source(self, channel_id: str) -> Optional[CreatorSource]:
        """Loads CreatorSource contract model for ranking calculations."""
        conn = self.db.get_connection()
        try:
            cursor = conn.execute(
                "SELECT channel_id, name, channel_url, baseline_views FROM monitored_channels WHERE channel_id = ?",
                (channel_id,),
            )
            row = cursor.fetchone()
            if row:
                return CreatorSource(
                    creator_id=row[0],
                    name=row[1],
                    channel_id=row[0],
                    channel_url=row[2] or f"https://youtube.com/channel/{row[0]}",
                    baseline_views=float(row[3]),
                )
            return None
        finally:
            conn.close()
