"""
Deep Learning Subject Finding, Tracking, and Segmentation Engine.
Powered by YOLOv8 detection & instance segmentation models.
Identifies human subjects, computes segmentation masks, and determines
salient bounding boxes for portrait (9:16) video reframing.
"""

from typing import List, Dict, Any, Optional, Tuple
import os
import cv2
import numpy as np


class SubjectSegmenter:
    """
    Finds and segments subjects (e.g. persons) in video frames using YOLOv8.
    Computes subject bounding boxes, centroids, and segmentation masks.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        confidence_threshold: float = 0.45,
        target_classes: Optional[List[int]] = None,
        device: str = "cpu",
    ):
        self.confidence_threshold = confidence_threshold
        # Class 0 in COCO is "person"
        self.target_classes = target_classes or [0]
        self.device = device

        # Resolve model path
        resolved_path = None
        candidates = [
            model_path,
            "models/yolov8n-seg.pt",
            "models/yolov8n.pt",
            os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../models/yolov8n-seg.pt")),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../models/yolov8n.pt")),
        ]
        for c in candidates:
            if c and os.path.exists(c) and os.path.getsize(c) > 100000:
                resolved_path = os.path.abspath(c)
                break

        self.model = None
        self.model_path = resolved_path
        if resolved_path:
            try:
                from ultralytics import YOLO
                self.model = YOLO(resolved_path)
            except Exception:
                pass

    def detect_subjects(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """
        Detects target subjects (persons) in a frame.
        Returns list of dicts with bounding boxes [x1, y1, x2, y2], confidence, and class.
        """
        if self.model is None or frame is None:
            return []

        try:
            results = self.model(frame, verbose=False, conf=self.confidence_threshold, device=self.device)
            subjects = []
            for r in results:
                boxes = r.boxes
                if boxes is None or len(boxes) == 0:
                    continue
                for box in boxes:
                    cls_id = int(box.cls[0].item())
                    if cls_id in self.target_classes:
                        xyxy = box.xyxy[0].tolist()
                        conf = float(box.conf[0].item())
                        subjects.append({
                            "class_id": cls_id,
                            "confidence": round(conf, 3),
                            "box": [int(xyxy[0]), int(xyxy[1]), int(xyxy[2]), int(xyxy[3])],
                            "center_x": int((xyxy[0] + xyxy[2]) / 2.0),
                            "center_y": int((xyxy[1] + xyxy[3]) / 2.0),
                            "area": int((xyxy[2] - xyxy[0]) * (xyxy[3] - xyxy[1])),
                        })
            return subjects
        except Exception:
            return []

    def get_salient_subject_center(self, frame: np.ndarray) -> Optional[int]:
        """
        Finds the primary subject in the frame and returns its horizontal center coordinate X.
        """
        subjects = self.detect_subjects(frame)
        if not subjects:
            return None
        # Select subject with largest area (closest to camera / most prominent)
        primary = max(subjects, key=lambda s: s["area"])
        return primary["center_x"]
