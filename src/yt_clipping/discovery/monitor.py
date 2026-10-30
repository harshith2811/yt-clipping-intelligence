"""
Channel Monitor and Video Discovery Ingestion Layer.
Supports YouTube Data API quota management, channel registries, deduplication,
and compliant feed-based ingestion.
"""

from typing import List, Dict, Optional, Set
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import json
import os
import re
import urllib.request
from ..contracts.models import CreatorSource, VideoCandidate, RightsStatus
from ..contracts.interfaces import DiscoveryProvider


def parse_iso8601_duration(dur_str: str) -> float:
    """Parses ISO 8601 duration format (e.g. PT34M10S) into total seconds."""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur_str)
    if not match:
        return 0.0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return float(hours * 3600 + minutes * 60 + seconds)


class APIQuotaBudget:
    """Tracks and caps YouTube Data API v3 quota usage per 24-hour cycle."""

    DAILY_DEFAULT_LIMIT = 10000

    COST_SEARCH_LIST = 100
    COST_VIDEOS_LIST = 1
    COST_PLAYLIST_ITEMS_LIST = 1
    COST_CHANNELS_LIST = 1

    def __init__(self, daily_limit: int = DAILY_DEFAULT_LIMIT):
        self.daily_limit = daily_limit
        self.units_spent: int = 0
        self.last_reset = datetime.now(timezone.utc).date()

    def _check_reset(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today > self.last_reset:
            self.units_spent = 0
            self.last_reset = today

    def can_spend(self, cost: int) -> bool:
        self._check_reset()
        return (self.units_spent + cost) <= self.daily_limit

    def spend(self, cost: int) -> None:
        self._check_reset()
        if not self.can_spend(cost):
            raise RuntimeError(
                f"YouTube Data API quota exceeded! Spent: {self.units_spent}, Requested: {cost}, Limit: {self.daily_limit}"
            )
        self.units_spent += cost


class ChannelMonitor(DiscoveryProvider):
    """
    Monitors a configurable list of creators, polls their uploads,
    and deduplicates ingested candidates against a local cache.
    """

    def __init__(self, quota_budget: Optional[APIQuotaBudget] = None, api_key: Optional[str] = None):
        self.quota_budget = quota_budget or APIQuotaBudget()
        self.api_key = api_key or os.getenv("YOUTUBE_API_KEY")
        self.creators: Dict[str, CreatorSource] = {}
        self.seen_video_ids: Set[str] = set()
        self._mock_registry: Dict[str, List[VideoCandidate]] = {}

    def register_creator(self, creator: CreatorSource) -> None:
        """Adds a creator to the monitoring registry."""
        self.creators[creator.channel_id] = creator

    def register_mock_video(self, channel_id: str, video: VideoCandidate) -> None:
        """Used for testing and offline fixture simulation."""
        if channel_id not in self._mock_registry:
            self._mock_registry[channel_id] = []
        self._mock_registry[channel_id].append(video)

    def fetch_recent_videos(self, channel_id: str, limit: int = 10) -> List[VideoCandidate]:
        """
        Polls the channel's latest uploads.
        Complies with quota guidelines: uses playlistItems.list (1 unit) instead of search.list (100 units).
        """
        self.quota_budget.spend(APIQuotaBudget.COST_PLAYLIST_ITEMS_LIST)

        # In offline/mock mode or unit tests, return registered mock videos
        if channel_id in self._mock_registry:
            candidates = self._mock_registry[channel_id]
            unseen = [c for c in candidates if c.video_id not in self.seen_video_ids][:limit]
            for c in unseen:
                self.seen_video_ids.add(c.video_id)
            return unseen

        # Live YouTube Data API v3 query if API key is configured
        if self.api_key and channel_id.startswith("UC"):
            try:
                uploads_playlist_id = "UU" + channel_id[2:]
                url = (
                    f"https://www.googleapis.com/youtube/v3/playlistItems"
                    f"?part=snippet&playlistId={uploads_playlist_id}&maxResults={min(limit, 50)}&key={self.api_key}"
                )
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                
                now = datetime.now(timezone.utc).isoformat()
                candidates = []
                for item in data.get("items", []):
                    vid = item["snippet"]["resourceId"]["videoId"]
                    if vid in self.seen_video_ids:
                        continue
                    self.seen_video_ids.add(vid)
                    candidates.append(
                        VideoCandidate(
                            video_id=vid,
                            title=item["snippet"]["title"],
                            url=f"https://www.youtube.com/watch?v={vid}",
                            creator_id=channel_id,
                            published_at=item["snippet"]["publishedAt"],
                            retrieved_at=now,
                            duration_seconds=0.0,
                            view_count=0,
                            rights_status=RightsStatus.PENDING_REVIEW,
                            discovery_rationale="Discovered via YouTube Data API v3 playlistItems.list.",
                        )
                    )
                return candidates[:limit]
            except Exception:
                pass

        # Return empty list if no live network adapter is configured
        return []

    def get_video_metadata(self, video_id: str) -> Optional[VideoCandidate]:
        """Fetches metadata for a single video (1 unit cost)."""
        self.quota_budget.spend(APIQuotaBudget.COST_VIDEOS_LIST)
        for v_list in self._mock_registry.values():
            for v in v_list:
                if v.video_id == video_id:
                    return v

        # Live YouTube Data API v3 query if API key is configured
        if self.api_key:
            try:
                url = (
                    f"https://www.googleapis.com/youtube/v3/videos"
                    f"?part=snippet,contentDetails,statistics&id={video_id}&key={self.api_key}"
                )
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                items = data.get("items", [])
                if items:
                    item = items[0]
                    snippet = item.get("snippet", {})
                    stats = item.get("statistics", {})
                    details = item.get("contentDetails", {})
                    dur_str = details.get("duration", "")
                    dur_sec = parse_iso8601_duration(dur_str)

                    return VideoCandidate(
                        video_id=video_id,
                        title=snippet.get("title", ""),
                        url=f"https://www.youtube.com/watch?v={video_id}",
                        creator_id=snippet.get("channelId", ""),
                        published_at=snippet.get("publishedAt", ""),
                        retrieved_at=datetime.now(timezone.utc).isoformat(),
                        duration_seconds=dur_sec,
                        view_count=int(stats.get("viewCount", 0)),
                        like_count=int(stats.get("likeCount", 0)),
                        comment_count=int(stats.get("commentCount", 0)),
                        rights_status=RightsStatus.PENDING_REVIEW,
                        discovery_rationale="Retrieved via YouTube Data API v3 videos.list.",
                    )
            except Exception:
                pass

        return None

    def parse_channel_rss(self, rss_xml_content: str, channel_id: str) -> List[VideoCandidate]:
        """
        Parses public YouTube Atom/RSS feed without consuming Data API quota.
        Yields clean, compliant candidates from official feeds.
        """
        candidates: List[VideoCandidate] = []
        try:
            root = ET.fromstring(rss_xml_content)
            # Atom namespace
            ns = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
            entries = root.findall("atom:entry", ns)
            now = datetime.now(timezone.utc).isoformat()
            for entry in entries:
                vid_elem = entry.find("yt:videoId", ns)
                title_elem = entry.find("atom:title", ns)
                published_elem = entry.find("atom:published", ns)
                if vid_elem is not None and title_elem is not None:
                    vid = vid_elem.text or ""
                    if vid and vid not in self.seen_video_ids:
                        cand = VideoCandidate(
                            video_id=vid,
                            title=title_elem.text or "Untitled",
                            url=f"https://www.youtube.com/watch?v={vid}",
                            creator_id=channel_id,
                            published_at=published_elem.text if published_elem is not None else now,
                            retrieved_at=now,
                            duration_seconds=0.0,
                            view_count=0,
                            rights_status=RightsStatus.PENDING_REVIEW,
                            discovery_rationale="Discovered via compliant channel RSS feed.",
                        )
                        candidates.append(cand)
                        self.seen_video_ids.add(vid)
        except Exception:
            pass
        return candidates
