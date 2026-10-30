"""
Best-in-Class YouTube Trend Analysis & Virality Prediction Engine.
Computes real-time View Velocity, Channel Baseline Normalization (outlier detection),
Engagement Virality Ratios (LVR, CVR), Composite Virality Index (CVI),
and polls official YouTube Trending Charts across regions and categories.
"""

from typing import List, Dict, Optional, Any
import os
import urllib.request
import json
from datetime import datetime, timezone
import math
from dotenv import load_dotenv

load_dotenv()

from ..contracts.models import (
    VideoCandidate,
    CreatorSource,
    TrendReport,
    RightsStatus,
)
from .monitor import APIQuotaBudget, parse_iso8601_duration


class TrendAnalyzer:
    """
    Evaluates YouTube video virality potential using statistical velocity modeling
    and audience engagement ratios.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        quota_budget: Optional[APIQuotaBudget] = None,
    ):
        self.api_key = api_key or os.getenv("YOUTUBE_API_KEY")
        self.quota_budget = quota_budget or APIQuotaBudget()

    def analyze_metrics(
        self,
        video_id: str,
        title: str,
        channel_id: str,
        channel_title: str,
        published_at_iso: str,
        view_count: int,
        like_count: int = 0,
        comment_count: int = 0,
        creator: Optional[CreatorSource] = None,
    ) -> TrendReport:
        """
        Computes comprehensive virality telemetry for any YouTube video.
        """
        now = datetime.now(timezone.utc)
        try:
            # Handle ISO string with trailing Z or timezone offset
            clean_iso = published_at_iso.replace("Z", "+00:00")
            pub_time = datetime.fromisoformat(clean_iso)
            if pub_time.tzinfo is None:
                pub_time = pub_time.replace(tzinfo=timezone.utc)
            age_hours = max((now - pub_time).total_seconds() / 3600.0, 0.25)
        except Exception:
            age_hours = 24.0

        # 1. Hourly View Velocity
        velocity = float(view_count) / age_hours

        # 2. Channel Baseline Normalization
        baseline_total = creator.baseline_views if creator else 25000.0
        # Assume standard 48-hour video maturity cycle for creator baseline
        baseline_hourly_velocity = max(baseline_total / 48.0, 10.0)
        velocity_multiplier = velocity / baseline_hourly_velocity

        # 3. Audience Engagement Ratios
        safe_views = max(view_count, 1)
        like_ratio = (float(like_count) / safe_views) * 100.0
        comment_ratio = (float(comment_count) / safe_views) * 100.0

        # 4. Composite Virality Index (CVI) 0 to 100
        # Weights:
        # - Velocity Multiplier vs Channel Baseline: 45% (capped at 3.0x multiplier)
        # - Like-to-View Ratio: 30% (viral threshold benchmark = 5.0%)
        # - Comment-to-View Ratio: 25% (viral threshold benchmark = 0.35%)
        score_velocity = min(velocity_multiplier / 3.0, 1.0) * 45.0
        score_likes = min(like_ratio / 5.0, 1.0) * 30.0
        score_comments = min(comment_ratio / 0.35, 1.0) * 25.0
        virality_index = round(min(score_velocity + score_likes + score_comments, 100.0), 1)

        # 5. Outlier Classification
        if velocity_multiplier >= 3.0 or virality_index >= 85.0:
            classification = "VIRAL_EXPLOSION"
            summary = (
                f"Breakout outlier performing at {velocity_multiplier:.1f}x channel baseline. "
                f"Velocity: {velocity:,.0f} views/hr. High audience resonance (LVR={like_ratio:.1f}%)."
            )
        elif velocity_multiplier >= 1.8 or virality_index >= 70.0:
            classification = "TRENDING_HIGH"
            summary = (
                f"Strong traction at {velocity_multiplier:.1f}x channel baseline. "
                f"Velocity: {velocity:,.0f} views/hr."
            )
        elif velocity_multiplier >= 1.2 or (velocity_multiplier >= 1.0 and virality_index >= 60.0):
            classification = "ABOVE_AVERAGE"
            summary = f"Above average momentum ({velocity_multiplier:.1f}x baseline). Steady engagement."
        elif velocity_multiplier >= 0.8:
            classification = "STEADY"
            summary = "Consistent with normal channel baseline velocity."
        else:
            classification = "UNDERPERFORMING"
            summary = f"Pacing below expected baseline ({velocity_multiplier:.2f}x)."

        return TrendReport(
            video_id=video_id,
            title=title,
            channel_id=channel_id,
            channel_title=channel_title,
            published_at=published_at_iso,
            view_count=view_count,
            like_count=like_count,
            comment_count=comment_count,
            view_velocity_per_hour=round(velocity, 1),
            channel_baseline_velocity=round(baseline_hourly_velocity, 1),
            velocity_multiplier=round(velocity_multiplier, 2),
            like_ratio_pct=round(like_ratio, 2),
            comment_ratio_pct=round(comment_ratio, 3),
            virality_index=virality_index,
            classification=classification,
            rationale=summary,
        )

    def analyze_video_id(
        self,
        video_id: str,
        creator: Optional[CreatorSource] = None,
    ) -> Optional[TrendReport]:
        """
        Fetches live video statistics via YouTube Data API v3 and evaluates virality.
        """
        if not self.api_key:
            return None

        try:
            self.quota_budget.spend(APIQuotaBudget.COST_VIDEOS_LIST)
            url = (
                f"https://www.googleapis.com/youtube/v3/videos"
                f"?part=snippet,contentDetails,statistics&id={video_id}&key={self.api_key}"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            items = data.get("items", [])
            if not items:
                return None

            item = items[0]
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})

            return self.analyze_metrics(
                video_id=video_id,
                title=snippet.get("title", ""),
                channel_id=snippet.get("channelId", ""),
                channel_title=snippet.get("channelTitle", ""),
                published_at_iso=snippet.get("publishedAt", ""),
                view_count=int(stats.get("viewCount", 0)),
                like_count=int(stats.get("likeCount", 0)),
                comment_count=int(stats.get("commentCount", 0)),
                creator=creator,
            )
        except Exception:
            return None

    def fetch_trending_chart(
        self,
        region_code: str = "US",
        category_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[TrendReport]:
        """
        Queries official YouTube Trending Charts via YouTube Data API v3 (1 quota unit)
        and ranks discovered videos by Composite Virality Index.
        """
        if not self.api_key:
            return []

        try:
            self.quota_budget.spend(APIQuotaBudget.COST_VIDEOS_LIST)
            cat_param = f"&videoCategoryId={category_id}" if category_id else ""
            url = (
                f"https://www.googleapis.com/youtube/v3/videos"
                f"?part=snippet,statistics&chart=mostPopular&regionCode={region_code}"
                f"&maxResults={min(limit, 50)}{cat_param}&key={self.api_key}"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            reports: List[TrendReport] = []
            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                report = self.analyze_metrics(
                    video_id=item.get("id", ""),
                    title=snippet.get("title", ""),
                    channel_id=snippet.get("channelId", ""),
                    channel_title=snippet.get("channelTitle", ""),
                    published_at_iso=snippet.get("publishedAt", ""),
                    view_count=int(stats.get("viewCount", 0)),
                    like_count=int(stats.get("likeCount", 0)),
                    comment_count=int(stats.get("commentCount", 0)),
                )
                reports.append(report)

            # Sort descending by virality index
            reports.sort(key=lambda r: r.virality_index, reverse=True)
            return reports[:limit]
        except Exception:
            return []
