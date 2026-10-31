"""
Centralized API Quota Governor and Accounting Service.
Enforces YouTube Data API v3 daily usage limits, persists consumption in SQLite,
triggers cost-control policies at 90% threshold, and provides usage telemetry.
"""

from typing import Dict, Any, Optional
import os
import sqlite3
from datetime import datetime, timezone, date
from ..orchestration.db import DatabaseManager


class QuotaExceededError(RuntimeError):
    """Raised when YouTube Data API quota daily budget is exhausted."""
    pass


class APIQuotaGovernor:
    """
    Centralized quota governor managing YouTube Data API v3 units across all workers.
    """

    DAILY_DEFAULT_LIMIT = 10000

    COST_SEARCH_LIST = 100
    COST_VIDEOS_LIST = 1
    COST_PLAYLIST_ITEMS_LIST = 1
    COST_CHANNELS_LIST = 1
    COST_COMMENTS_LIST = 1
    COST_RSS_FEED = 0  # RSS feeds consume zero YouTube Data API quota

    def __init__(self, daily_limit: int = DAILY_DEFAULT_LIMIT, db_path: str = "data/jobs.db"):
        self.daily_limit = daily_limit
        self.db = DatabaseManager(db_path)

    def _get_today_spent(self) -> int:
        today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        conn = self.db.get_connection()
        try:
            cursor = conn.execute(
                "SELECT COALESCE(SUM(units_spent), 0) FROM api_quota_log WHERE timestamp LIKE ?",
                (f"{today_prefix}%",),
            )
            row = cursor.fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()

    def can_spend(self, cost: int) -> bool:
        if cost == 0:
            return True
        spent = self._get_today_spent()
        return (spent + cost) <= self.daily_limit

    def is_cost_control_active(self) -> bool:
        """Returns True if 90% of configured daily quota has been consumed."""
        spent = self._get_today_spent()
        return spent >= (0.90 * self.daily_limit)

    def record_spend(self, endpoint: str, cost: int, success: bool = True, details: str = "") -> None:
        """Records API expenditure to database atomically."""
        if cost == 0:
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO api_quota_log (endpoint, units_spent, timestamp, success, details)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (endpoint, cost, now_iso, 1 if success else 0, details),
                )
        finally:
            conn.close()

    def spend(self, endpoint: str, cost: int, details: str = "") -> None:
        """
        Deducts quota units if within daily budget.
        Raises QuotaExceededError if limit would be breached.
        """
        if cost == 0:
            return

        spent = self._get_today_spent()
        if (spent + cost) > self.daily_limit:
            self.record_spend(endpoint, 0, success=False, details=f"Rejected: quota exceeded ({spent}/{self.daily_limit})")
            raise QuotaExceededError(
                f"YouTube Data API quota exceeded! Spent: {spent}, Requested: {cost}, Daily Limit: {self.daily_limit}"
            )

        self.record_spend(endpoint, cost, success=True, details=details)

    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive quota telemetry."""
        spent = self._get_today_spent()
        remaining = max(self.daily_limit - spent, 0)
        cost_control = self.is_cost_control_active()
        return {
            "daily_limit": self.daily_limit,
            "units_spent": spent,
            "units_remaining": remaining,
            "pct_consumed": round((spent / float(self.daily_limit)) * 100.0, 1),
            "cost_control_active": cost_control,
            "reset_time_utc": "00:00:00 UTC",
        }
