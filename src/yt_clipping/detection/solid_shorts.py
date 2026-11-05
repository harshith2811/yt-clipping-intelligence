"""
Dynamic Yield Decision Engine for High-Retention YouTube Shorts.
Determines the mathematically optimal number of solid, non-cannibalizing,
high-retention Shorts to extract from any given source video.
"""

from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
import math
import logging

from ..contracts.models import HighlightCandidate, Transcript, HeatmapData

logger = logging.getLogger(__name__)


@dataclass
class SolidShortsConfig:
    """Configurable thresholds for the Solid Shorts Decision Engine."""
    # Quality thresholds
    tier_1_instant_viral_score: float = 80.0     # Always accepted if capacity permits
    solid_quality_floor: float = 72.0            # Strict floor: reject any clip below this
    strict_hook_floor: float = 6.0               # Minimum hook rating out of 10
    quality_cliff_drop: float = 12.0             # Score drop indicating a cliff

    # Duration scaling capacity thresholds (seconds)
    short_video_max_duration: float = 180.0      # < 3 mins -> 1-2 clips
    medium_video_max_duration: float = 900.0     # 3 - 15 mins -> 2-4 clips
    long_video_max_duration: float = 1800.0      # 15 - 30 mins -> 3-6 clips
    # > 30 mins -> up to 10 clips

    # Temporal separation bounds
    min_separation_short: float = 20.0           # Seconds between clips for short videos
    min_separation_medium: float = 30.0          # Seconds between clips for medium videos
    min_separation_long: float = 45.0            # Seconds between clips for long videos

    # Maximum global hard ceiling
    max_global_clips_ceiling: int = 12


@dataclass
class SolidShortsDecision:
    """Detailed result and audit log of the solid shorts decision."""
    recommended_count: int
    selected_candidates: List[HighlightCandidate]
    total_candidates_analyzed: int
    capacity_limit: int
    quality_floor: float
    reasons: List[str] = field(default_factory=list)
    quality_cliff_detected_at: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommended_count": self.recommended_count,
            "selected_candidate_ids": [c.candidate_id for c in self.selected_candidates],
            "total_candidates_analyzed": self.total_candidates_analyzed,
            "capacity_limit": self.capacity_limit,
            "quality_floor": self.quality_floor,
            "reasons": self.reasons,
            "quality_cliff_detected_at": self.quality_cliff_detected_at,
        }


class SolidShortsDecider:
    """
    Evaluates candidate highlight pools, source duration, and audience retention curves
    to determine the optimal count of solid, high-yield vertical Shorts.
    """

    def __init__(self, config: Optional[SolidShortsConfig] = None):
        self.config = config or SolidShortsConfig()

    def calculate_capacity_ceiling(self, duration_seconds: float) -> Tuple[int, float]:
        """
        Determines the maximum clip capacity and minimum temporal spacing
        based on the source video's duration.
        """
        dur = max(10.0, float(duration_seconds))
        if dur < self.config.short_video_max_duration:
            # Under 3 minutes: 1 to 2 clips max
            cap = 1 if dur < 90.0 else 2
            spacing = self.config.min_separation_short
        elif dur < self.config.medium_video_max_duration:
            # 3 to 15 minutes: 2 to 4 clips
            cap = min(4, max(2, int(dur / 180.0)))
            spacing = self.config.min_separation_medium
        elif dur < self.config.long_video_max_duration:
            # 15 to 30 minutes: 3 to 6 clips
            cap = min(6, max(3, int(dur / 240.0)))
            spacing = self.config.min_separation_long
        else:
            # 30+ minutes (podcasts, masterclasses): 4 to 10 clips
            cap = min(self.config.max_global_clips_ceiling, max(4, int(dur / 300.0) + 1))
            spacing = self.config.min_separation_long

        return cap, spacing

    def decide(
        self,
        candidates: List[HighlightCandidate],
        duration_seconds: float,
        heatmap_data: Optional[HeatmapData] = None,
        target_count: Optional[int] = None,
        strict_quality: bool = True,
    ) -> SolidShortsDecision:
        """
        Executes the 5-signal solid shorts decision algorithm.
        """
        if not candidates:
            return SolidShortsDecision(
                recommended_count=0,
                selected_candidates=[],
                total_candidates_analyzed=0,
                capacity_limit=1,
                quality_floor=self.config.solid_quality_floor,
                reasons=["No candidate highlights available."],
            )

        capacity, min_spacing = self.calculate_capacity_ceiling(duration_seconds)
        if target_count is not None and target_count > 0:
            capacity = target_count

        quality_floor = self.config.solid_quality_floor if strict_quality else 65.0
        reasons: List[str] = [
            f"Source duration: {duration_seconds:.1f}s -> Capacity ceiling: {capacity} clips (Min spacing: {min_spacing:.0f}s)."
        ]

        # 1. Rank candidates by effective score (incorporating audience retention boost)
        scored_pool: List[Tuple[float, HighlightCandidate, str]] = []
        for c in candidates:
            effective_score = float(c.score)
            retention_reason = "Base score"

            # Check retention peak alignment
            if heatmap_data and heatmap_data.peaks:
                for p in heatmap_data.peaks:
                    peak_time = getattr(p, "center_time", getattr(p, "timestamp", 0.0))
                    if c.start_seconds <= peak_time <= c.end_seconds:
                        intensity = getattr(p, "intensity", 0.0)
                        prominence = getattr(p, "prominence", 0.0)
                        if intensity >= 0.50 or prominence >= 0.20:
                            boost = min(8.0, 10.0 * intensity * (1.0 + prominence))
                            effective_score += boost
                            retention_reason = f"Audience peak at {peak_time:.1f}s (Intensity: {intensity*100:.0f}%, +{boost:.1f} boost)"
                            break

            scored_pool.append((effective_score, c, retention_reason))

        # Sort pool descending by effective score
        scored_pool.sort(key=lambda x: x[0], reverse=True)

        selected: List[HighlightCandidate] = []
        cliff_idx: Optional[int] = None

        for idx, (eff_score, cand, note) in enumerate(scored_pool, 1):
            if len(selected) >= capacity:
                reasons.append(f"Reached capacity limit of {capacity} clips.")
                break

            # 2. Quality Floor Check
            if eff_score < quality_floor:
                reasons.append(
                    f"Candidate #{idx} (Score {eff_score:.1f}) rejected: Below solid quality floor of {quality_floor:.1f}."
                )
                if cliff_idx is None:
                    cliff_idx = len(selected)
                break

            # 3. Hook Floor Check
            hook_val = 7.0
            if hasattr(cand, "breakdown") and cand.breakdown:
                hook_val = float(getattr(cand.breakdown, "hook_score", getattr(cand.breakdown, "hook_strength", 7.0)))
            elif hasattr(cand, "signals") and isinstance(cand.signals, dict):
                hook_val = float(cand.signals.get("hook", 7.0))

            if hook_val < self.config.strict_hook_floor:
                reasons.append(
                    f"Candidate #{idx} rejected: Hook score {hook_val:.1f}/10 is below threshold {self.config.strict_hook_floor:.1f}."
                )
                continue

            # 4. Temporal Spacing & Non-Overlapping Check against already accepted candidates
            has_temporal_collision = False
            for acc in selected:
                # Overlap check
                overlap_start = max(cand.start_seconds, acc.start_seconds)
                overlap_end = min(cand.end_seconds, acc.end_seconds)
                overlap_dur = max(0.0, overlap_end - overlap_start)
                min_cand_dur = min(cand.duration_seconds, acc.duration_seconds)

                if min_cand_dur > 0 and (overlap_dur / min_cand_dur) > 0.20:
                    has_temporal_collision = True
                    reasons.append(
                        f"Candidate #{idx} [{cand.start_seconds:.1f}s - {cand.end_seconds:.1f}s] suppressed: Overlaps accepted clip [{acc.start_seconds:.1f}s - {acc.end_seconds:.1f}s]."
                    )
                    break

            if has_temporal_collision:
                continue

            # 5. Statistical Quality Cliff Check (if we already have at least 1 clip)
            if selected and eff_score < self.config.tier_1_instant_viral_score:
                avg_selected_score = sum(c.score for c in selected) / len(selected)
                score_drop = avg_selected_score - eff_score
                if score_drop > self.config.quality_cliff_drop:
                    cliff_idx = len(selected)
                    reasons.append(
                        f"Quality Cliff detected at clip #{len(selected) + 1}: Score dropped by {score_drop:.1f} points (from avg {avg_selected_score:.1f} to {eff_score:.1f}). Halting extraction to preserve quality."
                    )
                    break

            # Passed all filters -> Accept as solid short
            selected.append(cand)
            reasons.append(
                f"Accepted Clip #{len(selected)}: [{cand.start_seconds:.1f}s - {cand.end_seconds:.1f}s] (Score: {eff_score:.1f}/100, {note})."
            )

        # Fallback: if no candidates passed strict floor, guarantee the single highest if it is at least viable
        if not selected and scored_pool:
            best_eff, best_cand, best_note = scored_pool[0]
            if best_eff >= 60.0:
                selected.append(best_cand)
                reasons.append(
                    f"Accepted top solitary candidate [{best_cand.start_seconds:.1f}s - {best_cand.end_seconds:.1f}s] as best available (Score: {best_eff:.1f}/100)."
                )

        return SolidShortsDecision(
            recommended_count=len(selected),
            selected_candidates=selected,
            total_candidates_analyzed=len(candidates),
            capacity_limit=capacity,
            quality_floor=quality_floor,
            reasons=reasons,
            quality_cliff_detected_at=cliff_idx,
        )


__all__ = [
    "SolidShortsConfig",
    "SolidShortsDecision",
    "SolidShortsDecider",
]
