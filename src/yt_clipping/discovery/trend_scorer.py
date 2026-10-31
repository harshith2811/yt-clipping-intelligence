"""
Early-Hour View Velocity and Statistical Virality Scraper Engine.
Computes real-time hourly view velocity, creator baseline normalization,
engagement resonance ratios (LVR, CVR), and classifies viral breakout moments.
"""

from typing import Dict, Any, Optional, Tuple, List
from enum import Enum
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import uuid
import math

from ..orchestration.db import DatabaseManager


class ViralityClassification(str, Enum):
    VIRAL_EXPLOSION = "VIRAL_EXPLOSION"      # >= 3.0x baseline velocity
    TRENDING_HIGH = "TRENDING_HIGH"          # 1.5x - 3.0x baseline velocity
    STEADY = "STEADY"                        # 0.8x - 1.5x baseline velocity
    UNDERPERFORMING = "UNDERPERFORMING"      # < 0.8x baseline velocity


@dataclass
class VelocityTelemetry:
    video_id: str
    channel_id: str
    title: str
    published_at: str
    age_hours: float
    view_count: int
    like_count: int
    comment_count: int
    hourly_velocity: float
    baseline_velocity: float
    velocity_multiplier: float
    classification: ViralityClassification
    like_ratio: float
    comment_ratio: float
    is_resonant: bool
    resonance_flag: str
    virality_score: float

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["classification"] = self.classification.value
        return d


class TrendScorer:
    """
    Statistical engine for early-hour velocity scoring and resonance validation.
    Persists historical telemetry to the SQLite database.
    """

    POPULATION_BASELINE_VIEWS = 10000.0  # Median baseline if channel history is absent
    BASELINE_WINDOW_HOURS = 48.0         # Baseline window for velocity denominator

    def __init__(self, db_path: str = "data/jobs.db"):
        self.db = DatabaseManager(db_path)

    @staticmethod
    def calculate_hourly_velocity(view_count: int, age_hours: float) -> float:
        """
        Calculates hourly view velocity with lower-bound age clamping (15 mins minimum).
        V_hourly = Current Views / max(Age in Hours, 0.25)
        """
        clamped_age = max(float(age_hours), 0.25)
        return float(view_count) / clamped_age

    @classmethod
    def calculate_velocity_multiplier(
        cls, hourly_velocity: float, baseline_views: Optional[float] = None
    ) -> Tuple[float, float]:
        """
        Calculates the velocity multiplier M_v normalized against channel baseline.
        Returns (velocity_multiplier, baseline_hourly_velocity).
        """
        base_views = baseline_views if (baseline_views and baseline_views > 0) else cls.POPULATION_BASELINE_VIEWS
        baseline_hourly_velocity = max(base_views / cls.BASELINE_WINDOW_HOURS, 10.0)
        multiplier = hourly_velocity / baseline_hourly_velocity
        return round(multiplier, 2), round(baseline_hourly_velocity, 2)

    @staticmethod
    def classify_multiplier(multiplier: float) -> ViralityClassification:
        """
        Classifies candidate upload based on velocity multiplier thresholds:
        - M_v >= 3.0x: VIRAL_EXPLOSION
        - 1.5x <= M_v < 3.0x: TRENDING_HIGH
        - 0.8x <= M_v < 1.5x: STEADY
        - M_v < 0.8x: UNDERPERFORMING
        """
        if multiplier >= 3.0:
            return ViralityClassification.VIRAL_EXPLOSION
        elif multiplier >= 1.5:
            return ViralityClassification.TRENDING_HIGH
        elif multiplier >= 0.8:
            return ViralityClassification.STEADY
        else:
            return ViralityClassification.UNDERPERFORMING

    @staticmethod
    def calculate_engagement_ratios(
        view_count: int, like_count: int = 0, comment_count: int = 0
    ) -> Tuple[float, float]:
        """Calculates Like-to-View Ratio (LVR) and Comment-to-View Ratio (CVR) as percentages."""
        safe_views = max(view_count, 1)
        lvr = (float(like_count) / safe_views) * 100.0
        cvr = (float(comment_count) / safe_views) * 100.0
        return round(lvr, 2), round(cvr, 2)

    @staticmethod
    def validate_resonance(
        like_ratio: float,
        comment_ratio: float,
        view_count: int,
        min_like_ratio: float = 1.2,
        min_comment_ratio: float = 0.03,
    ) -> Tuple[bool, str]:
        """
        Detects clickbait or bot view anomalies.
        If views are substantial (> 5,000) but engagement ratios are extremely low,
        flags anomaly.
        """
        if view_count < 1000:
            return True, "INSUFFICIENT_SAMPLE_SIZE"

        if like_ratio < min_like_ratio and view_count > 5000:
            return False, f"SUSPICIOUS_LOW_LIKE_RATIO ({like_ratio:.2f}% < {min_like_ratio}%)"
        if comment_ratio < min_comment_ratio and view_count > 10000:
            return False, f"SUSPICIOUS_LOW_COMMENT_RATIO ({comment_ratio:.2f}% < {min_comment_ratio}%)"

        return True, "HEALTHY_ORGANIC_ENGAGEMENT"

    @classmethod
    def compute_composite_virality_score(
        cls,
        multiplier: float,
        like_ratio: float,
        comment_ratio: float,
        age_hours: float,
    ) -> float:
        """
        Computes calibrated composite virality score (0.0 to 100.0).
        Rewards explosive early velocity while factoring in audience engagement depth.
        """
        # Velocity component: up to 60 points
        vel_pts = min(multiplier * 20.0, 60.0)
        # Engagement component: up to 25 points
        like_pts = min(like_ratio * 4.0, 15.0)
        comment_pts = min(comment_ratio * 20.0, 10.0)
        # Freshness urgency: up to 15 points
        freshness_pts = max(15.0 - (age_hours * 0.5), 0.0)

        composite = vel_pts + like_pts + comment_pts + freshness_pts
        return round(min(max(composite, 0.0), 100.0), 1)

    def evaluate_video(
        self,
        video_id: str,
        channel_id: str,
        title: str,
        published_at_iso: str,
        view_count: int,
        like_count: int = 0,
        comment_count: int = 0,
        baseline_views: Optional[float] = None,
        source: str = "rss_pinger",
        record_snapshot: bool = True,
    ) -> VelocityTelemetry:
        """
        Executes end-to-end virality and velocity evaluation.
        Optionally persists telemetry to SQLite velocity_snapshots table.
        """
        now = datetime.now(timezone.utc)
        try:
            clean_iso = published_at_iso.replace("Z", "+00:00")
            pub_dt = datetime.fromisoformat(clean_iso)
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            age_hours = max((now - pub_dt).total_seconds() / 3600.0, 0.25)
        except Exception:
            age_hours = 24.0

        hourly_vel = self.calculate_hourly_velocity(view_count, age_hours)
        multiplier, base_vel = self.calculate_velocity_multiplier(hourly_vel, baseline_views)
        classification = self.classify_multiplier(multiplier)
        lvr, cvr = self.calculate_engagement_ratios(view_count, like_count, comment_count)
        is_resonant, res_flag = self.validate_resonance(lvr, cvr, view_count)
        score = self.compute_composite_virality_score(multiplier, lvr, cvr, age_hours)

        telemetry = VelocityTelemetry(
            video_id=video_id,
            channel_id=channel_id,
            title=title,
            published_at=published_at_iso,
            age_hours=round(age_hours, 2),
            view_count=view_count,
            like_count=like_count,
            comment_count=comment_count,
            hourly_velocity=round(hourly_vel, 1),
            baseline_velocity=base_vel,
            velocity_multiplier=multiplier,
            classification=classification,
            like_ratio=lvr,
            comment_ratio=cvr,
            is_resonant=is_resonant,
            resonance_flag=res_flag,
            virality_score=score,
        )

        if record_snapshot:
            self._save_snapshot(telemetry, source=source)

        return telemetry

    def _save_snapshot(self, t: VelocityTelemetry, source: str) -> None:
        """Persists velocity snapshot into SQLite database."""
        snap_id = f"snap-{t.video_id}-{uuid.uuid4().hex[:6]}"
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO velocity_snapshots (
                        snapshot_id, video_id, timestamp, age_hours, view_count, like_count, comment_count,
                        hourly_velocity, velocity_multiplier, classification, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snap_id,
                        t.video_id,
                        now_iso,
                        t.age_hours,
                        t.view_count,
                        t.like_count,
                        t.comment_count,
                        t.hourly_velocity,
                        t.velocity_multiplier,
                        t.classification.value,
                        source,
                    ),
                )
        except Exception:
            pass
        finally:
            conn.close()
