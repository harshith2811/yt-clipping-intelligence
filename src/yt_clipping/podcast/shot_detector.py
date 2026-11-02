"""
Podcast Shot and Camera Angle Detector.
Analyzes podcast footage to identify shot cuts and classify camera perspectives:
- DUAL_WIDE: Wide camera view containing both Host and Guest.
- SINGLE_CLOSEUP: Tightly framed camera on the active speaker.
- PANORAMIC: Establishing or audience shot.
"""

from enum import Enum
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any
import os
import cv2
import numpy as np


class PodcastShotType(str, Enum):
    DUAL_WIDE = "dual_wide"
    SINGLE_CLOSEUP = "single_closeup"
    PANORAMIC = "panoramic"


@dataclass
class PodcastShot:
    """Represents a continuous camera take within a podcast candidate clip."""
    shot_index: int
    start_sec: float
    end_sec: float
    duration_sec: float
    shot_type: PodcastShotType
    speaker_center_x: Optional[float] = None
    host_center_x: Optional[float] = None
    guest_center_x: Optional[float] = None


class PodcastShotDetector:
    """
    Detects scene transitions and classifies each shot into dual-speaker wide shot
    or single-speaker close-up using lightweight CV algorithms.
    """

    def __init__(
        self,
        shot_cut_threshold: float = 28.0,
        yolo_model_path: Optional[str] = None,
        use_yolo: bool = True
    ):
        self.shot_cut_threshold = shot_cut_threshold
        self.use_yolo = use_yolo
        self.yolo_model = None

        if self.use_yolo:
            candidates = [
                yolo_model_path,
                "models/yolov8n-pose.pt",
                "models/yolov8s-world.pt",
                os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../models/yolov8n-pose.pt")),
            ]
            for cp in candidates:
                if cp and os.path.exists(cp):
                    try:
                        from ultralytics import YOLO
                        self.yolo_model = YOLO(cp)
                        break
                    except Exception:
                        pass

        # Haar cascade fallback
        cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        self.face_cascade = cv2.CascadeClassifier(cascade_path) if os.path.exists(cascade_path) else None

    def detect_shots(
        self,
        video_path: str,
        start_sec: float = 0.0,
        duration_sec: Optional[float] = None,
    ) -> List[PodcastShot]:
        """
        Scans video file, detects cuts, and classifies shots into dual-wide vs single-closeup.
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            # Fallback to single wide shot
            dur = duration_sec or 10.0
            return [PodcastShot(
                shot_index=0,
                start_sec=start_sec,
                end_sec=start_sec + dur,
                duration_sec=dur,
                shot_type=PodcastShotType.DUAL_WIDE,
                host_center_x=0.25,
                guest_center_x=0.75
            )]

        fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        video_dur = total_frames / fps if fps > 0 else 10.0
        clip_dur = min(duration_sec, video_dur - start_sec) if duration_sec else (video_dur - start_sec)
        clip_dur = max(clip_dur, 1.0)
        end_sec = start_sec + clip_dur

        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 854
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480

        # Step 1: Detect cuts by sampling at 6 FPS
        sample_step = max(int(fps / 6.0), 1)
        start_frame = int(start_sec * fps)
        end_frame = int(end_sec * fps)

        cut_times = [0.0]  # Relative to start_sec
        prev_gray = None

        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        curr_frame_idx = start_frame

        while curr_frame_idx < end_frame:
            ret, frame = cap.read()
            if not ret:
                break

            if (curr_frame_idx - start_frame) % sample_step == 0:
                small = cv2.resize(frame, (160, 90))
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                if prev_gray is not None:
                    diff = cv2.absdiff(gray, prev_gray)
                    mean_val = float(np.mean(diff))
                    if mean_val > self.shot_cut_threshold:
                        rel_t = (curr_frame_idx - start_frame) / fps
                        # Enforce minimum shot duration of 1.0s to avoid jitter
                        if rel_t - cut_times[-1] >= 1.0:
                            cut_times.append(round(rel_t, 2))
                prev_gray = gray

            curr_frame_idx += 1

        if cut_times[-1] < clip_dur - 0.5:
            cut_times.append(round(clip_dur, 2))
        else:
            cut_times[-1] = round(clip_dur, 2)

        # Step 2: Classify each shot
        shots = []
        for i in range(len(cut_times) - 1):
            s_start = cut_times[i]
            s_end = cut_times[i + 1]
            s_dur = s_end - s_start
            if s_dur < 0.2:
                continue

            # Sample middle frame of this shot
            mid_rel = s_start + s_dur / 2.0
            mid_abs_frame = int((start_sec + mid_rel) * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, mid_abs_frame)
            ret, frame = cap.read()
            if not ret:
                shot_type = PodcastShotType.DUAL_WIDE
                speaker_cx = None
                host_cx = src_w * 0.28
                guest_cx = src_w * 0.72
            else:
                shot_type, speaker_cx, host_cx, guest_cx = self._classify_frame(frame, src_w, src_h)

            shots.append(PodcastShot(
                shot_index=i,
                start_sec=round(s_start, 2),
                end_sec=round(s_end, 2),
                duration_sec=round(s_dur, 2),
                shot_type=shot_type,
                speaker_center_x=speaker_cx,
                host_center_x=host_cx,
                guest_center_x=guest_cx
            ))

        cap.release()
        return shots if shots else [PodcastShot(
            shot_index=0,
            start_sec=0.0,
            end_sec=round(clip_dur, 2),
            duration_sec=round(clip_dur, 2),
            shot_type=PodcastShotType.DUAL_WIDE,
            host_center_x=src_w * 0.28,
            guest_center_x=src_w * 0.72
        )]

    def _classify_frame(
        self, frame: np.ndarray, src_w: int, src_h: int
    ) -> Tuple[PodcastShotType, Optional[float], Optional[float], Optional[float]]:
        """
        Analyzes a single frame to detect whether it contains dual speakers or a single close-up.
        """
        # Try YOLO first
        if self.yolo_model is not None:
            try:
                res = self.yolo_model(frame, verbose=False)[0]
                boxes = res.boxes.xyxy.cpu().numpy()
                persons = []
                for b in boxes:
                    bw = b[2] - b[0]
                    bh = b[3] - b[1]
                    # Filter out tiny background people
                    if bw > src_w * 0.10 and bh > src_h * 0.25:
                        cx = (b[0] + b[2]) / 2.0
                        persons.append((cx, b))

                if len(persons) >= 2:
                    # Sort left to right
                    persons.sort(key=lambda p: p[0])
                    host_cx = persons[0][0]
                    guest_cx = persons[-1][0]
                    # Check if they are well separated across left and right
                    if host_cx < src_w * 0.50 and guest_cx > src_w * 0.50:
                        return PodcastShotType.DUAL_WIDE, None, host_cx, guest_cx
                    return PodcastShotType.DUAL_WIDE, None, host_cx, guest_cx
                elif len(persons) == 1:
                    speaker_cx = persons[0][0]
                    return PodcastShotType.SINGLE_CLOSEUP, speaker_cx, None, None
            except Exception:
                pass

        # Fallback to Haar Cascade face detector
        if self.face_cascade is not None:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=4, minSize=(40, 40))
            if len(faces) >= 2:
                sorted_faces = sorted(faces, key=lambda f: f[0])
                h_cx = sorted_faces[0][0] + sorted_faces[0][2] / 2.0
                g_cx = sorted_faces[-1][0] + sorted_faces[-1][2] / 2.0
                return PodcastShotType.DUAL_WIDE, None, h_cx, g_cx
            elif len(faces) == 1:
                cx = faces[0][0] + faces[0][2] / 2.0
                return PodcastShotType.SINGLE_CLOSEUP, cx, None, None

        # Default fallback: wide shot
        return PodcastShotType.DUAL_WIDE, None, src_w * 0.28, src_w * 0.72
