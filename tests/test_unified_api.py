"""
Integration tests for Unified Web Studio REST APIs:
Google OAuth, Video Editor, and Publishing Workflow endpoints.
"""

import pytest
import os
import subprocess
import uuid
from fastapi.testclient import TestClient

from yt_clipping.web.server import app, project_store, CLIPS_DIR
from yt_clipping.orchestration.project_store import ClipSidecarRecord


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def sample_mp4():
    test_file = os.path.join(CLIPS_DIR, "test_api_clip_01.mp4")
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", "testsrc=duration=2:size=640x360:rate=25",
        "-f", "lavfi",
        "-i", "sine=frequency=1000:duration=2",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        test_file,
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return test_file


def test_api_google_auth_url(client):
    res = client.get("/api/v1/auth/google/url")
    assert res.status_code == 200
    data = res.json()
    assert "auth_url" in data
    assert "https://accounts.google.com" in data["auth_url"]


def test_api_google_auth_status_isolation(client):
    res = client.get("/api/v1/auth/google/status")
    assert res.status_code == 200
    data = res.json()
    assert "connected" in data
    assert "channel_title" in data
    assert "isolation_verified" in data
    # Ensure sensitive secrets are NEVER returned
    assert "access_token" not in data
    assert "refresh_token" not in data
    assert "client_secret" not in data


def test_api_publish_channels(client):
    res = client.get("/api/v1/publish/channels")
    assert res.status_code == 200
    data = res.json()
    assert "dedicated_youtube" in data
    assert "omnipost_gateway" in data


def test_api_publish_rejection_without_approval(client, sample_mp4):
    cid = "test_api_clip_01"
    res = client.post(
        "/api/v1/publish/submit",
        json={
            "clip_id": cid,
            "target": "youtube_dedicated",
            "approved_by_user": False,  # No user approval!
        },
    )
    assert res.status_code == 400
    assert "Explicit human approval" in res.json()["detail"]


def test_api_publish_success_with_approval(client, sample_mp4):
    cid = f"test_api_clip_{uuid.uuid4().hex[:8]}"
    # Seed sidecar in project store
    sidecar = ClipSidecarRecord(
        clip_id=cid,
        project_id="proj_api_test",
        video_id="vid_api_test",
        file_path=sample_mp4,
        relative_url=f"/clips/{os.path.basename(sample_mp4)}",
        start_seconds=0.0,
        end_seconds=2.0,
        duration_seconds=2.0,
        score=95.0,
        file_size_bytes=os.path.getsize(sample_mp4),
        status="COMPLETED",
    )
    project_store.save_clip_sidecar(sidecar)

    res = client.post(
        "/api/v1/publish/submit",
        json={
            "clip_id": cid,
            "target": "youtube_dedicated",
            "title": "API Test Published Short",
            "description": "Awesome test short #viral",
            "tags": ["testing", "shorts"],
            "approved_by_user": True,  # User explicitly approved!
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["status"] in ("DELIVERED", "SCHEDULED")
    assert "receipt_id" in data


def test_api_publish_history(client):
    res = client.get("/api/v1/publish/history")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= 1


def test_api_editor_frame_preview(client, sample_mp4):
    res = client.post(
        "/api/v1/editor/preview-frame",
        json={"file_path": sample_mp4, "timestamp": 0.5},
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"
    assert len(res.content) > 100


def test_api_editor_export(client, sample_mp4):
    res = client.post(
        "/api/v1/editor/export",
        json={
            "source_path": sample_mp4,
            "project_id": "proj_export_api_test",
            "clips": [
                {
                    "title": "Exported Hook Clip",
                    "start_seconds": 0.0,
                    "end_seconds": 1.0,
                    "aspect_ratio": "9:16",
                    "center_x": 0.5,
                    "text_overlay": "Hot Take",
                }
            ],
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["exported_count"] == 1
    assert len(data["clips"]) == 1


def test_api_clip_streaming_alias(client, sample_mp4):
    cid = os.path.splitext(os.path.basename(sample_mp4))[0]
    res = client.get(f"/api/v1/clips/{cid}/stream")
    assert res.status_code in (200, 206)
    assert res.headers["content-type"] == "video/mp4"


def test_api_editor_export_resolves_clip_id(client, sample_mp4):
    cid = os.path.splitext(os.path.basename(sample_mp4))[0]
    # Pass pure clip_id without path or extension
    res = client.post(
        "/api/v1/editor/export",
        json={
            "source_path": cid,
            "project_id": "proj_export_clip_id_test",
            "clips": [
                {
                    "title": "Resolved Clip Export",
                    "start_seconds": 0.0,
                    "end_seconds": 0.8,
                    "aspect_ratio": "9:16",
                    "text_overlay": "100% Tested",
                }
            ],
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["exported_count"] == 1


def test_api_editor_preview_frame_resolves_clip_id(client, sample_mp4):
    cid = os.path.splitext(os.path.basename(sample_mp4))[0]
    res = client.post(
        "/api/v1/editor/preview-frame",
        json={"file_path": cid, "timestamp": 0.2},
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"


def test_api_batch_multi_clip_publishing(client, sample_mp4):
    cid1 = f"batch_clip_01_{uuid.uuid4().hex[:6]}"
    cid2 = f"batch_clip_02_{uuid.uuid4().hex[:6]}"

    for cid in (cid1, cid2):
        sidecar = ClipSidecarRecord(
            clip_id=cid,
            project_id="proj_batch_test",
            video_id="vid_batch_test",
            file_path=sample_mp4,
            relative_url=f"/clips/{os.path.basename(sample_mp4)}",
            start_seconds=0.0,
            end_seconds=1.5,
            duration_seconds=1.5,
            score=93.0,
            file_size_bytes=os.path.getsize(sample_mp4),
            status="COMPLETED",
        )
        project_store.save_clip_sidecar(sidecar)

    res = client.post(
        "/api/v1/publish/submit",
        json={
            "clip_ids": [cid1, cid2],
            "target": "youtube_dedicated",
            "channel_id": "UC_TEST_BATCH_CH",
            "approved_by_user": True,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["total_published"] == 2
    assert len(data["receipts"]) == 2


def test_api_publish_channels_returns_channel_list(client):
    res = client.get("/api/v1/publish/channels")
    assert res.status_code == 200
    data = res.json()
    assert "channels" in data
    assert isinstance(data["channels"], list)

