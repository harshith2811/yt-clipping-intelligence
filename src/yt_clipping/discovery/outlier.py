"""
Outlier Virality Multiplier Engine (Algorithmic mechanics adapted from swipe.py).
Replaces naive raw view counts in trend and channel discovery with Channel Median Multipliers:
    Virality Multiple = Video Views / Median(Channel Views)
Requires a baseline of >= 4 videos per channel. An outlier at >= 3.0x median is flagged as
a proven algorithmic breakout, regardless of whether the channel has 10k or 10M subscribers.
"""

from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from enum import Enum
import statistics

from ..contracts.models import VideoCandidate, CreatorSource


class OutlierClassification(str, Enum):
    BREAKOUT_OUTLIER = "BREAKOUT_OUTLIER"            # >= 3.0x channel median (algorithmic breakout)
    HIGH_PERFORMER = "HIGH_PERFORMER"                # 1.8x to 3.0x channel median
    STEADY = "STEADY"                                # 0.8x to 1.8x channel median
    UNDERPERFORMING = "UNDERPERFORMING"              # < 0.8x channel median
    INSUFFICIENT_BASELINE = "INSUFFICIENT_BASELINE"  # < 4 videos historical baseline


@dataclass
class OutlierReport:
    """Comprehensive outlier virality assessment for a candidate video."""
    video_id: str
    video_views: int
    channel_id: str
    channel_median_views: float
    virality_multiple: float
    sample_size: int
    is_outlier: bool
    is_algorithmic_breakout: bool
    has_sufficient_baseline: bool
    classification: OutlierClassification
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["classification"] = self.classification.value
        return d


class OutlierMultiplier:
    """
    Channel-relative outlier detection engine.
    Ensures discovery parity across small emerging creators and mega-channels.
    """

    MIN_BASELINE_VIDEOS: int = 4
    OUTLIER_THRESHOLD: float = 3.0
    HIGH_PERFORMER_THRESHOLD: float = 1.8
    STEADY_THRESHOLD: float = 0.8
    POPULATION_FALLBACK_MEDIAN: float = 10000.0

    def __init__(
        self,
        min_baseline_videos: int = MIN_BASELINE_VIDEOS,
        outlier_threshold: float = OUTLIER_THRESHOLD,
    ):
        self.min_baseline_videos = min_baseline_videos
        self.outlier_threshold = outlier_threshold

    def compute_channel_median(
        self,
        channel_views: List[int],
    ) -> Optional[float]:
        """
        Calculates the statistical median of recent channel uploads.
        Returns None if fewer than MIN_BASELINE_VIDEOS (4) are provided.
        """
        if not channel_views or len(channel_views) < self.min_baseline_videos:
            return None
        valid_views = [max(v, 0) for v in channel_views]
        return float(statistics.median(valid_views))

    def calculate_virality_multiple(
        self,
        video_views: int,
        channel_views: List[int],
        video_id: str = "",
        channel_id: str = "",
        creator: Optional[CreatorSource] = None,
    ) -> OutlierReport:
        """
        Calculates the Virality Multiple:
            Multiple = Video Views / Median(Channel Views)
        Requires sample size >= 4. Identifies outliers >= 3.0x median.
        """
        safe_views = max(int(video_views), 0)
        sample_size = len(channel_views)
        has_sufficient_baseline = sample_size >= self.min_baseline_videos

        if has_sufficient_baseline:
            channel_median = float(statistics.median([max(v, 0) for v in channel_views]))
            median_safe = max(channel_median, 1.0)
            multiple = round(float(safe_views) / median_safe, 2)

            is_outlier = multiple >= self.outlier_threshold
            is_breakout = is_outlier  # Both threshold and baseline satisfied

            if multiple >= self.outlier_threshold:
                classification = OutlierClassification.BREAKOUT_OUTLIER
                rationale = (
                    f"Proven algorithmic breakout at {multiple:.1f}x channel median "
                    f"({safe_views:,} vs median {channel_median:,.0f} across {sample_size} uploads)."
                )
            elif multiple >= self.HIGH_PERFORMER_THRESHOLD:
                classification = OutlierClassification.HIGH_PERFORMER
                rationale = (
                    f"Strong performance at {multiple:.1f}x channel median "
                    f"({safe_views:,} vs median {channel_median:,.0f})."
                )
            elif multiple >= self.STEADY_THRESHOLD:
                classification = OutlierClassification.STEADY
                rationale = (
                    f"Expected steady distribution at {multiple:.1f}x channel median "
                    f"({safe_views:,} vs median {channel_median:,.0f})."
                )
            else:
                classification = OutlierClassification.UNDERPERFORMING
                rationale = (
                    f"Underperforming at {multiple:.1f}x channel median "
                    f"({safe_views:,} vs median {channel_median:,.0f})."
                )
        else:
            # Baseline is insufficient (< 4 videos)
            fallback_median = (
                creator.baseline_views
                if (creator and creator.baseline_views > 0)
                else (statistics.median(channel_views) if channel_views else self.POPULATION_FALLBACK_MEDIAN)
            )
            fallback_safe = max(float(fallback_median), 1.0)
            multiple = round(float(safe_views) / fallback_safe, 2)
            is_outlier = multiple >= self.outlier_threshold
            is_breakout = False  # Not proven due to small sample size
            classification = OutlierClassification.INSUFFICIENT_BASELINE
            rationale = (
                f"Insufficient channel history ({sample_size}/{self.min_baseline_videos} required uploads). "
                f"Preliminary multiple {multiple:.1f}x against estimated baseline {fallback_median:,.0f}."
            )
            channel_median = fallback_safe

        return OutlierReport(
            video_id=video_id,
            video_views=safe_views,
            channel_id=channel_id,
            channel_median_views=round(channel_median, 1),
            virality_multiple=multiple,
            sample_size=sample_size,
            is_outlier=is_outlier,
            is_algorithmic_breakout=is_breakout,
            has_sufficient_baseline=has_sufficient_baseline,
            classification=classification,
            rationale=rationale,
        )

    def evaluate_candidate(
        self,
        candidate: VideoCandidate,
        channel_candidates: List[VideoCandidate],
        creator: Optional[CreatorSource] = None,
    ) -> OutlierReport:
        """Evaluates a VideoCandidate against a list of historical channel candidates."""
        views = [c.view_count for c in channel_candidates if c.video_id != candidate.video_id]
        # Include candidate in historical pool if not already present
        all_channel_views = views + [candidate.view_count]
        return self.calculate_virality_multiple(
            video_views=candidate.view_count,
            channel_views=all_channel_views,
            video_id=candidate.video_id,
            channel_id=candidate.creator_id,
            creator=creator,
        )

    def rank_candidates_by_outlier(
        self,
        candidates: List[VideoCandidate],
        channel_histories: Dict[str, List[int]],
    ) -> List[Tuple[VideoCandidate, OutlierReport]]:
        """
        Ranks video candidates descending by their channel-relative virality multiple.
        Prioritizes proven algorithmic breakouts regardless of raw channel subscriber scale.
        """
        evaluated: List[Tuple[VideoCandidate, OutlierReport]] = []
        for cand in candidates:
            c_views = channel_histories.get(cand.creator_id, [])
            report = self.calculate_virality_multiple(
                video_views=cand.view_count,
                channel_views=c_views,
                video_id=cand.video_id,
                channel_id=cand.creator_id,
            )
            evaluated.append((cand, report))

        # Sort: algorithmic breakouts first, then descending by multiple
        evaluated.sort(
            key=lambda x: (
                1 if x[1].is_algorithmic_breakout else 0,
                x[1].virality_multiple,
            ),
            reverse=True,
        )
        return evaluated
