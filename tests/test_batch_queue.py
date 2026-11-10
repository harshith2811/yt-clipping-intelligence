import pytest
import os
import tempfile
import gc
from yt_clipping.orchestration.batch_queue import (
    BatchQueueManager,
    BatchStatus,
    BatchItemStatus,
)


@pytest.fixture
def temp_batch_manager():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test_dashboard.db")
    manager = BatchQueueManager(storage_dir=tmpdir, db_path=db_path)
    yield manager
    gc.collect()
    try:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass


def test_create_and_load_batch(temp_batch_manager):
    videos = [
        {"video_id": f"vid_{i}", "title": f"Video {i}", "channel_name": "MrBeast"}
        for i in range(10)
    ]
    session = temp_batch_manager.create_batch(videos=videos, name="Overnight 10-Pack")
    assert session.total_videos == 10
    assert len(session.items) == 10
    assert session.status == BatchStatus.RUNNING

    loaded = temp_batch_manager.get_batch(session.batch_id)
    assert loaded is not None
    assert loaded.batch_id == session.batch_id
    assert loaded.total_videos == 10
    assert loaded.name == "Overnight 10-Pack"


def test_batch_worker_sequential_execution(temp_batch_manager):
    videos = [
        {"video_id": "vid_1", "title": "Vid 1"},
        {"video_id": "vid_2", "title": "Vid 2"},
        {"video_id": "vid_3", "title": "Vid 3"},
    ]
    session = temp_batch_manager.create_batch(videos=videos)

    processed = []

    def mock_render(video_id, config, progress_cb):
        processed.append(video_id)
        progress_cb(50, "Synthesizing captions")
        progress_cb(100, "Render complete")
        return [{"clip_id": f"clip_{video_id}_1"}, {"clip_id": f"clip_{video_id}_2"}]

    temp_batch_manager.run_batch_worker(session.batch_id, mock_render)

    completed = temp_batch_manager.get_batch(session.batch_id)
    assert completed.status == BatchStatus.COMPLETED
    assert completed.completed_videos == 3
    assert completed.total_clips_generated == 6
    assert processed == ["vid_1", "vid_2", "vid_3"]


def test_batch_worker_failure_isolation(temp_batch_manager):
    """Verifies that an error in one video doesn't break the entire batch."""
    videos = [
        {"video_id": "good_1", "title": "Good 1"},
        {"video_id": "bad_2", "title": "Bad 2 (Copyrighted)"},
        {"video_id": "good_3", "title": "Good 3"},
    ]
    session = temp_batch_manager.create_batch(videos=videos)

    def mock_render(video_id, config, progress_cb):
        if video_id == "bad_2":
            raise RuntimeError("Video unavailable due to copyright")
        return [{"clip_id": f"clip_{video_id}"}]

    temp_batch_manager.run_batch_worker(session.batch_id, mock_render)

    completed = temp_batch_manager.get_batch(session.batch_id)
    assert completed.status == BatchStatus.COMPLETED
    assert completed.completed_videos == 2
    assert completed.failed_videos == 1
    assert completed.total_clips_generated == 2

    # Check item details
    items = completed.items
    assert items[0].status == BatchItemStatus.COMPLETED
    assert items[1].status == BatchItemStatus.FAILED
    assert "copyright" in items[1].error_message
    assert items[2].status == BatchItemStatus.COMPLETED


def test_batch_cancellation(temp_batch_manager):
    videos = [
        {"video_id": f"vid_{i}", "title": f"Video {i}"}
        for i in range(5)
    ]
    session = temp_batch_manager.create_batch(videos=videos)

    def mock_render(video_id, config, progress_cb):
        if video_id == "vid_1":
            temp_batch_manager.cancel_batch(session.batch_id)
        return [{"clip_id": "clip"}]

    temp_batch_manager.run_batch_worker(session.batch_id, mock_render)

    res = temp_batch_manager.get_batch(session.batch_id)
    assert res.status == BatchStatus.CANCELLED
    assert res.completed_videos >= 1
    assert res.completed_videos < 5


def test_batch_api_endpoints(monkeypatch):
    from fastapi.testclient import TestClient
    from yt_clipping.web.server import app

    monkeypatch.setattr("yt_clipping.web.server._execute_batch_background", lambda batch_id: None)

    client = TestClient(app)

    # 1. Status
    r = client.get("/api/v1/batch/status")
    assert r.status_code == 200

    # 2. Start
    r = client.post("/api/v1/batch/start", json={
        "video_ids": ["nEaJMdM1djM", "kG3uGk_4a78"],
        "name": "Test API Batch",
    })
    assert r.status_code == 200
    batch_data = r.json()
    assert "batch_id" in batch_data
    assert batch_data["total_videos"] == 2

    # 3. Check status
    r = client.get("/api/v1/batch/status")
    assert r.status_code == 200
    assert r.json()["batch_id"] == batch_data["batch_id"]

    # 4. Cancel
    r = client.post("/api/v1/batch/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"

    # 5. History
    r = client.get("/api/v1/batch/history")
    assert r.status_code == 200
    assert len(r.json()) >= 1

