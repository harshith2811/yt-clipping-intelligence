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

        # 3. Initialize deep learning YOLOv8 instance segmenter & subject finder
        self.subject_segmenter = None
        try:
            from .subject_segmenter import SubjectSegmenter
            self.subject_segmenter = SubjectSegmenter(device="cpu")
        except Exception:
            pass

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

        # 1. Detect scene shot boundaries across the clip window
        scene_cuts = [0.0]
        if duration_seconds >= 2.0:
            step_cut = max(1, int(fps * 0.20))  # sample 5 times per sec
            start_f = int(start_seconds * fps)
            end_f = int((start_seconds + duration_seconds) * fps)
            prev_h = None
            for f_idx in range(start_f, end_f, step_cut):
                cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
                ret_c, frame_c = cap.read()
                if not ret_c or frame_c is None:
                    break
                gray_c = cv2.cvtColor(frame_c, cv2.COLOR_BGR2GRAY)
                hist_c = cv2.calcHist([gray_c], [0], None, [32], [0, 256])
                cv2.normalize(hist_c, hist_c)
                if prev_h is not None:
                    corr = cv2.compareHist(prev_h, hist_c, cv2.HISTCMP_CORREL)
                    if corr < 0.65:
                        t_rel = round((f_idx - start_f) / fps, 2)
                        if t_rel - scene_cuts[-1] >= 0.5:
                            scene_cuts.append(t_rel)
                prev_h = hist_c
            if scene_cuts[-1] < duration_seconds - 0.2:
                scene_cuts.append(round(duration_seconds, 2))

        # Sample representative frames across shots or clip window
        num_samples = max(min(int(duration_seconds * self.sample_fps), 48), 3)
        step_seconds = duration_seconds / max(num_samples, 1)

        detected_x_positions: List[float] = []
        smoothed_x_positions: List[float] = []
        time_positions: List[Tuple[float, float]] = []
        face_detected_count = 0
        subject_detected_count = 0
        multi_subject_count = 0

        current_smoothed_x = float(center_x)

        for i in range(num_samples):
            t_rel = i * step_seconds
            t = start_seconds + t_rel
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue

            # Downsample frame for fast detection
            scale = 0.5
            small = cv2.resize(frame, (0, 0), fx=scale, fy=scale)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

            focal_x = None

            # 1. Primary: Try deep learning YuNet face detection first
            if self.yunet is not None:
                try:
                    self.yunet.setInputSize((small.shape[1], small.shape[0]))
                    _, y_faces = self.yunet.detect(small)
                    if y_faces is not None and len(y_faces) > 0:
                        best_y = max(y_faces, key=lambda f: f[2] * f[3])
                        fx = int((best_y[0] + best_y[2] / 2.0) / scale)
                        focal_x = fx
                        face_detected_count += 1
                        subject_detected_count += 1
                except Exception:
                    pass

            # 2. Secondary: Fallback to Haar Cascade face detector
            if focal_x is None:
                faces = self.face_cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.15,
                    minNeighbors=4,
                    minSize=(int(30 * scale), int(30 * scale)),
                )
                if len(faces) > 0:
                    best_face = max(faces, key=lambda f: f[2] * f[3])
                    fx = int((best_face[0] + best_face[2] / 2.0) / scale)
                    focal_x = fx
                    face_detected_count += 1
                    subject_detected_count += 1

            # 3. Tertiary: YOLOv8 Person & Subject Saliency
            # Handles turned-away subjects, hooded figures, seated speakers, walking persons
            if self.subject_segmenter is not None:
                try:
                    subjects = self.subject_segmenter.detect_subjects(frame)
                    if subjects:
                        subject_detected_count += 1
                        if len(subjects) >= 2:
                            # Check if multiple subjects are separated by more than crop width
                            xs = sorted([s["center_x"] for s in subjects])
                            if (xs[-1] - xs[0]) > (crop_w * 0.80):
                                multi_subject_count += 1

                        if focal_x is None:
                            # Focus on primary subject with largest visible body area
                            primary_subj = max(subjects, key=lambda s: s["area"])
                            focal_x = primary_subj["center_x"]
                except Exception:
                    pass

            if focal_x is not None:
                # Desired crop X to center on active face or subject
                target_x = max(0, min(focal_x - (crop_w // 2), src_w - crop_w))

                # Check for abrupt scene change jump
                jump_fraction = abs(target_x - current_smoothed_x) / float(src_w)
                if jump_fraction > self.scene_jump_threshold:
                    # Scene cut reset
                    current_smoothed_x = float(target_x)
                else:
                    # Apply EMA temporal smoothing
                    current_smoothed_x = (self.ema_alpha * target_x) + ((1.0 - self.ema_alpha) * current_smoothed_x)

                detected_x_positions.append(float(target_x))
                time_positions.append((t_rel, float(target_x)))
            else:
                # No face or subject detected: gently relax towards center
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

        # Check for dynamic camera shot switch across the window
        dynamic_crop_filter = None
        if len(scene_cuts) >= 3 and len(time_positions) >= 2:
            # Multi-shot piecewise framing
            shot_crops = []
            for s_idx in range(len(scene_cuts) - 1):
                t_s = scene_cuts[s_idx]
                t_e = scene_cuts[s_idx + 1]
                pts = [x for t_pos, x in time_positions if t_s <= t_pos <= t_e]
                if pts:
                    sx = int(np.median(pts))
                else:
                    sx = median_x
                sx = sx if sx % 2 == 0 else max(0, sx - 1)
                sx = max(0, min(sx, src_w - crop_w))
                shot_crops.append((t_s, t_e, sx))

            # Build nested if expression if there is variation across shots
            min_x = min(x for _, _, x in shot_crops)
            max_x = max(x for _, _, x in shot_crops)
            if (max_x - min_x) >= (src_w * 0.10):
                expr = str(shot_crops[-1][2])
                for k in range(len(shot_crops) - 2, -1, -1):
                    t_bound = shot_crops[k][1]
                    x_val = shot_crops[k][2]
                    expr = f"if(lt(t,{t_bound:.2f}),{x_val},{expr})"
                dynamic_crop_filter = f"crop={crop_w}:{crop_h}:'{expr}':0"
        elif len(time_positions) >= 2:
            first_half = [x for t_pos, x in time_positions if t_pos < duration_seconds * 0.5]
            second_half = [x for t_pos, x in time_positions if t_pos >= duration_seconds * 0.5]
            if first_half and second_half:
                med1 = int(np.median(first_half))
                med2 = int(np.median(second_half))
                med1 = med1 if med1 % 2 == 0 else max(0, med1 - 1)
                med2 = med2 if med2 % 2 == 0 else max(0, med2 - 1)
                if abs(med2 - med1) >= (src_w * 0.20):
                    cut_t = duration_seconds * 0.5
                    dynamic_crop_filter = f"crop={crop_w}:{crop_h}:'if(lt(t,{cut_t:.2f}),{med1},{med2})':0"

        face_conf = min(face_detected_count / float(max(num_samples, 1)), 1.0)
        subject_conf = min(subject_detected_count / float(max(num_samples, 1)), 1.0)
        is_multi_subj = (multi_subject_count / float(max(num_samples, 1))) >= 0.30

        crop_filter = dynamic_crop_filter or f"crop={crop_w}:{crop_h}:{median_x}:0"

        return {
            "crop_w": crop_w,
            "crop_h": crop_h,
            "crop_x": median_x,
            "crop_y": 0,
            "tracking_confidence": round(subject_conf, 2),
            "face_detected_ratio": round(face_conf, 2),
            "subject_detected_ratio": round(subject_conf, 2),
            "ffmpeg_crop_filter": crop_filter,
            "is_center_fallback": subject_conf < 0.20,
            "is_dynamic_pan": dynamic_crop_filter is not None,
            "is_multi_subject": is_multi_subj,
            "recommended_layout": "split_screen" if is_multi_subj else ("active_speaker" if subject_conf >= 0.35 else "blur_background"),
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
