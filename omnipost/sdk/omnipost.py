"""
OmniPost Universal Python SDK

Lightweight, zero-dependency client for OmniPost Social Media Automation & Publishing Engine.
Compatible with Python 3.8+ using standard library (urllib) or requests if available.

Example:
    from sdk.omnipost import OmniPost

    client = OmniPost(base_url="http://localhost:3300", api_key="my_secret_key")

    # 1. Preflight status check
    status = client.preflight()
    print("Ready channels:", status.get("readyToPublish"))

    # 2. Publish post immediately
    res = client.publish(
        title="Python Announcement",
        caption="Publishing from Python to LinkedIn and Instagram with ease! #python",
        media_url="https://example.com/video.mp4",
        platforms=["linkedin", "instagram"]
    )
    print("Published:", res)
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Union


class OmniPostError(Exception):
    """Exception raised for errors in OmniPost API calls."""

    def __init__(self, message: str, status: int = 500, code: str = "OMNIPOST_ERROR", details: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details


class OmniPost:
    """OmniPost Client for Python."""

    def __init__(
        self,
        base_url: str = "http://localhost:3300",
        api_key: Optional[str] = None,
        timeout: int = 30
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("AUTOMATION_SECRET_KEY") or os.environ.get("CHAMBERS_ADMIN_SECRET_KEY") or ""
        self.timeout = timeout

    def _request(self, endpoint: str, method: str = "GET", data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {
            "Accept": "application/json",
            "User-Agent": "OmniPost-Python-SDK/1.0"
        }

        if self.api_key:
            headers["x-api-key"] = self.api_key

        payload = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(data).encode("utf-8")

        req = urllib.request.Request(url, data=payload, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            try:
                err_data = json.loads(err_body)
                msg = err_data.get("message") or err_data.get("error") or str(e)
                code = err_data.get("code") or f"HTTP_{e.code}"
            except Exception:
                err_data = {"raw": err_body}
                msg = str(e)
                code = f"HTTP_{e.code}"
            raise OmniPostError(msg, status=e.code, code=code, details=err_data)
        except urllib.error.URLError as e:
            raise OmniPostError(f"Network error connecting to OmniPost: {e.reason}", status=502, code="NETWORK_ERROR")

    def preflight(self) -> Dict[str, Any]:
        """Check system readiness and which social platforms are armed and ready."""
        return self._request("/api/engine/preflight")

    def get_channels(self) -> Dict[str, Any]:
        """Get inventory of all supported channels and their configuration status."""
        return self._request("/api/channels")

    def publish(
        self,
        caption: str,
        title: str = "",
        media_url: str = "",
        media_type: str = "",
        platforms: Optional[Union[List[str], str]] = None,
        link: str = ""
    ) -> Dict[str, Any]:
        """Publish a post immediately to the specified social platforms.

        Args:
            caption: Main text, copy, or hashtags.
            title: Post title (optional).
            media_url: Public media URL for photo or video.
            media_type: 'video', 'image', or 'text' (auto-detected if blank).
            platforms: List or comma-separated string of platforms.
            link: External link (optional).
        """
        plat_list = (
            platforms if isinstance(platforms, list)
            else [p.strip() for p in platforms.split(",") if p.strip()] if isinstance(platforms, str)
            else []
        )

        return self._request(
            "/api/webhook/publish",
            method="POST",
            data={
                "title": title,
                "caption": caption,
                "mediaUrl": media_url,
                "mediaType": media_type,
                "platforms": plat_list,
                "link": link,
                "publishNow": True
            }
        )

    def schedule(
        self,
        caption: str,
        scheduled_date_time: str,
        title: str = "",
        media_url: str = "",
        media_type: str = "",
        platforms: Optional[Union[List[str], str]] = None,
        link: str = ""
    ) -> Dict[str, Any]:
        """Schedule a post in the content calendar for future automated publishing."""
        plat_list = (
            platforms if isinstance(platforms, list)
            else [p.strip() for p in platforms.split(",") if p.strip()] if isinstance(platforms, str)
            else []
        )

        return self._request(
            "/api/webhook/schedule",
            method="POST",
            data={
                "title": title,
                "caption": caption,
                "scheduledDateTime": scheduled_date_time,
                "mediaUrl": media_url,
                "mediaType": media_type,
                "platforms": plat_list,
                "link": link
            }
        )

    def get_status(self, content_id: str) -> Dict[str, Any]:
        """Get current publishing state and live permalinks for a content ID."""
        return self._request(f"/api/webhook/status/{urllib.parse.quote(content_id)}")

    def get_posts(self) -> Dict[str, Any]:
        """Fetch all calendar posts."""
        return self._request("/api/v1/posts")
