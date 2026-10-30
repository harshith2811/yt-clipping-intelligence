"""
Discovery Ranking and Metric Observation Engine.
Separates observed public momentum from internal retention predictions.
Calculates view velocity across time snapshots and normalizes by channel baseline.
"""

from typing import List, Dict, Optional
from datetime import datetime, timezone
import math
from ..contracts.models import VideoCandidate, MetricSnapshot, CreatorSource
from ..contracts.interfaces import MetricObserver


class PublicMetricRanker(MetricObserver):
    """
    Records public metric snapshots and ranks videos using:
    - Observed View Velocity (views gained per hour between observations)
    - Channel Baseline Normalization (prevents large channels from dominating discovery)
    - Recency Decay (prioritizes fresh uploads within lookback window)
    """

    def __init__(self):
        self._snapshots: Dict[str, List[MetricSnapshot]] = {}

    def record_snapshot(
        self, video_id: str, view_count: int, like_count: int = 0, comment_count: int = 0
    ) -> MetricSnapshot:
        now_iso = datetime.now(timezone.utc).isoformat()
        snap_id = f"snap-{video_id}-{len(self._snapshots.get(video_id, [])) + 1}"

        existing = self._snapshots.get(video_id, [])
        velocity = 0.0
        if existing:
            prev = existing[-1]
            try:
                t1 = datetime.fromisoformat(prev.timestamp.replace("Z", "+00:00"))
                t2 = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
                hours = max((t2 - t1).total_seconds() / 3600.0, 0.001)
                velocity = max((view_count - prev.view_count) / hours, 0.0)
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

        if video_id not in self._snapshots:
            self._snapshots[video_id] = []
        self._snapshots[video_id].append(snapshot)
        return snapshot

    def calculate_view_velocity(self, snapshots: List[MetricSnapshot]) -> float:
        if len(snapshots) < 2:
            return 0.0
        first = snapshots[0]
        last = snapshots[-1]
        try:
            t1 = datetime.fromisoformat(first.timestamp.replace("Z", "+00:00"))
            t2 = datetime.fromisoformat(last.timestamp.replace("Z", "+00:00"))
            hours = max((t2 - t1).total_seconds() / 3600.0, 0.001)
            return max((last.view_count - first.view_count) / hours, 0.0)
        except Exception:
            return 0.0

    def compute_discovery_score(
        self,
        candidate: VideoCandidate,
        creator: Optional[CreatorSource] = None,
        as_of: Optional[datetime] = None,
    ) -> float:
        """
        Computes normalized discovery score (0.0 to 100.0).
        """
        now = as_of or datetime.now(timezone.utc)
        try:
            pub_dt = datetime.fromisoformat(candidate.published_at.replace("Z", "+00:00"))
            age_hours = max((now - pub_dt).total_seconds() / 3600.0, 0.1)
        except Exception:
            age_hours = 24.0

        # 1. Recency Score (Exponential half-life of 48 hours)
        recency_score = math.exp(-0.693 * (age_hours / 48.0)) * 100.0

        # 2. Velocity Score (Relative to baseline)
        baseline = creator.baseline_views if creator and creator.baseline_views > 0 else 10000.0
        snapshots = self._snapshots.get(candidate.video_id, [])
        velocity = self.calculate_view_velocity(snapshots)

        # Expected hourly view rate ~ baseline / 48
        expected_hourly = max(baseline / 48.0, 10.0)
        velocity_ratio = velocity / expected_hourly if velocity > 0 else (candidate.view_count / max(age_hours, 1.0)) / expected_hourly
        velocity_score = min(velocity_ratio * 30.0, 100.0)

        # 3. Engagement Score (Likes / Views ratio)
        engagement_ratio = (candidate.like_count / max(candidate.view_count, 1)) if candidate.view_count > 0 else 0.0
        # Average YouTube like ratio is ~4% (0.04)
        engagement_score = min((engagement_ratio / 0.04) * 50.0, 100.0)

        # Composite score: Recency (35%), Velocity (50%), Engagement (15%)
        composite = (0.35 * recency_score) + (0.50 * velocity_score) + (0.15 * engagement_score)
        final_score = round(min(max(composite, 0.0), 100.0), 2)

        candidate.discovery_score = final_score
        candidate.discovery_rationale = (
            f"Score {final_score}/100: Age={age_hours:.1f}h (recency={recency_score:.1f}), "
            f"velocity_ratio={velocity_ratio:.2f}x baseline (velocity={velocity_score:.1f}), "
            f"engagement={engagement_score:.1f}."
        )
        return final_score

    def rank_candidates(
        self, candidates: List[VideoCandidate], creators: Dict[str, CreatorSource]
    ) -> List[VideoCandidate]:
        """Ranks candidates descending by discovery score."""
        for c in candidates:
            creator = creators.get(c.creator_id)
            self.compute_discovery_score(c, creator)
        return sorted(candidates, key=lambda x: x.discovery_score, reverse=True)
