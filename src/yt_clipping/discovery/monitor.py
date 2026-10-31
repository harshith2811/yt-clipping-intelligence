"""
Channel Monitor and Video Discovery Ingestion Layer.
Supports channel handle (@handle) and custom URL resolution,
resilient RSS/Atom HTTP client with ETag and 304 caching,
centralized quota management, and channel registry persistence.
"""

from typing import List, Dict, Optional, Set, Tuple, Any
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import json
import os
import re
import time
import urllib.request
import urllib.error
from urllib.parse import urlparse

from ..contracts.models import CreatorSource, VideoCandidate, RightsStatus
from ..contracts.interfaces import DiscoveryProvider
from .quota_governor import APIQuotaGovernor


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

    def __init__(self, daily_limit: int = DAILY_DEFAULT_LIMIT, db_path: Optional[str] = None):
        self.daily_limit = daily_limit
        self.units_spent: int = 0
        self.last_reset = datetime.now(timezone.utc).date()
        self.governor = APIQuotaGovernor(daily_limit=daily_limit, db_path=db_path) if db_path else None

    def _check_reset(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today > self.last_reset:
            self.units_spent = 0
            self.last_reset = today

    def can_spend(self, cost: int) -> bool:
        self._check_reset()
        if self.governor:
            return self.governor.can_spend(cost)
        return (self.units_spent + cost) <= self.daily_limit

    def spend(self, cost: int) -> None:
        self._check_reset()
        if not self.can_spend(cost):
            raise RuntimeError(
                f"YouTube Data API quota exceeded! Spent: {self.units_spent}, Requested: {cost}, Limit: {self.daily_limit}"
            )
        self.units_spent += cost
        if self.governor:
            self.governor.spend("v3_legacy", cost)


class RSSFeedClient:
    """
    HTTP client for YouTube creator RSS/Atom feeds.
    Implements ETag caching, If-None-Match, If-Modified-Since, HTTP 304 handling,
    and bounded exponential backoff retries.
    """

    def __init__(self, timeout: int = 10, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._cache: Dict[str, Dict[str, Any]] = {}  # channel_id -> {"etag": ..., "modified": ..., "xml": ...}

    def fetch_feed(self, channel_id: str) -> Tuple[Optional[str], bool]:
        """
        Fetches channel Atom feed.
        Returns (xml_content, was_modified).
        If HTTP 304 (Not Modified), returns (cached_xml, False).
        """
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Antigravity-Monitor/1.0"}

        cached = self._cache.get(channel_id, {})
        if "etag" in cached:
            headers["If-None-Match"] = cached["etag"]
        if "modified" in cached:
            headers["If-Modified-Since"] = cached["modified"]

        for attempt in range(1, self.max_retries + 1):
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    code = resp.getcode()
                    if code == 304:
                        return cached.get("xml"), False

                    xml_bytes = resp.read()
                    xml_str = xml_bytes.decode("utf-8", errors="replace")
                    etag = resp.headers.get("ETag")
                    last_mod = resp.headers.get("Last-Modified")

                    self._cache[channel_id] = {
                        "etag": etag,
                        "modified": last_mod,
                        "xml": xml_str,
                    }
                    return xml_str, True

            except urllib.error.HTTPError as he:
                if he.code == 304:
                    return cached.get("xml"), False
                if attempt == self.max_retries or (400 <= he.code < 500 and he.code != 429):
                    raise
            except Exception:
                if attempt == self.max_retries:
                    raise

            time.sleep(0.5 * (2 ** (attempt - 1)))

        return None, False


class ChannelMonitor(DiscoveryProvider):
    """
    Monitors creators, polls their uploads via RSS/Atom or Data API,
    resolves handles and custom URLs, and deduplicates candidates.
    """

    def __init__(
        self,
        quota_budget: Optional[APIQuotaBudget] = None,
        api_key: Optional[str] = None,
        rss_client: Optional[RSSFeedClient] = None,
        db_path: Optional[str] = None,
    ):
        self.quota_budget = quota_budget or APIQuotaBudget(db_path=db_path)
        self.api_key = api_key or os.getenv("YOUTUBE_API_KEY")
        self.rss_client = rss_client or RSSFeedClient()
        self.creators: Dict[str, CreatorSource] = {}
        self.seen_video_ids: Set[str] = set()
        self._mock_registry: Dict[str, List[VideoCandidate]] = {}
        self._resolved_handles: Dict[str, str] = {}

    def register_creator(self, creator: CreatorSource) -> None:
        """Adds a creator to the monitoring registry."""
        self.creators[creator.channel_id] = creator

    def register_mock_video(self, channel_id: str, video: VideoCandidate) -> None:
        """Used for testing and offline fixture simulation."""
        if channel_id not in self._mock_registry:
            self._mock_registry[channel_id] = []
        self._mock_registry[channel_id].append(video)

    def resolve_channel_id(self, identifier: str) -> str:
        """
        BUG-03 fix: Resolves channel IDs, @handles, channel URLs, or custom URLs
        to canonical 'UC...' channel IDs.
        """
        ident = identifier.strip()

        # Check memory cache or mock registry
        if ident in self._resolved_handles:
            return self._resolved_handles[ident]
        if ident in self._mock_registry:
            return ident

        # 1. Already a canonical channel ID or test mock ID starting with UC
        if ident.startswith("UC") and "/" not in ident and not ident.startswith("@"):
            return ident

        # 2. Extract handle or ID from URL
        clean_handle = None
        if "youtube.com" in ident or "youtu.be" in ident:
            parsed = urlparse(ident)
            path = parsed.path.strip("/")
            if path.startswith("channel/UC"):
                cid = path.split("/")[1]
                self._resolved_handles[ident] = cid
                return cid
            elif path.startswith("@"):
                clean_handle = path.split("/")[0]
            elif path.startswith("c/") or path.startswith("user/"):
                clean_handle = "@" + path.split("/")[1]
        elif ident.startswith("@"):
            clean_handle = ident
        else:
            clean_handle = f"@{ident}"

        # 3. Resolve handle via YouTube Data API v3 if API key available
        if self.api_key and clean_handle:
            try:
                self.quota_budget.spend(APIQuotaBudget.COST_CHANNELS_LIST)
                handle_query = clean_handle.lstrip("@")
                url = (
                    f"https://www.googleapis.com/youtube/v3/channels"
                    f"?part=id,snippet&forHandle={handle_query}&key={self.api_key}"
                )
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    items = data.get("items", [])
                    if items:
                        resolved_id = items[0]["id"]
                        self._resolved_handles[ident] = resolved_id
                        self._resolved_handles[clean_handle] = resolved_id
                        return resolved_id
            except Exception:
                pass

        # 4. Fallback: Parse channel page metadata for external ID
        if clean_handle:
            try:
                page_url = f"https://www.youtube.com/{clean_handle}"
                req = urllib.request.Request(page_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    html = resp.read().decode("utf-8", errors="replace")
                    match = re.search(r'"channelId":"(UC[A-Za-z0-9_-]{22})"', html)
                    if not match:
                        match = re.search(r'data-channel-external-id="(UC[A-Za-z0-9_-]{22})"', html)
                    if match:
                        resolved_id = match.group(1)
                        self._resolved_handles[ident] = resolved_id
                        self._resolved_handles[clean_handle] = resolved_id
                        return resolved_id
            except Exception:
                pass

        raise ValueError(
            f"Could not resolve channel identifier '{identifier}' to a valid YouTube channel ID. "
            "Please provide a canonical UC... channel ID or verify API key configuration."
        )

    def fetch_recent_videos(self, channel_identifier: str, limit: int = 10) -> List[VideoCandidate]:
        """
        Polls the channel's latest uploads using YouTube Data API or RSS fallback.
        Resolves handles and custom URLs before querying.
        """
        # Resolve identifier if necessary
        try:
            channel_id = self.resolve_channel_id(channel_identifier)
        except ValueError:
            channel_id = channel_identifier

        # Mock mode / offline fixtures
        if channel_id in self._mock_registry:
            self.quota_budget.spend(APIQuotaBudget.COST_PLAYLIST_ITEMS_LIST)
            candidates = self._mock_registry[channel_id]
            unseen = [c for c in candidates if c.video_id not in self.seen_video_ids][:limit]
            for c in unseen:
                self.seen_video_ids.add(c.video_id)
            return unseen

        # Live Data API v3 query if API key configured and channel_id is valid
        if self.api_key and channel_id.startswith("UC"):
            try:
                self.quota_budget.spend(APIQuotaBudget.COST_PLAYLIST_ITEMS_LIST)
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

        # BUG-04 fix: RSS fallback (zero API quota cost)
        if channel_id.startswith("UC"):
            try:
                xml_content, _ = self.rss_client.fetch_feed(channel_id)
                if xml_content:
                    return self.parse_channel_rss(xml_content, channel_id)[:limit]
            except Exception:
                pass

        return []

    def get_video_metadata(self, video_id: str) -> Optional[VideoCandidate]:
        """Fetches metadata for a single video."""
        for v_list in self._mock_registry.values():
            for v in v_list:
                if v.video_id == video_id:
                    return v

        if self.api_key:
            try:
                self.quota_budget.spend(APIQuotaBudget.COST_VIDEOS_LIST)
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
        """
        if not rss_xml_content:
            return []

        candidates: List[VideoCandidate] = []
        try:
            root = ET.fromstring(rss_xml_content)
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
