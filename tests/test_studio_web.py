"""
Unit tests for YouTube Clipping Intelligence Web Studio Dashboard & REST API.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from yt_clipping.web.server import app, active_render_jobs
from yt_clipping.cli.commands.studio import cmd_studio


@pytest.fixture
def client():
    return TestClient(app)


def test_studio_dashboard_serves_html(client):
    """Verifies that root '/' returns the live interactive studio dashboard HTML."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "YouTube Clipping Intelligence Platform" in response.text
    assert "Live Studio" in response.text
    assert "btn-preview" in response.text
    assert "btn-primary" in response.text


def test_studio_health_endpoint(client):
    """Verifies that '/api/v1/health' returns system diagnostics, GPU readiness, and model status."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data
    assert "gpu_available" in data
    assert "ffmpeg_ready" in data
    assert "models" in data
    assert "yunet_onnx" in data["models"]
    assert "yolov8n_seg" in data["models"]
    assert "gemini_active" in data["models"]
    assert "storage" in data
    assert "clips_count" in data["storage"]


def test_studio_clips_list_endpoint(client):
    """Verifies that '/api/v1/clips' returns a JSON list of rendered clips."""
    response = client.get("/api/v1/clips")
    assert response.status_code == 200
    clips = response.json()
    assert isinstance(clips, list)
    if clips:
        clip = clips[0]
        assert "filename" in clip
        assert "url" in clip
        assert "size_mb" in clip


def test_studio_render_status_not_found(client):
    """Verifies that requesting a nonexistent task ID returns 404."""
    response = client.get("/api/v1/render/status/nonexistent-task-999")
    assert response.status_code == 404
    assert "Task ID not found" in response.json()["detail"]


def test_studio_render_status_existing(client):
    """Verifies that querying a known active task ID returns progress and status."""
    active_render_jobs["test-task-123"] = {
        "task_id": "test-task-123",
        "video_id": "test_vid",
        "status": "IN_PROGRESS",
        "progress": 65,
        "message": "Applying face tracking...",
    }
    try:
        response = client.get("/api/v1/render/status/test-task-123")
        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == "test-task-123"
        assert data["status"] == "IN_PROGRESS"
        assert data["progress"] == 65
    finally:
        active_render_jobs.pop("test-task-123", None)


def test_studio_preview_invalid_url(client):
    """Verifies that invalid video identifiers are rejected with 400."""
    response = client.post("/api/v1/preview", json={"video_id_or_url": "invalid!id"})
    assert response.status_code == 400


def test_cmd_studio_invocation():
    """Verifies that cmd_studio parses host and port and invokes start_server."""
    args = MagicMock()
    args.host = "127.0.0.1"
    args.port = 8888

    with patch("yt_clipping.cli.commands.studio.start_server") as mock_start:
        ret = cmd_studio(args)
        assert ret == 0
        mock_start.assert_called_once_with(host="127.0.0.1", port=8888)


def test_api_metadata_endpoint(client):
    """Verifies that POST /api/v1/metadata returns enriched video information."""
    # Test invalid URL
    bad_res = client.post("/api/v1/metadata", json={"video_id_or_url": "invalid_url_here"})
    assert bad_res.status_code == 400

    # Test valid mock video metadata
    mock_info = {
        "video_id": "nEaJMdM1djM",
        "title": "Mock Video Title",
        "description": "Mock Description",
        "channel_title": "Mock Channel",
        "view_count": 1000,
        "like_count": 50,
        "comment_count": 10,
        "duration": 120.0,
        "canonical_url": "https://www.youtube.com/watch?v=nEaJMdM1djM",
        "metadata_provider": "youtube_data_api_v3",
        "extraction_status": "success",
    }
    with patch("yt_clipping.web.server.metadata_service.get_metadata") as mock_get:
        from yt_clipping.discovery.video_metadata import EnrichedVideoInfo
        mock_get.return_value = EnrichedVideoInfo.from_dict(mock_info)
        res = client.post("/api/v1/metadata", json={"video_id_or_url": "nEaJMdM1djM"})
        assert res.status_code == 200
        data = res.json()
        assert data["video_id"] == "nEaJMdM1djM"
        assert data["title"] == "Mock Video Title"


def test_api_jobs_and_cancellation(client):
    """Verifies job status and cancellation endpoints."""
    # Trigger render
    render_req = {
        "video_id_or_url": "nEaJMdM1djM",
        "max_clips": 1,
        "layout": "active_speaker",
        "subtitle_preset": "hormozi",
        "gpu": False,
    }
    with patch("yt_clipping.web.server._run_render_worker"):
        res = client.post("/api/v1/render", json=render_req)
        assert res.status_code == 200
        data = res.json()
        job_id = data["job_id"]
        assert job_id.startswith("job-")

        # Query job status
        job_res = client.get(f"/api/v1/jobs/{job_id}")
        assert job_res.status_code == 200
        job_data = job_res.json()
        assert job_data["job_id"] == job_id
        assert job_data["status"] in ("queued", "discovering", "rendering")

        # Cancel job
        cancel_res = client.post(f"/api/v1/jobs/{job_id}/cancel")
        assert cancel_res.status_code == 200
        assert cancel_res.json()["status"] == "cancelled"


def test_api_projects_endpoints(client):
    """Verifies GET /api/v1/projects endpoint."""
    res = client.get("/api/v1/projects")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_api_media_range_streaming(client, tmp_path):
    """Verifies that media endpoint supports HTTP Range 206 Partial Content requests for seeking."""
    import os
    test_file = tmp_path / "test_stream.mp4"
    # Create 10000 bytes dummy mp4
    test_content = b"0123456789" * 1000
    test_file.write_bytes(test_content)

    from yt_clipping.orchestration.project_store import ClipSidecarRecord
    from yt_clipping.web.server import project_store

    sidecar = ClipSidecarRecord(
        clip_id="test_stream_id",
        project_id="proj_test",
        video_id="v_test",
        file_path=str(test_file),
        relative_url="/clips/test_stream.mp4",
        start_seconds=0.0,
        end_seconds=10.0,
        duration_seconds=10.0,
        score=85.0,
        file_size_bytes=len(test_content),
    )
    project_store.save_clip_sidecar(sidecar)

    # 1. Full stream
    full_res = client.get("/api/v1/clips/test_stream_id/media")
    assert full_res.status_code == 200
    assert full_res.headers["content-length"] == str(len(test_content))

    # 2. Range request: bytes=0-499
    range_res = client.get("/api/v1/clips/test_stream_id/media", headers={"Range": "bytes=0-499"})
    assert range_res.status_code == 206
    assert range_res.headers["content-length"] == "500"
    assert range_res.headers["content-range"] == f"bytes 0-499/{len(test_content)}"
    assert range_res.content == test_content[0:500]


def test_path_traversal_protection(client):
    """Verifies that path traversal payloads are rejected with 400 Bad Request."""
    bad_clips = [
        "../../etc/passwd",
        "..\\..\\windows\\win.ini",
        "....//....//boot.ini",
    ]
    for bad in bad_clips:
        res = client.get(f"/api/v1/clips/{bad}/download")
        assert res.status_code in (400, 404)


def test_api_regenerate_caption_endpoint(client, tmp_path):
    """Verifies that POST /api/v1/clips/{clip_id}/regenerate_caption creates a fresh caption package."""
    from yt_clipping.orchestration.project_store import ClipSidecarRecord
    from yt_clipping.web.server import project_store

    sidecar = ClipSidecarRecord(
        clip_id="test_regen_clip",
        project_id="proj_regen",
        video_id="nEaJMdM1djM",
        file_path=str(tmp_path / "dummy.mp4"),
        relative_url="/clips/dummy.mp4",
        start_seconds=10.0,
        end_seconds=35.0,
        duration_seconds=25.0,
        score=88.0,
        caption_package={"hook_title": "Old Title", "full_copy_caption": "Old Caption"},
        source_metadata={"video_id": "nEaJMdM1djM", "channel_title": "Tech Creator", "title": "Tech Talk"},
    )
    project_store.save_clip_sidecar(sidecar)

    # 1. Nonexistent clip returns 404
    bad_res = client.post("/api/v1/clips/nonexistent_clip_xyz/regenerate_caption")
    assert bad_res.status_code == 404

    # 2. Existing clip succeeds and updates sidecar
    res = client.post("/api/v1/clips/test_regen_clip/regenerate_caption")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "regenerated"
    assert "caption_package" in data
    assert "intelligence" in data
    assert data["caption_package"]["hook_title"] != ""
    assert "Tech Creator" in data["caption_package"]["creator_credit"]


def test_api_clips_includes_playback_and_validation(client, tmp_path):
    """Verifies GET /api/v1/clips includes playback_url and validation_status."""
    from yt_clipping.orchestration.project_store import ClipSidecarRecord
    from yt_clipping.web.server import project_store

    mp4_file = tmp_path / "pb.mp4"
    mp4_file.write_bytes(b"dummy mp4 content")

    sidecar = ClipSidecarRecord(
        clip_id="test_clip_playback",
        project_id="proj_pb",
        video_id="vid_pb",
        file_path=str(mp4_file),
        relative_url="/clips/pb.mp4",
        start_seconds=5.0,
        end_seconds=25.0,
        duration_seconds=20.0,
        score=91.0,
        status="COMPLETED",
    )
    project_store.save_clip_sidecar(sidecar)

    res = client.get("/api/v1/clips")
    assert res.status_code == 200
    clips = res.json()
    target = next((c for c in clips if c["clip_id"] == "test_clip_playback"), None)
    assert target is not None
    assert target["playback_url"] == "/api/v1/clips/test_clip_playback/media"
    assert target["download_url"] == "/api/v1/clips/test_clip_playback/download"
    assert target["validation_status"] == "COMPLETED"


def test_api_settings_endpoints(client):
    """Verifies GET and POST /api/v1/settings."""
    res = client.get("/api/v1/settings")
    assert res.status_code == 200
    data = res.json()
    assert "gemini_model" in data
    assert "layout_mode" in data

    # Update settings
    post_res = client.post("/api/v1/settings", json={"contact_email": "ops@customdomain.com"})
    assert post_res.status_code == 200
    assert post_res.json()["settings"]["contact_email"] == "ops@customdomain.com"


def test_api_clip_poster_endpoint(client, tmp_path):
    """Verifies GET /api/v1/clips/{clip_id}/poster returns poster or 404."""
    # Nonexistent
    bad_res = client.get("/api/v1/clips/nonexistent_clip_xyz/poster")
    assert bad_res.status_code == 404




