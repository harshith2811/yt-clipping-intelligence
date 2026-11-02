"""
Discovery Ranking and Metric Observation Engine.
Calculates mathematically sound view velocity across temporal snapshots,
persists snapshots durably in SQLite to survive restarts,
and normalizes discovery scores by channel baseline.
"""

from typing import List, Dict, Optional
from datetime import datetime, timezone
import math
import sqlite3

from ..contracts.models import VideoCandidate, MetricSnapshot, CreatorSource
from ..contracts.interfaces import MetricObserver
from ..orchestration.db import DatabaseManager
from .outlier import OutlierMultiplier


class PublicMetricRanker(MetricObserver):
    """
    Records public metric snapshots in SQLite and ranks videos using:
    - Mathematically valid View Velocity (views gained per hour between observations)
    - Minimum observation intervals to prevent division by near-zero time intervals
    - Channel Baseline Normalization (prevents large channels from dominating discovery)
    - Recency Decay (exponential half-life of 48 hours)
    - Channel Median Outlier Multipliers (>= 3.0x median breakouts)
    """

    MIN_OBSERVATION_SECONDS = 30.0  # Minimum interval to avoid noise spikes

    def __init__(self, db_path: str = "data/jobs.db", outlier_multiplier: Optional[OutlierMultiplier] = None):
        self.db = DatabaseManager(db_path)
        self.outlier_multiplier = outlier_multiplier or OutlierMultiplier()
        self._snapshots_cache: Dict[str, List[MetricSnapshot]] = {}
        self._load_cached_snapshots()


    def _load_cached_snapshots(self) -> None:
        conn = self.db.get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT snapshot_id, video_id, timestamp, view_count, like_count, comment_count, calculated_velocity
                FROM metric_snapshots ORDER BY timestamp ASC
                """
            )
            for row in cursor.fetchall():
                snap = MetricSnapshot(
                    snapshot_id=row[0],
                    video_id=row[1],
                    timestamp=row[2],
                    view_count=row[3],
                    like_count=row[4],
                    comment_count=row[5],
                    calculated_velocity=row[6],
                )
                if snap.video_id not in self._snapshots_cache:
                    self._snapshots_cache[snap.video_id] = []
                self._snapshots_cache[snap.video_id].append(snap)
        finally:
            conn.close()

    def record_snapshot(
        self,
        video_id: str,
        view_count: int,
        like_count: int = 0,
        comment_count: int = 0,
        channel_id: Optional[str] = None,
        source: str = "api",
    ) -> MetricSnapshot:
        """Records a metric snapshot to SQLite and updates velocity telemetry."""
        now_iso = datetime.now(timezone.utc).isoformat()
        existing = self._snapshots_cache.get(video_id, [])
        snap_id = f"snap-{video_id}-{len(existing) + 1}"

        velocity = 0.0
        if existing:
            prev = existing[-1]
            try:
                t1 = datetime.fromisoformat(prev.timestamp.replace("Z", "+00:00"))
                t2 = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
                delta_sec = (t2 - t1).total_seconds()

                if delta_sec >= self.MIN_OBSERVATION_SECONDS:
                    hours = delta_sec / 3600.0
                    delta_views = view_count - prev.view_count
                    # BUG-09 fix: handle view adjustments/decreases gracefully
                    if delta_views < 0:
                        velocity = 0.0
                    else:
                        velocity = delta_views / hours
                else:
                    # Too close to previous observation: retain previous velocity
                    velocity = prev.calculated_velocity
            except Exception:
                velocity = 0.0

        snapshot = MetricSnapshot(
            snapshot_id=snap_id,
            video_id=video_id,
            timestamp=now_iso,
            view_count=view_count,
            like_count=like_count,
            comment_count=comment_count,
            calculated_velocity=round(velocity, 2),
        )

        # Persist to SQLite
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO metric_snapshots (
                        snapshot_id, video_id, channel_id, timestamp, view_count, like_count, comment_count, calculated_velocity, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.snapshot_id,
                        snapshot.video_id,
                        channel_id,
                        snapshot.timestamp,
                        snapshot.view_count,
                        snapshot.like_count,
                        snapshot.comment_count,
                        snapshot.calculated_velocity,
                        source,
                    ),
                )
        finally:
            conn.close()

        if video_id not in self._snapshots_cache:
            self._snapshots_cache[video_id] = []
        self._snapshots_cache[video_id].append(snapshot)
        return snapshot

    def calculate_view_velocity(self, snapshots: List[MetricSnapshot]) -> float:
        """
        Calculates observed view velocity across snapshots.
        BUG-09 fix: Rejects inverted timestamps and near-zero intervals.
        """
        if len(snapshots) < 2:
            return 0.0

        first = snapshots[0]
        last = snapshots[-1]
        try:
            t1 = datetime.fromisoformat(first.timestamp.replace("Z", "+00:00"))
            t2 = datetime.fromisoformat(last.timestamp.replace("Z", "+00:00"))
            delta_sec = (t2 - t1).total_seconds()

            if delta_sec < self.MIN_OBSERVATION_SECONDS:
                return 0.0

            hours = delta_sec / 3600.0
            delta_views = last.view_count - first.view_count
            if delta_views <= 0:
                return 0.0

            return round(delta_views / hours, 2)
        except Exception:
            return 0.0

    def compute_discovery_score(
        self,
        candidate: VideoCandidate,
        creator: Optional[CreatorSource] = None,
        as_of: Optional[datetime] = None,
        channel_views: Optional[List[int]] = None,
    ) -> float:
        """
        Computes normalized discovery score (0.0 to 100.0).
        If channel_views with >= 4 uploads is provided, normalizes against Channel Median Multipliers.
        """
        now = as_of or datetime.now(timezone.utc)
        try:
            pub_dt = datetime.fromisoformat(candidate.published_at.replace("Z", "+00:00"))
            age_hours = max((now - pub_dt).total_seconds() / 3600.0, 0.1)
        except Exception:
            age_hours = 24.0

        # 1. Recency Score (Exponential half-life of 48 hours)
        recency_score = math.exp(-0.693 * (age_hours / 48.0)) * 100.0

        # 2. Velocity Score (Relative to baseline or median)
        outlier_report = None
        if channel_views and len(channel_views) >= self.outlier_multiplier.min_baseline_videos:
            outlier_report = self.outlier_multiplier.calculate_virality_multiple(
                video_views=candidate.view_count,
                channel_views=channel_views,
                video_id=candidate.video_id,
                channel_id=candidate.creator_id,
                creator=creator,
            )
            baseline = outlier_report.channel_median_views
        else:
            baseline = creator.baseline_views if creator and creator.baseline_views > 0 else 10000.0

        snapshots = self._snapshots_cache.get(candidate.video_id, [])

        has_observed_snapshots = len(snapshots) >= 2
        if has_observed_snapshots:
            velocity = self.calculate_view_velocity(snapshots)
        else:
            velocity = candidate.view_count / max(age_hours, 1.0)

        # Expected hourly view rate ~ baseline / 48
        expected_hourly = max(baseline / 48.0, 10.0)
        velocity_ratio = velocity / expected_hourly
        velocity_score = min(velocity_ratio * 30.0, 100.0)

        # 3. Engagement Score (Likes / Views ratio)
        engagement_ratio = (candidate.like_count / max(candidate.view_count, 1)) if candidate.view_count > 0 else 0.0
        # Benchmark YouTube like ratio is ~4% (0.04)
        engagement_score = min((engagement_ratio / 0.04) * 50.0, 100.0)

        # Composite score: Recency (35%), Velocity (50%), Engagement (15%)
        composite = (0.35 * recency_score) + (0.50 * velocity_score) + (0.15 * engagement_score)

        # Breakout boost if proven algorithmic breakout (>= 3.0x channel median)
        if outlier_report and outlier_report.is_algorithmic_breakout:
            composite = min(composite * 1.15, 100.0)

        final_score = round(min(max(composite, 0.0), 100.0), 2)

        velocity_type = "observed_velocity" if has_observed_snapshots else "lifetime_pace"
        candidate.discovery_score = final_score

        outlier_note = ""
        if outlier_report and outlier_report.is_algorithmic_breakout:
            outlier_note = f", Outlier={outlier_report.virality_multiple:.1f}x median breakout"

        candidate.discovery_rationale = (
            f"Score {final_score}/100: Age={age_hours:.1f}h (recency={recency_score:.1f}), "
            f"velocity_ratio={velocity_ratio:.2f}x baseline ({velocity_type}={velocity:.0f}/hr), "
            f"engagement={engagement_score:.1f}{outlier_note}."
        )
        return final_score

    def rank_candidates(
        self,
        candidates: List[VideoCandidate],
        creators: Dict[str, CreatorSource],
        channel_histories: Optional[Dict[str, List[int]]] = None,
    ) -> List[VideoCandidate]:
        """Ranks candidates descending by discovery score."""
        for c in candidates:
            creator = creators.get(c.creator_id)
            c_views = channel_histories.get(c.creator_id) if channel_histories else None
            self.compute_discovery_score(c, creator, channel_views=c_views)
        return sorted(candidates, key=lambda x: x.discovery_score, reverse=True)
