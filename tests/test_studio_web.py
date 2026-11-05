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
