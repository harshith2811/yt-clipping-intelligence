"""
Tests for AI TTS Narration, Subject Tracking, Face Detection & Segmentation Models.
"""

import os
import cv2
import numpy as np
import pytest

from src.yt_clipping.audio.tts_engine import TTSEngine
from src.yt_clipping.rendering.face_tracker import FaceFocusedFramer
from src.yt_clipping.rendering.subject_segmenter import SubjectSegmenter


def test_tts_engine_synthesis(tmp_path):
    engine = TTSEngine(cache_dir=str(tmp_path / "tts_cache"))
    out_file = str(tmp_path / "voiceover.mp3")

    path = engine.synthesize(
        text="Testing automated AI narration synthesis.",
        output_path=out_file,
    )

    assert os.path.exists(path)
    assert os.path.getsize(path) > 1000
    assert path.endswith(".mp3")


def test_face_tracker_with_yunet_model():
    yunet_path = "models/face_detection_yunet_2023mar.onnx"
    assert os.path.exists(yunet_path), "YuNet model weights missing"

    framer = FaceFocusedFramer(yunet_model_path=yunet_path)
    assert framer.model_type == "yunet_onnx"
    assert framer.yunet is not None


def test_subject_segmenter_with_yolo():
    yolo_path = "models/yolov8n-seg.pt"
    assert os.path.exists(yolo_path), "YOLOv8 segmentation model weights missing"

    segmenter = SubjectSegmenter(model_path=yolo_path)
    assert segmenter.model is not None

    # Create dummy RGB frame with a simulated person shape
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.rectangle(frame, (250, 100), (390, 420), (255, 255, 255), -1)

    # Detect subjects
    subjects = segmenter.detect_subjects(frame)
    # The method runs successfully without crashing
    assert isinstance(subjects, list)


def test_faster_whisper_model_operational():
    from faster_whisper import WhisperModel
    # Verify faster-whisper base model loads
    model = WhisperModel("base", device="cpu", compute_type="int8")
    assert model is not None
