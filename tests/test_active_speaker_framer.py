"""
Tests for Active-Speaker Face-Focused Framing and Video Cropping Engine.
"""

import os
import cv2
import numpy as np
import pytest

from src.yt_clipping.rendering.face_tracker import FaceFocusedFramer
from src.yt_clipping.rendering.renderer import FFmpegRenderer
from src.yt_clipping.contracts.models import RenderProfile, HighlightCandidate, ScoreBreakdown


def test_face_framer_fallback_on_missing_file():
    framer = FaceFocusedFramer()
    result = framer.analyze_crop_window("nonexistent_video.mp4", start_seconds=0.0, duration_seconds=5.0)

    assert result["is_center_fallback"] is True
    assert result["tracking_confidence"] == 0.0
    assert result["crop_w"] % 2 == 0
    assert result["crop_h"] % 2 == 0
    assert result["crop_x"] % 2 == 0
    assert "crop=" in result["ffmpeg_crop_filter"]


def test_face_framer_with_synthetic_video(tmp_path):
    framer = FaceFocusedFramer(sample_fps=5.0)
    video_path = str(tmp_path / "synthetic_interview.mp4")

    # Create a 2-second synthetic 1280x720 video with OpenCV
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(video_path, fourcc, 10.0, (1280, 720))

    # Draw frames with an off-center circle/shape
    for i in range(20):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        # Draw a simulated subject around x=850
        cv2.circle(frame, (850, 360), 100, (200, 200, 200), -1)
        out.write(frame)
    out.release()

    res = framer.analyze_crop_window(video_path, start_seconds=0.0, duration_seconds=2.0)

    assert res["crop_w"] > 0
    assert res["crop_h"] > 0
    assert res["crop_w"] % 2 == 0
    assert res["crop_h"] % 2 == 0
    assert res["crop_x"] % 2 == 0
    assert res["crop_x"] + res["crop_w"] <= 1280
    assert "ffmpeg_crop_filter" in res
    assert res["ffmpeg_crop_filter"].startswith(f"crop={res['crop_w']}:{res['crop_h']}")


def test_active_speaker_renderer_filtergraph():
    renderer = FFmpegRenderer()
    profile = RenderProfile(layout_mode="active_speaker", width=1080, height=1920)

    # Active speaker with override filter
    custom_crop = "crop=608:1080:336:0"
    vf = renderer.build_filtergraph(profile, subtitle_ass_path="subs.ass", crop_override=custom_crop)

    assert custom_crop in vf
    assert "scale=1080:1920" in vf
    assert "subtitles='subs.ass'" in vf


def test_subject_aware_multi_subject_detection(tmp_path):
    framer = FaceFocusedFramer(sample_fps=2.0)
    video_path = str(tmp_path / "multi_subject.mp4")

    # Create synthetic video with two distinct persons on left (x=150) and right (x=1100)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(video_path, fourcc, 10.0, (1280, 720))
    for _ in range(15):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        # Person 1 (left)
        cv2.rectangle(frame, (100, 200), (300, 680), (180, 180, 180), -1)
        # Person 2 (right)
        cv2.rectangle(frame, (980, 200), (1180, 680), (180, 180, 180), -1)
        out.write(frame)
    out.release()

    res = framer.analyze_crop_window(video_path, start_seconds=0.0, duration_seconds=1.5)
    assert "recommended_layout" in res
    assert "is_multi_subject" in res
    assert "subject_detected_ratio" in res


def test_dynamic_camera_cut_expression(tmp_path):
    framer = FaceFocusedFramer(sample_fps=3.0, scene_jump_threshold=0.20)
    video_path = str(tmp_path / "camera_cut.mp4")

    # Create video where subject starts on far left (x=150) for 1s, then camera cuts to far right (x=1050)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(video_path, fourcc, 10.0, (1280, 720))
    for i in range(20):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        center_x = 150 if i < 10 else 1050
        cv2.circle(frame, (center_x, 360), 80, (255, 255, 255), -1)
        out.write(frame)
    out.release()

    res = framer.analyze_crop_window(video_path, start_seconds=0.0, duration_seconds=2.0)
    assert "crop_w" in res
    assert "crop_h" in res
    assert "ffmpeg_crop_filter" in res

