"""
Tests for ProjectStore and ClipSidecarRecord persistence.
Verifies atomic saving, recovery after restart, corrupted file handling,
missing media detection, and project history listing.
"""

import pytest
import os
import json
from yt_clipping.orchestration.project_store import (
    ProjectStore,
    ProjectRecord,
    ClipSidecarRecord,
)
from yt_clipping.discovery.video_metadata import EnrichedVideoInfo


def test_project_store_lifecycle(tmp_path):
    store = ProjectStore(base_data_dir=str(tmp_path))

    video_info = EnrichedVideoInfo(
        video_id="vid_test_123",
        title="Test Project Title",
        description="Test Description",
        channel_title="Test Creator",
        canonical_url="https://www.youtube.com/watch?v=vid_test_123",
    )

    # 1. Create project
    proj = store.create_or_get_project("vid_test_123", source_metadata=video_info)
    assert proj.project_id == "proj_vid_test_123"
    assert proj.title == "Test Project Title"

    # 2. Add clip sidecar
    mp4_file = tmp_path / "rendered_clips" / "clip_vid_test_123_1.mp4"
    mp4_file.write_bytes(b"dummy video content")

    sidecar = ClipSidecarRecord(
        clip_id="c_1",
        project_id=proj.project_id,
        video_id="vid_test_123",
        file_path=str(mp4_file),
        relative_url="/clips/clip_vid_test_123_1.mp4",
        start_seconds=10.0,
        end_seconds=40.0,
        duration_seconds=30.0,
        score=92.0,
        file_size_bytes=len(b"dummy video content"),
        status="COMPLETED",
    )
    sidecar_path = store.save_clip_sidecar(sidecar)
    assert os.path.exists(sidecar_path)

    # 3. Simulate Server Restart: Reinstantiate ProjectStore with same dir
    store_restarted = ProjectStore(base_data_dir=str(tmp_path))
    retrieved_proj = store_restarted.get_project(proj.project_id)
    assert retrieved_proj is not None
    assert retrieved_proj.title == "Test Project Title"

    # List clips
    clips = store_restarted.list_clips()
    assert len(clips) >= 1
    found = next((c for c in clips if c.clip_id == "c_1"), None)
    assert found is not None
    assert found.score == 92.0
    assert found.status == "COMPLETED"

    # List projects
    projs = store_restarted.list_projects()
    assert len(projs) >= 1
    assert projs[0].project_id == proj.project_id


def test_project_store_handles_corrupted_files(tmp_path):
    store = ProjectStore(base_data_dir=str(tmp_path))

    # Create dummy project directory with corrupted project.json
    pdir = tmp_path / "projects" / "project_corrupted"
    pdir.mkdir(parents=True)
    corrupted_file = pdir / "project.json"
    corrupted_file.write_text("{invalid json ...")

    # Listing projects should gracefully ignore or log warning without raising
    projs = store.list_projects()
    assert isinstance(projs, list)


def test_project_store_missing_media(tmp_path):
    store = ProjectStore(base_data_dir=str(tmp_path))

    sidecar = ClipSidecarRecord(
        clip_id="missing_clip",
        project_id="proj_missing",
        video_id="vid_missing",
        file_path=str(tmp_path / "non_existent.mp4"),
        relative_url="/clips/non_existent.mp4",
        start_seconds=0.0,
        end_seconds=30.0,
        duration_seconds=30.0,
        score=80.0,
    )
    store.save_clip_sidecar(sidecar)

    clips = store.list_clips()
    match = next((c for c in clips if c.clip_id == "missing_clip"), None)
    assert match is not None
    assert match.status == "MISSING_MEDIA"


def test_project_store_prefix_and_name_variations(tmp_path):
    store = ProjectStore(base_data_dir=str(tmp_path))

    # Project created with proj_video99
    proj = store.create_or_get_project("video99")
    assert proj.project_id == "proj_video99"

    # Querying by proj_video99, project_proj_video99, and video99 should all resolve
    assert store.get_project("proj_video99") is not None
    assert store.get_project("project_proj_video99") is not None
    assert store.get_project("video99") is not None

    # Save a clip whose ID starts with 'clip_' and has 'clip' in the middle
    mp4_file = tmp_path / "rendered_clips" / "clip_special_clip_1.mp4"
    mp4_file.write_bytes(b"content")

    sidecar = ClipSidecarRecord(
        clip_id="clip_special_clip_1",
        project_id=proj.project_id,
        video_id="video99",
        file_path=str(mp4_file),
        relative_url="/clips/clip_special_clip_1.mp4",
        start_seconds=0.0,
        end_seconds=15.0,
        duration_seconds=15.0,
        score=85.0,
    )
    store.save_clip_sidecar(sidecar)

    # Retrieval by clip_special_clip_1 and special_clip_1 must both find the sidecar
    res1 = store.get_clip_sidecar("clip_special_clip_1")
    assert res1 is not None
    assert res1.clip_id == "clip_special_clip_1"

    res2 = store.get_clip_sidecar("special_clip_1")
    assert res2 is not None
    assert res2.clip_id == "clip_special_clip_1"

