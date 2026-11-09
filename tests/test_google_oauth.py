"""
Tests for Dedicated Google Account and YouTube OAuth Isolation.
Verifies token lifecycle, channel authorization, credential isolation,
and zero leakage of secrets to frontend responses.
"""

import pytest
import os
import json
import time
from unittest.mock import patch, MagicMock

from yt_clipping.auth.google_oauth import DedicatedYouTubeAuth


@pytest.fixture
def auth_instance(tmp_path):
    creds_file = tmp_path / "youtube_auth.json"
    auth = DedicatedYouTubeAuth(
        credentials_file=str(creds_file),
        client_id="test-client-id.apps.googleusercontent.com",
        client_secret="test-client-secret-xyz",
        redirect_uri="http://localhost:8000/api/v1/auth/google/callback",
        env_mode="development",
    )
    return auth


def test_auth_url_generation(auth_instance):
    url = auth_instance.get_authorization_url(state="test_state_123")
    assert "https://accounts.google.com/o/oauth2/v2/auth" in url
    assert "client_id=test-client-id.apps.googleusercontent.com" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=test_state_123" in url


def test_public_status_redacts_secrets(auth_instance):
    # Store token with sensitive fields
    auth_instance._save_stored_credentials({
        "access_token": "secret_access_token_123",
        "refresh_token": "secret_refresh_token_456",
        "client_secret": "do_not_leak_this",
        "channel_id": "UC_TEST_CHANNEL",
        "channel_title": "Test Channel Title",
        "channel_handle": "@TestHandle",
        "subscriber_count": "5,000",
        "thumbnail_url": "http://img/avatar.jpg",
        "expires_at": time.time() + 3600,
    })

    status = auth_instance.get_public_status()
    assert status["connected"] is True
    assert status["channel_id"] == "UC_TEST_CHANNEL"
    assert status["channel_title"] == "Test Channel Title"
    assert status["channel_handle"] == "@TestHandle"
    assert status["subscriber_count"] == "5,000"

    # Strictly assert NO secret tokens are present in public status
    assert "access_token" not in status
    assert "refresh_token" not in status
    assert "client_secret" not in status
    assert "secret_access_token_123" not in json.dumps(status)
    assert "secret_refresh_token_456" not in json.dumps(status)


def test_token_auto_refresh_when_expired(auth_instance):
    auth_instance._save_stored_credentials({
        "access_token": "expired_token_123",
        "refresh_token": "valid_refresh_token_999",
        "expires_at": time.time() - 100,  # Expired
    })

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "new_fresh_token_777",
        "expires_in": 3600,
    }

    with patch("requests.post", return_value=mock_resp):
        token = auth_instance.get_valid_access_token()
        assert token == "new_fresh_token_777"
        # Verify stored file was updated
        stored = auth_instance._load_stored_credentials()
        assert stored["access_token"] == "new_fresh_token_777"


def test_disconnect_wipes_credentials(auth_instance):
    auth_instance._save_stored_credentials({"access_token": "tok1", "refresh_token": "tok2"})
    assert os.path.exists(auth_instance.credentials_file)

    auth_instance.disconnect()
    assert not os.path.exists(auth_instance.credentials_file)
    status = auth_instance.get_public_status()
    assert status["connected"] is False


def test_youtube_upload_dry_run(auth_instance, tmp_path):
    dummy_video = tmp_path / "test_video.mp4"
    dummy_video.write_bytes(b"dummy mp4 video bytes")

    result = auth_instance.upload_video_to_youtube(
        file_path=str(dummy_video),
        title="Test Shorts Title #shorts",
        description="Great video description #viral",
        tags=["shorts", "test"],
        dry_run=True,
    )
    assert result["success"] is True
    assert result["simulated"] is True
    assert "video_id" in result
    assert "https://www.youtube.com/watch?v=" in result["video_url"]


def test_csrf_state_generation_and_validation(auth_instance):
    state = auth_instance.generate_state_token()
    assert len(state) >= 32
    assert auth_instance.validate_state_token(state) is True
    # Second validation fails (single-use)
    assert auth_instance.validate_state_token(state) is False
    assert auth_instance.validate_state_token("tampered_state_value") is False


def test_list_available_channels(auth_instance):
    auth_instance._save_stored_credentials({
        "access_token": "valid_token",
        "channel_id": "UC_AUTOMATION_01",
        "channel_title": "Primary Automation Hub",
        "channel_handle": "@AutoStudio",
        "subscriber_count": "25,000",
    })
    channels = auth_instance.list_available_channels()
    assert len(channels) >= 1
    assert channels[0]["channel_id"] == "UC_AUTOMATION_01"
    assert channels[0]["channel_title"] == "Primary Automation Hub"
    assert channels[0]["is_default"] is True


def test_scheduled_publish_at_and_thumbnail(auth_instance, tmp_path):
    dummy_video = tmp_path / "test_sched_video.mp4"
    dummy_video.write_bytes(b"dummy mp4 video bytes")
    dummy_thumb = tmp_path / "thumb.jpg"
    dummy_thumb.write_bytes(b"dummy jpg image bytes")

    result = auth_instance.upload_video_to_youtube(
        file_path=str(dummy_video),
        title="Scheduled Release Clip",
        description="Release soon #shorts",
        publish_at="2026-12-25T12:00:00Z",
        channel_id="UC_CUSTOM_DEST",
        thumbnail_path=str(dummy_thumb),
        dry_run=True,
    )

    assert result["success"] is True
    assert result["privacy_status"] == "private"
    assert result["scheduled_time"] == "2026-12-25T12:00:00Z"
    assert result["channel_id"] == "UC_CUSTOM_DEST"
    assert result["thumbnail_set"] is True
    assert result["thumbnail_path"] == str(dummy_thumb)
