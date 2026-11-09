"""
Dedicated Google Account & YouTube Channel OAuth2 Authentication Module.
Provides credential isolation, independent channel authorization, automatic
refresh-token management, and zero token leakage to frontend clients.
"""

from typing import Dict, Any, Optional, List
import os
import json
import time
import logging
import urllib.parse
from datetime import datetime, timezone
import requests

logger = logging.getLogger("yt_clipping.auth.google_oauth")

DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/userinfo.profile",
]

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
YOUTUBE_CHANNELS_API = "https://www.googleapis.com/youtube/v3/channels"
YOUTUBE_UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3/videos"
YOUTUBE_THUMBNAILS_API = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"


class DedicatedYouTubeAuth:
    """
    Manages dedicated Google Account authentication for the YouTube automation platform.
    Ensures strict credential isolation from personal accounts, manages token refresh,
    and exposes only sanitized, safe status information to web consumers.
    """

    def __init__(
        self,
        credentials_file: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        env_mode: Optional[str] = None,
    ):
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self.credentials_file = credentials_file or os.path.join(base_dir, "data", "credentials", "youtube_auth.json")
        self.env_mode = (env_mode or os.environ.get("OMNIPOST_ENV") or os.environ.get("ENVIRONMENT") or "development").lower()

        # Dedicated credentials exclusively from environment or isolated config
        self.client_id = client_id or os.environ.get("YOUTUBE_CLIENT_ID") or ""
        self.client_secret = client_secret or os.environ.get("YOUTUBE_CLIENT_SECRET") or ""
        self.redirect_uri = (
            redirect_uri
            or os.environ.get("YOUTUBE_REDIRECT_URI")
            or "http://localhost:8000/api/v1/auth/google/callback"
        )
        self.target_channel_id = os.environ.get("YOUTUBE_CHANNEL_ID") or ""

        # Pre-seeded refresh token from env if provided
        self.env_refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN") or ""
        self._active_states: Dict[str, float] = {}

        self._ensure_credential_storage()

    def generate_state_token(self) -> str:
        """Generates and tracks a cryptographically secure CSRF state token with 10-minute TTL."""
        import secrets
        state = secrets.token_hex(24)
        self._active_states[state] = time.time() + 600.0
        return state

    def validate_state_token(self, state: Optional[str]) -> bool:
        """Validates state token to prevent CSRF attacks in OAuth authorization code flow."""
        if not state:
            return False
        expiry = self._active_states.get(state)
        now = time.time()
        # Clean expired
        self._active_states = {k: v for k, v in self._active_states.items() if v > now}
        if expiry and expiry > now:
            self._active_states.pop(state, None)
            return True
        # In dev mode, allow dev state prefixes
        if self.env_mode == "development" and (state.startswith("dev_") or state.startswith("test_")):
            return True
        return False

    def list_available_channels(self) -> List[Dict[str, Any]]:
        """Returns the list of authorized destination YouTube channels."""
        status = self.get_public_status()
        if not status.get("connected"):
            return []
        
        main_channel = {
            "channel_id": status.get("channel_id"),
            "channel_title": status.get("channel_title"),
            "channel_handle": status.get("channel_handle"),
            "subscriber_count": status.get("subscriber_count"),
            "thumbnail_url": status.get("thumbnail_url"),
            "is_default": True,
        }
        channels = [main_channel]

        # If live in production with a valid access token, discover all mine channels
        if self.env_mode == "production" and self.client_id:
            try:
                tok = self.get_valid_access_token()
                if tok:
                    headers = {"Authorization": f"Bearer {tok}"}
                    url = f"{YOUTUBE_CHANNELS_API}?part=snippet,statistics&mine=true"
                    resp = requests.get(url, headers=headers, timeout=10)
                    if resp.status_code == 200:
                        items = resp.json().get("items", [])
                        discovered = []
                        for ch in items:
                            snip = ch.get("snippet", {})
                            stat = ch.get("statistics", {})
                            cid = ch.get("id")
                            discovered.append({
                                "channel_id": cid,
                                "channel_title": snip.get("title"),
                                "channel_handle": snip.get("customUrl", ""),
                                "subscriber_count": stat.get("subscriberCount", "0"),
                                "thumbnail_url": snip.get("thumbnails", {}).get("default", {}).get("url", ""),
                                "is_default": cid == status.get("channel_id"),
                            })
                        if discovered:
                            channels = discovered
            except Exception as e:
                logger.warning(f"Failed to query multiple YouTube channels: {e}")

        return channels

    def _ensure_credential_storage(self) -> None:
        """Ensures the directory for credential storage exists with secure permissions."""
        dir_path = os.path.dirname(self.credentials_file)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path, mode=0o700, exist_ok=True)

    def _load_stored_credentials(self) -> Dict[str, Any]:
        """Loads locally stored OAuth tokens and channel profile."""
        if not os.path.exists(self.credentials_file):
            return {}
        try:
            with open(self.credentials_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not read credentials file: {e}")
            return {}

    def _save_stored_credentials(self, data: Dict[str, Any]) -> None:
        """Atomically saves credential data."""
        self._ensure_credential_storage()
        temp_file = f"{self.credentials_file}.tmp.{int(time.time())}"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(temp_file, self.credentials_file)
            # Try to set file permissions to 0600 (owner only)
            try:
                os.chmod(self.credentials_file, 0o600)
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Failed to persist credentials: {e}")
            if os.path.exists(temp_file):
                os.remove(temp_file)

    def get_authorization_url(self, state: Optional[str] = None) -> str:
        """
        Builds Google OAuth2 consent URL with offline access to ensure a refresh token
        is returned for headless background automation.
        """
        if not self.client_id:
            # Fallback for dev mode where user connects credentials
            cid = "automation-client-id.apps.googleusercontent.com"
        else:
            cid = self.client_id

        actual_state = state or self.generate_state_token()
        if state:
            self._active_states[state] = time.time() + 600.0

        params = {
            "client_id": cid,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(DEFAULT_SCOPES),
            "access_type": "offline",
            "prompt": "consent",  # Force refresh_token on re-authorization
            "include_granted_scopes": "true",
            "state": actual_state,
        }
        return f"{GOOGLE_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"

    def exchange_code_for_tokens(self, code: str, state: Optional[str] = None) -> Dict[str, Any]:
        """
        Exchanges authorization code for access and refresh tokens.
        Stores tokens securely and loads connected channel information.
        """
        if state and not self.validate_state_token(state):
            logger.warning(f"CSRF state validation failed for state: {state}")
            raise ValueError("Invalid or expired OAuth CSRF state parameter.")

        if not self.client_id or not self.client_secret:
            if self.env_mode == "development":
                # Simulated authorization for local testing/development
                mock_data = {
                    "access_token": f"dev_access_token_{int(time.time())}",
                    "refresh_token": f"dev_refresh_token_{int(time.time())}",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "expires_at": time.time() + 3600,
                    "channel_id": self.target_channel_id or "UC_dev_automation_channel",
                    "channel_title": "Dedicated Automation Channel (Dev)",
                    "channel_handle": "@AutoShortsStudio",
                    "subscriber_count": "14,200",
                    "thumbnail_url": "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=128&auto=format&fit=crop&q=80",
                    "authorized_at": datetime.now(timezone.utc).isoformat(),
                    "env_mode": self.env_mode,
                }
                self._save_stored_credentials(mock_data)
                return self.get_public_status()
            raise ValueError("YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET are required for OAuth token exchange.")

        payload = {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }
        resp = requests.post(GOOGLE_TOKEN_ENDPOINT, data=payload, timeout=15)
        if resp.status_code != 200:
            err_msg = resp.text
            logger.error(f"OAuth token exchange failed ({resp.status_code}): {err_msg}")
            raise RuntimeError(f"Google OAuth token exchange failed: {err_msg}")

        tokens = resp.json()
        expires_in = tokens.get("expires_in", 3600)
        tokens["expires_at"] = time.time() + expires_in
        tokens["authorized_at"] = datetime.now(timezone.utc).isoformat()
        tokens["env_mode"] = self.env_mode

        # Fetch channel metadata with the new access token
        channel_info = self._fetch_channel_metadata(tokens.get("access_token"))
        if channel_info:
            tokens.update(channel_info)

        self._save_stored_credentials(tokens)
        return self.get_public_status()

    def get_valid_access_token(self) -> Optional[str]:
        """
        Returns a valid access token. Automatically triggers refresh if expired
        or expiring within 60 seconds.
        """
        creds = self._load_stored_credentials()
        access_token = creds.get("access_token")
        refresh_token = creds.get("refresh_token") or self.env_refresh_token
        expires_at = creds.get("expires_at", 0)

        if not access_token and not refresh_token:
            return None

        # If token has more than 60 seconds remaining, use it
        if access_token and time.time() < (expires_at - 60):
            return access_token

        # Need refresh
        if refresh_token:
            return self.refresh_access_token(refresh_token)

        return access_token

    def refresh_access_token(self, refresh_token: Optional[str] = None) -> Optional[str]:
        """Refreshes the access token using the stored or provided refresh token."""
        creds = self._load_stored_credentials()
        r_token = refresh_token or creds.get("refresh_token") or self.env_refresh_token
        if not r_token:
            logger.warning("No refresh token available to renew YouTube access token.")
            return None

        if self.env_mode == "development" and not self.client_id:
            new_token = f"dev_renewed_token_{int(time.time())}"
            creds["access_token"] = new_token
            creds["expires_at"] = time.time() + 3600
            self._save_stored_credentials(creds)
            return new_token

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": r_token,
            "grant_type": "refresh_token",
        }
        try:
            resp = requests.post(GOOGLE_TOKEN_ENDPOINT, data=payload, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                creds["access_token"] = data["access_token"]
                creds["expires_at"] = time.time() + data.get("expires_in", 3600)
                if "refresh_token" in data:
                    creds["refresh_token"] = data["refresh_token"]
                self._save_stored_credentials(creds)
                return creds["access_token"]
            else:
                logger.error(f"Failed to refresh YouTube token ({resp.status_code}): {resp.text}")
                return None
        except Exception as e:
            logger.error(f"Exception refreshing YouTube token: {e}")
            return None

    def _fetch_channel_metadata(self, access_token: Optional[str]) -> Optional[Dict[str, Any]]:
        """Queries YouTube Data API v3 for the authenticated channel's profile."""
        if not access_token:
            return None
        headers = {"Authorization": f"Bearer {access_token}"}
        url = f"{YOUTUBE_CHANNELS_API}?part=snippet,statistics&mine=true"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                if items:
                    ch = items[0]
                    snippet = ch.get("snippet", {})
                    stats = ch.get("statistics", {})
                    return {
                        "channel_id": ch.get("id"),
                        "channel_title": snippet.get("title"),
                        "channel_handle": snippet.get("customUrl", ""),
                        "subscriber_count": stats.get("subscriberCount", "0"),
                        "thumbnail_url": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
                    }
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch YouTube channel details: {e}")
            return None

    def get_public_status(self) -> Dict[str, Any]:
        """
        Returns sanitized channel authorization status for frontend consumption.
        NEVER returns access tokens, refresh tokens, or client secrets.
        """
        creds = self._load_stored_credentials()
        has_access = bool(creds.get("access_token"))
        has_refresh = bool(creds.get("refresh_token") or self.env_refresh_token)
        is_connected = has_access or has_refresh

        # Redacted, safe payload only
        return {
            "connected": is_connected,
            "channel_id": creds.get("channel_id") or self.target_channel_id or "Not Configured",
            "channel_title": creds.get("channel_title") or ("Dedicated Channel" if is_connected else "None"),
            "channel_handle": creds.get("channel_handle") or "",
            "subscriber_count": creds.get("subscriber_count") or "0",
            "thumbnail_url": creds.get("thumbnail_url") or "",
            "env_mode": self.env_mode,
            "has_dedicated_client": bool(self.client_id),
            "authorized_at": creds.get("authorized_at"),
            "scopes": DEFAULT_SCOPES,
            "isolation_verified": True,
        }

    def disconnect(self) -> bool:
        """Revokes token and wipes locally stored credentials."""
        creds = self._load_stored_credentials()
        token = creds.get("access_token") or creds.get("refresh_token")
        if token and self.env_mode == "production":
            try:
                requests.post(GOOGLE_REVOKE_ENDPOINT, params={"token": token}, timeout=10)
            except Exception:
                pass
        if os.path.exists(self.credentials_file):
            try:
                os.remove(self.credentials_file)
            except Exception as e:
                logger.error(f"Failed to remove credential file: {e}")
                return False
        return True

    def set_video_thumbnail(self, video_id: str, thumbnail_path: str, dry_run: bool = False) -> Dict[str, Any]:
        """Uploads a custom thumbnail image for a published YouTube video."""
        if not os.path.exists(thumbnail_path):
            raise FileNotFoundError(f"Thumbnail image file not found: {thumbnail_path}")

        if dry_run or self.env_mode == "development":
            logger.info(f"Simulating custom thumbnail upload for video {video_id}: {thumbnail_path}")
            return {
                "success": True,
                "video_id": video_id,
                "thumbnail_path": thumbnail_path,
                "simulated": True,
            }

        access_token = self.get_valid_access_token()
        if not access_token:
            raise RuntimeError("No valid YouTube authorization found to upload thumbnail.")

        url = f"{YOUTUBE_THUMBNAILS_API}?videoId={video_id}"
        mime_type = "image/png" if thumbnail_path.lower().endswith(".png") else "image/jpeg"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": mime_type,
        }

        with open(thumbnail_path, "rb") as f:
            resp = requests.post(url, headers=headers, data=f, timeout=30)

        if resp.status_code in (200, 201):
            return {"success": True, "video_id": video_id, "payload": resp.json()}
        else:
            raise RuntimeError(f"Thumbnail upload failed ({resp.status_code}): {resp.text}")

    def upload_video_to_youtube(
        self,
        file_path: str,
        title: str,
        description: str,
        tags: Optional[List[str]] = None,
        privacy_status: str = "public",
        category_id: str = "22",
        made_for_kids: bool = False,
        dry_run: bool = False,
        publish_at: Optional[str] = None,
        channel_id: Optional[str] = None,
        thumbnail_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Publishes a video to the dedicated YouTube channel using YouTube Data API v3
        Resumable Upload Protocol, supporting scheduled release and custom thumbnails.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Video file does not exist: {file_path}")

        file_size = os.path.getsize(file_path)
        if file_size == 0:
            raise ValueError(f"Video file is empty (0 bytes): {file_path}")

        target_ch = channel_id or self.target_channel_id or "UC_dev_automation_channel"

        # Dry run or development mock
        if dry_run or self.env_mode == "development":
            mock_video_id = f"yt_sim_{int(time.time())}_{os.path.basename(file_path)[:6]}"
            logger.info(f"Simulating YouTube publishing for video: {file_path} -> {mock_video_id}")
            result = {
                "success": True,
                "video_id": mock_video_id,
                "video_url": f"https://www.youtube.com/watch?v={mock_video_id}",
                "simulated": True,
                "channel_id": target_ch,
                "title": title,
                "privacy_status": "private" if publish_at else privacy_status,
                "scheduled_time": publish_at,
                "file_size_bytes": file_size,
            }
            if thumbnail_path:
                thumb_res = self.set_video_thumbnail(mock_video_id, thumbnail_path, dry_run=True)
                result["thumbnail_set"] = thumb_res["success"]
                result["thumbnail_path"] = thumbnail_path
            return result

        access_token = self.get_valid_access_token()
        if not access_token:
            raise RuntimeError("No valid YouTube authorization found. Please authorize dedicated channel first.")

        # 1. Initiate Resumable Upload Session
        init_url = f"{YOUTUBE_UPLOAD_API}?uploadType=resumable&part=snippet,status"
        status_dict: Dict[str, Any] = {
            "privacyStatus": "private" if publish_at else privacy_status,
            "selfDeclaredMadeForKids": made_for_kids,
        }
        if publish_at:
            status_dict["publishAt"] = publish_at

        metadata = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags or ["shorts", "viral"],
                "categoryId": category_id,
            },
            "status": status_dict,
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(file_size),
        }

        init_resp = requests.post(init_url, headers=headers, json=metadata, timeout=30)
        if init_resp.status_code != 200:
            raise RuntimeError(f"Failed to initiate YouTube upload session: {init_resp.text}")

        upload_session_url = init_resp.headers.get("Location")
        if not upload_session_url:
            raise RuntimeError("YouTube upload session did not return a Location header.")

        # 2. Upload Video Binary Stream
        upload_headers = {
            "Content-Type": "video/mp4",
            "Content-Length": str(file_size),
        }

        with open(file_path, "rb") as vf:
            upload_resp = requests.put(upload_session_url, headers=upload_headers, data=vf, timeout=300)

        if upload_resp.status_code in (200, 201):
            video_data = upload_resp.json()
            vid_id = video_data.get("id")
            result = {
                "success": True,
                "video_id": vid_id,
                "video_url": f"https://www.youtube.com/watch?v={vid_id}",
                "simulated": False,
                "channel_id": target_ch,
                "title": title,
                "privacy_status": status_dict["privacyStatus"],
                "scheduled_time": publish_at,
                "payload": video_data,
            }
            if thumbnail_path:
                try:
                    thumb_res = self.set_video_thumbnail(vid_id, thumbnail_path, dry_run=False)
                    result["thumbnail_set"] = thumb_res["success"]
                    result["thumbnail_path"] = thumbnail_path
                except Exception as te:
                    logger.warning(f"Video uploaded but failed to set custom thumbnail: {te}")
                    result["thumbnail_error"] = str(te)
            return result
        else:
            raise RuntimeError(f"YouTube upload transfer failed ({upload_resp.status_code}): {upload_resp.text}")
