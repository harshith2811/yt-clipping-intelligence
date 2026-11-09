"""
Tests for Manual Video Editor Engine.
Verifies frame extraction, crop filters, trimming, text overlays,
and multi-clip export into ProjectStore.
"""

import pytest
import os
import subprocess
from yt_clipping.rendering.editor import VideoEditorEngine
from yt_clipping.orchestration.project_store import ProjectStore


@pytest.fixture(scope="module")
def sample_test_video(tmp_path_factory):
    """Generates a real 3-second synthetic test video with audio using FFmpeg."""
    tmp_dir = tmp_path_factory.mktemp("video_test")
    mp4_path = os.path.join(tmp_dir, "sample_source.mp4")
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", "testsrc=duration=3:size=640x360:rate=25",
        "-f", "lavfi",
        "-i", "sine=frequency=1000:duration=3",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        mp4_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return mp4_path


def test_build_crop_filter():
    editor = VideoEditorEngine()
    # 16:9 source (1920x1080) to 9:16 vertical short (1080x1920)
    filter_str, w, h = editor.build_crop_filter(1920, 1080, "9:16", center_x=0.5)
    assert w == 1080
    assert h == 1920
    assert "crop=" in filter_str
    assert "scale=1080:1920" in filter_str

    # Center x offset shifts crop coordinates
    filter_left, _, _ = editor.build_crop_filter(1920, 1080, "9:16", center_x=0.0)
    assert ":0:0,scale" in filter_left


def test_frame_extraction(sample_test_video, tmp_path):
    editor = VideoEditorEngine(output_dir=str(tmp_path))
    preview_img = editor.extract_frame_preview(sample_test_video, timestamp_s=1.0)
    assert os.path.exists(preview_img)
    assert os.path.getsize(preview_img) > 100
    assert preview_img.endswith(".jpg")


def test_render_edited_clip(sample_test_video, tmp_path):
    editor = VideoEditorEngine(output_dir=str(tmp_path))
    out_clip = tmp_path / "rendered_edit.mp4"

    res = editor.render_edited_clip(
        source_path=sample_test_video,
        start_seconds=0.5,
        end_seconds=1.8,
        aspect_ratio="9:16",
        center_x=0.5,
        text_overlay="Breaking News",
        text_position="top",
        output_file_path=str(out_clip),
    )

    assert os.path.exists(res["file_path"])
    assert res["duration_seconds"] == 1.3
    assert res["width"] == 1080
    assert res["height"] == 1920
    assert res["file_size_bytes"] > 1024


def test_export_multiple_clips(sample_test_video, tmp_path):
    editor = VideoEditorEngine(output_dir=str(tmp_path / "clips"))
    store = ProjectStore(base_data_dir=str(tmp_path / "store"))
    proj = store.create_or_get_project("vid_multi_test")

    specs = [
        {"title": "Hook Arc 1", "start_seconds": 0.0, "end_seconds": 1.2, "aspect_ratio": "9:16"},
        {"title": "Climax Arc 2", "start_seconds": 1.2, "end_seconds": 2.5, "aspect_ratio": "1:1"},
    ]

    exported = editor.export_multiple_clips(
        source_path=sample_test_video,
        clips_specs=specs,
        project_id=proj.project_id,
        project_store=store,
    )

    assert len(exported) == 2
    for clip in exported:
        assert os.path.exists(clip.file_path)
        assert clip.status == "COMPLETED"
        assert clip.candidate_data.get("hook_title") is not None

    # Verify they can be queried via store
    listed = store.list_clips(proj.project_id)
    assert len(listed) >= 2


def test_invalid_duration_rejected(sample_test_video):
    editor = VideoEditorEngine()
    with pytest.raises(ValueError, match="Invalid duration"):
        editor.render_edited_clip(
            source_path=sample_test_video,
            start_seconds=2.0,
            end_seconds=1.0,
        )


def test_render_text_overlay_special_characters_escaping(sample_test_video, tmp_path):
    editor = VideoEditorEngine(output_dir=str(tmp_path))
    out_clip = tmp_path / "special_chars_edit.mp4"

    res = editor.render_edited_clip(
        source_path=sample_test_video,
        start_seconds=0.0,
        end_seconds=1.0,
        aspect_ratio="9:16",
        text_overlay="It's 100% Guaranteed: The Best #1!",
        text_position="top",
        output_file_path=str(out_clip),
    )

    assert os.path.exists(res["file_path"])
    assert res["file_size_bytes"] > 500
