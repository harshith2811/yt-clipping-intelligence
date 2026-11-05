"""
Dual-Engine YouTube Video Metadata Ingestion Service.
Supports YouTube Data API v3 with automatic cascading fallback to yt-dlp metadata-only extraction.
Enforces strict URL normalization, canonical video ID resolution, and SSRF protection.
"""

from __future__ import annotations
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs
import os
import re
import json
import logging
import time
import urllib.request
import urllib.error
import socket

logger = logging.getLogger(__name__)

# Strict 11-character YouTube video ID regex
YOUTUBE_ID_REGEX = re.compile(r"^[A-Za-z0-9_-]{11}$")

# Allowed YouTube hostnames for SSRF protection
ALLOWED_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "gaming.youtube.com",
    "youtu.be",
}

# ISO 8601 duration regex (e.g. PT1H2M10S, PT15M33S, PT45S)
ISO_DURATION_REGEX = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)


def parse_iso8601_duration(duration_str: str) -> float:
    """Parses an ISO 8601 duration string into total seconds."""
    if not duration_str:
        return 0.0
    match = ISO_DURATION_REGEX.match(duration_str)
    if not match:
        return 0.0
    d = match.groupdict()
    days = float(d.get("days") or 0)
    hours = float(d.get("hours") or 0)
    minutes = float(d.get("minutes") or 0)
    seconds = float(d.get("seconds") or 0)
    return days * 86400.0 + hours * 3600.0 + minutes * 60.0 + seconds


def normalize_youtube_url(url_or_id: str) -> tuple[str, str]:
    """
    Normalizes a YouTube URL, short link, embed link, or bare 11-char ID into:
    (canonical_video_id, canonical_url).

    Rejects invalid hosts, malformed IDs, IP addresses, and unsupported domains (SSRF protection).
    """
    if not url_or_id or not isinstance(url_or_id, str):
        raise ValueError("URL or video ID must be a non-empty string.")

    cleaned = url_or_id.strip()
    if not cleaned:
        raise ValueError("URL or video ID must not be empty or whitespace only.")

    # 1. Bare 11-character video ID
    if YOUTUBE_ID_REGEX.fullmatch(cleaned):
        video_id = cleaned
        return video_id, f"https://www.youtube.com/watch?v={video_id}"

    # 2. Parse URL
    if "://" not in cleaned:
        # Prepend https for parsing if omitted
        cleaned = "https://" + cleaned

    try:
        parsed = urlparse(cleaned)
    except Exception as e:
        raise ValueError(f"Malformed URL: {e}")

    # Enforce safe schemes
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme '{parsed.scheme}'. Only http and https are permitted.")

    hostname = (parsed.hostname or "").lower()

    # SSRF Protection: Check against allowed YouTube hostnames
    if hostname not in ALLOWED_YOUTUBE_HOSTS and not any(hostname.endswith("." + h) for h in ALLOWED_YOUTUBE_HOSTS):
        raise ValueError(
            f"Security Exception: Hostname '{hostname}' is not a recognized YouTube domain. "
            "Arbitrary URL fetching and internal network addressing are forbidden."
        )

    video_id: Optional[str] = None

    # Handle youtu.be/<id>
    if "youtu.be" in hostname:
        parts = parsed.path.strip("/").split("/")
        if parts and YOUTUBE_ID_REGEX.fullmatch(parts[0]):
            video_id = parts[0]

    # Handle youtube.com/*
    elif "youtube.com" in hostname:
        path = parsed.path.rstrip("/")
        if path == "/watch":
            qs = parse_qs(parsed.query)
            v_val = qs.get("v")
            if v_val and YOUTUBE_ID_REGEX.fullmatch(v_val[0]):
                video_id = v_val[0]
        elif path.startswith(("/shorts/", "/live/", "/embed/", "/v/")):
            parts = path.strip("/").split("/")
            if len(parts) >= 2 and YOUTUBE_ID_REGEX.fullmatch(parts[1]):
                video_id = parts[1]

    if not video_id or not YOUTUBE_ID_REGEX.fullmatch(video_id):
        raise ValueError(f"Could not extract a valid 11-character YouTube video ID from: '{url_or_id}'")

    canonical_url = f"https://www.youtube.com/watch?v={video_id}"
    return video_id, canonical_url


@dataclass
class EnrichedVideoInfo:
    """
    Typed, immutable data model representing complete YouTube video metadata.
    """
    video_id: str
    title: str = ""
    description: str = ""
    channel_title: str = "Unknown Creator"
    channel_handle: Optional[str] = None
    channel_id: Optional[str] = None
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    published_at: str = ""
    duration: float = 0.0
    category: str = ""
    tags: List[str] = field(default_factory=list)
    thumbnail_url: str = ""
    canonical_url: str = ""
    metadata_provider: str = "unknown"
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    extraction_status: str = "success"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EnrichedVideoInfo:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class VideoMetadataService:
    """
    Dual-engine ingestion service for YouTube video metadata.
    Attempts primary ingestion via YouTube Data API v3; seamlessly cascades
    to yt-dlp metadata-only extraction if the API key is absent, quota is depleted,
    or network connectivity fails.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_dir: str = "data/cache/metadata",
        timeout: int = 15,
        max_retries: int = 2,
    ):
        if api_key is not None:
            self.api_key = api_key
        else:
            self.api_key = os.getenv("YOUTUBE_API_KEY")
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.max_retries = max_retries
        os.makedirs(self.cache_dir, exist_ok=True)

    def get_metadata(
        self,
        url_or_id: str,
        use_cache: bool = True,
        force_provider: Optional[str] = None,
    ) -> EnrichedVideoInfo:
        """
        Retrieves normalized video metadata.
        Resolves canonical URL/ID first, checks cache, tries YouTube Data API v3,
        then cascades to yt-dlp.
        """
        video_id, canonical_url = normalize_youtube_url(url_or_id)

        # 1. Cache lookup
        if use_cache and not force_provider:
            cached = self._read_cache(video_id)
            if cached:
                logger.info(f"Loaded metadata from cache for {video_id}")
                return cached

        # 2. Primary: YouTube Data API v3
        if force_provider != "yt_dlp" and self.api_key:
            try:
                info = self._fetch_youtube_data_api(video_id, canonical_url)
                if info:
                    self._write_cache(video_id, info)
                    return info
            except Exception as e:
                logger.warning(
                    f"YouTube Data API v3 lookup failed for {video_id} ({e}). "
                    "Cascading to yt-dlp metadata extraction fallback."
                )

        # 3. Fallback: yt-dlp metadata-only extraction
        try:
            info = self._fetch_ytdlp_metadata(video_id, canonical_url)
            self._write_cache(video_id, info)
            return info
        except Exception as e:
            logger.error(f"yt-dlp metadata extraction also failed for {video_id}: {e}")
            # Construct a safe degraded record rather than crashing if title/ID are known
            return EnrichedVideoInfo(
                video_id=video_id,
                title=f"YouTube Video {video_id}",
                description="",
                channel_title="Unknown Creator",
                canonical_url=canonical_url,
                thumbnail_url=f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                metadata_provider="failed_fallback",
                extraction_status=f"error: {str(e)}",
            )

    def _fetch_youtube_data_api(self, video_id: str, canonical_url: str) -> Optional[EnrichedVideoInfo]:
        """Queries YouTube Data API v3 videos endpoint."""
        endpoint = (
            f"https://www.googleapis.com/youtube/v3/videos"
            f"?part=snippet,contentDetails,statistics"
            f"&id={video_id}&key={self.api_key}"
        )

        req = urllib.request.Request(
            endpoint,
            headers={"User-Agent": "YouTubeClippingStudio/2.0"},
        )

        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        items = data.get("items", [])
                        if not items:
                            logger.warning(f"YouTube Data API returned 0 items for video {video_id}")
                            return None
                        item = items[0]
                        snippet = item.get("snippet", {})
                        content_details = item.get("contentDetails", {})
                        statistics = item.get("statistics", {})

                        # Thumbnail resolution selection
                        thumbs = snippet.get("thumbnails", {})
                        thumb_url = (
                            thumbs.get("maxres", {}).get("url")
                            or thumbs.get("standard", {}).get("url")
                            or thumbs.get("high", {}).get("url")
                            or thumbs.get("default", {}).get("url")
                            or f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
                        )

                        duration_seconds = parse_iso8601_duration(content_details.get("duration", ""))

                        return EnrichedVideoInfo(
                            video_id=video_id,
                            title=snippet.get("title", ""),
                            description=snippet.get("description", ""),
                            channel_title=snippet.get("channelTitle", ""),
                            channel_handle=None,  # Not directly in videos endpoint; can be augmented if needed
                            channel_id=snippet.get("channelId"),
                            view_count=int(statistics.get("viewCount", 0)),
                            like_count=int(statistics.get("likeCount", 0)),
                            comment_count=int(statistics.get("commentCount", 0)),
                            published_at=snippet.get("publishedAt", ""),
                            duration=duration_seconds,
                            category=snippet.get("categoryId", ""),
                            tags=snippet.get("tags", []),
                            thumbnail_url=thumb_url,
                            canonical_url=canonical_url,
                            metadata_provider="youtube_data_api_v3",
                            extraction_status="success",
                        )
            except urllib.error.HTTPError as e:
                if e.code in (400, 401, 403, 404, 429):
                    logger.warning(f"YouTube Data API error ({e.code}): {e.reason}")
                    raise
                elif attempt < self.max_retries:
                    time.sleep(0.5 * (2 ** attempt))
                else:
                    raise
            except Exception as e:
                if attempt < self.max_retries:
                    time.sleep(0.5 * (2 ** attempt))
                else:
                    raise

        return None

    def _fetch_ytdlp_metadata(self, video_id: str, canonical_url: str) -> EnrichedVideoInfo:
        """Fetches metadata-only using yt-dlp without downloading media."""
        import yt_dlp

        ydl_opts = {
            "skip_download": True,
            "extract_flat": False,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": self.timeout,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(canonical_url, download=False)

        if not info:
            raise RuntimeError(f"yt-dlp returned empty info dict for {canonical_url}")

        raw_handle = info.get("channel_handle") or info.get("uploader_id")
        channel_id = info.get("channel_id")
        channel_handle: Optional[str] = None
        if raw_handle:
            h_str = str(raw_handle).strip()
            # If the handle is just the UC... channel ID or equals channel_id, it is not a genuine handle
            if not h_str.startswith("UC") and h_str != channel_id:
                channel_handle = h_str if h_str.startswith("@") else f"@{h_str}"

        thumb_url = info.get("thumbnail") or f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"

        categories = info.get("categories") or []
        category = categories[0] if categories else ""

        return EnrichedVideoInfo(
            video_id=video_id,
            title=info.get("title", f"Video {video_id}"),
            description=info.get("description", ""),
            channel_title=info.get("uploader") or info.get("channel") or "Unknown Creator",
            channel_handle=channel_handle,
            channel_id=info.get("channel_id"),
            view_count=int(info.get("view_count") or 0),
            like_count=int(info.get("like_count") or 0),
            comment_count=int(info.get("comment_count") or 0),
            published_at=str(info.get("upload_date") or ""),
            duration=float(info.get("duration") or 0.0),
            category=category,
            tags=info.get("tags") or [],
            thumbnail_url=thumb_url,
            canonical_url=canonical_url,
            metadata_provider="yt_dlp",
            extraction_status="success",
        )

    def _read_cache(self, video_id: str) -> Optional[EnrichedVideoInfo]:
        cache_path = os.path.join(self.cache_dir, f"{video_id}.json")
        if not os.path.exists(cache_path):
            return None
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return EnrichedVideoInfo.from_dict(data)
        except Exception as e:
            logger.warning(f"Corrupted metadata cache file {cache_path}: {e}")
            return None

    def _write_cache(self, video_id: str, info: EnrichedVideoInfo) -> None:
        cache_path = os.path.join(self.cache_dir, f"{video_id}.json")
        tmp_path = f"{cache_path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(info.to_dict(), f, indent=2)
            os.replace(tmp_path, cache_path)
        except Exception as e:
            logger.warning(f"Failed to write metadata cache for {video_id}: {e}")
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
