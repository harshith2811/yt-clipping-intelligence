"""
Active-Speaker Detection and Dynamic Video Framing Engine using OpenCV.
Produces portrait (9:16) crops from landscape footage by:
1. Frame sampling across candidate time windows.
2. Multi-face detection with Haar Cascade / DNN fallbacks.
3. EMA (Exponential Moving Average) temporal smoothing.
4. Scene-boundary aware crop stabilization.
5. Deterministic, safe center-crop fallback.
"""

from typing import List, Tuple, Optional, Dict, Any
import os
import cv2
import numpy as np


class FaceFocusedFramer:
    """
    Computes smooth, face-focused 9:16 crop coordinates from source video.
    """

    def __init__(
        self,
        sample_fps: float = 3.0,
        ema_alpha: float = 0.20,
        scene_jump_threshold: float = 0.35,  # Fraction of width jump to trigger cut reset
        yunet_model_path: Optional[str] = None,
    ):
        self.sample_fps = sample_fps
        self.ema_alpha = ema_alpha
        self.scene_jump_threshold = scene_jump_threshold
        self.model_type = "haar_cascade"

        # 1. Initialize deep learning YuNet face detector if ONNX weights exist
        self.yunet = None
        yunet_candidates = [
            yunet_model_path,
            "models/face_detection_yunet_2023mar.onnx",
            os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../models/face_detection_yunet_2023mar.onnx")),
        ]
        for yp in yunet_candidates:
            if yp and os.path.exists(yp):
                try:
                    self.yunet = cv2.FaceDetectorYN.create(
                        model=os.path.abspath(yp),
                        config="",
                        input_size=(320, 320),
                        score_threshold=0.55,
                        nms_threshold=0.3,
                        top_k=5000,
                    )
                    self.model_type = "yunet_onnx"
                    break
                except Exception:
                    pass

        # 2. Initialize Haar cascade detector bundled with OpenCV as reliable fallback
        cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        self.face_cascade = cv2.CascadeClassifier(cascade_path)

    def analyze_crop_window(
        self,
        video_path: str,
        start_seconds: float,
        duration_seconds: float,
        target_aspect_ratio: float = 9.0 / 16.0,
    ) -> Dict[str, Any]:
        """
        Samples frames from video over [start_seconds, start_seconds + duration_seconds],
        detects face regions, and computes smoothed crop boundaries.
        Returns crop specifications compatible with FFmpeg crop filters.
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return self._center_crop_fallback(1920, 1080, target_aspect_ratio)

        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

        # Target crop dimensions (guaranteed even numbers)
        crop_h = src_h if src_h % 2 == 0 else src_h - 1
        crop_w = int(crop_h * target_aspect_ratio)
        if crop_w % 2 != 0:
            crop_w -= 1
        crop_w = min(crop_w, src_w)

        # Default center crop X coordinate
        center_x = max(0, (src_w - crop_w) // 2)
        if center_x % 2 != 0:
            center_x -= 1

        # Calculate sampling timestamps
        step_seconds = 1.0 / max(self.sample_fps, 1.0)
        num_samples = max(int(duration_seconds / step_seconds), 1)

        detected_x_positions: List[float] = []
        smoothed_x_positions: List[float] = []
        face_detected_count = 0

        current_smoothed_x = float(center_x)

        for i in range(num_samples):
            t = start_seconds + (i * step_seconds)
            frame_num = int(t * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue

            # Downsample frame for fast detection
            scale = 0.5
            small = cv2.resize(frame, (0, 0), fx=scale, fy=scale)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

            detected_face_box = None

            # 1. Try deep learning YuNet detection first
            if self.yunet is not None:
                try:
                    self.yunet.setInputSize((small.shape[1], small.shape[0]))
                    _, y_faces = self.yunet.detect(small)
                    if y_faces is not None and len(y_faces) > 0:
                        best_y = max(y_faces, key=lambda f: f[2] * f[3])
                        detected_face_box = (
                            int(best_y[0] / scale),
                            int(best_y[1] / scale),
                            int(best_y[2] / scale),
                            int(best_y[3] / scale),
                        )
                except Exception:
                    pass

            # 2. Fallback to Haar Cascade
            if detected_face_box is None:
                faces = self.face_cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.15,
                    minNeighbors=4,
                    minSize=(int(30 * scale), int(30 * scale)),
                )
                if len(faces) > 0:
                    best_face = max(faces, key=lambda f: f[2] * f[3])
                    detected_face_box = (
                        int(best_face[0] / scale),
                        int(best_face[1] / scale),
                        int(best_face[2] / scale),
                        int(best_face[3] / scale),
                    )

            if detected_face_box is not None:
                face_detected_count += 1
                fx = int(detected_face_box[0] + detected_face_box[2] / 2.0)

                # Desired crop X to center on face
                target_x = max(0, min(fx - (crop_w // 2), src_w - crop_w))

                # Check for abrupt scene change jump
                jump_fraction = abs(target_x - current_smoothed_x) / float(src_w)
                if jump_fraction > self.scene_jump_threshold:
                    # Scene cut reset
                    current_smoothed_x = float(target_x)
                else:
                    # Apply EMA temporal smoothing
                    current_smoothed_x = (self.ema_alpha * target_x) + ((1.0 - self.ema_alpha) * current_smoothed_x)

                detected_x_positions.append(float(target_x))
            else:
                # No face detected in this frame: gently relax towards center
                current_smoothed_x = (0.05 * center_x) + (0.95 * current_smoothed_x)

            # Clamp smoothed position within frame bounds
            clamped_x = max(0.0, min(current_smoothed_x, float(src_w - crop_w)))
            smoothed_x_positions.append(clamped_x)

        cap.release()

        # Compute overall representative crop X
        if smoothed_x_positions:
            median_x = int(np.median(smoothed_x_positions))
        else:
            median_x = center_x

        # Ensure even integers for libx264 compatibility
        if median_x % 2 != 0:
            median_x = max(0, median_x - 1)

        confidence = face_detected_count / float(max(num_samples, 1))

        return {
            "crop_w": crop_w,
            "crop_h": crop_h,
            "crop_x": median_x,
            "crop_y": 0,
            "tracking_confidence": round(confidence, 2),
            "face_detected_ratio": round(confidence, 2),
            "ffmpeg_crop_filter": f"crop={crop_w}:{crop_h}:{median_x}:0",
            "is_center_fallback": confidence < 0.20,
        }

    def _center_crop_fallback(self, src_w: int, src_h: int, target_aspect_ratio: float) -> Dict[str, Any]:
        crop_h = src_h if src_h % 2 == 0 else src_h - 1
        crop_w = int(crop_h * target_aspect_ratio)
        if crop_w % 2 != 0:
            crop_w -= 1
        crop_w = min(crop_w, src_w)
        center_x = max(0, (src_w - crop_w) // 2)
        if center_x % 2 != 0:
            center_x -= 1

        return {
            "crop_w": crop_w,
            "crop_h": crop_h,
            "crop_x": center_x,
            "crop_y": 0,
            "tracking_confidence": 0.0,
            "face_detected_ratio": 0.0,
            "ffmpeg_crop_filter": f"crop={crop_w}:{crop_h}:{center_x}:0",
            "is_center_fallback": True,
        }
