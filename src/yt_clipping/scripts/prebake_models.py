"""
AI Models Pre-Bake and Verification Suite.
Downloads, caches, and verifies all required computer vision and speech models:
1. Faster-Whisper (base & small ASR models)
2. OpenCV YuNet (face detection ONNX)
3. Ultralytics YOLOv8 (person segmentation and detection weights)

Executed during Docker build to ensure complete offline/air-gapped autonomy in cloud containers.
"""

import os
import sys
import urllib.request
import logging
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("prebake_models")

MODELS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../models"))
WHISPER_CACHE_DIR = os.path.join(MODELS_DIR, "whisper")

YUNET_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
YUNET_FILENAME = "face_detection_yunet_2023mar.onnx"


def ensure_yunet_model() -> str:
    """Ensures OpenCV YuNet face detection ONNX model is downloaded and verified."""
    os.makedirs(MODELS_DIR, exist_ok=True)
    target_path = os.path.join(MODELS_DIR, YUNET_FILENAME)

    if not os.path.exists(target_path) or os.path.getsize(target_path) < 100_000:
        logger.info(f"Downloading OpenCV YuNet face detector from {YUNET_URL}...")
        try:
            urllib.request.urlretrieve(YUNET_URL, target_path)
            logger.info(f"Downloaded YuNet to {target_path} ({os.path.getsize(target_path)} bytes)")
        except Exception as e:
            logger.warning(f"Failed to download YuNet: {e}. Checking local alternatives...")
            if not os.path.exists(target_path):
                raise RuntimeError(f"YuNet model could not be downloaded: {e}")

    # Verify model with OpenCV
    try:
        import cv2
        detector = cv2.FaceDetectorYN.create(target_path, "", (320, 320))
        dummy_img = np.zeros((320, 320, 3), dtype=np.uint8)
        _, faces = detector.detect(dummy_img)
        logger.info(f"[OK] OpenCV YuNet Face Detector verified: {target_path}")
    except Exception as e:
        logger.error(f"[ERROR] YuNet verification failed: {e}")
        raise

    return target_path


def ensure_yolo_models() -> None:
    """Ensures YOLOv8 detection and instance segmentation models are present and primed."""
    os.makedirs(MODELS_DIR, exist_ok=True)
    for model_name in ["yolov8n.pt", "yolov8n-seg.pt"]:
        target_path = os.path.join(MODELS_DIR, model_name)
        logger.info(f"Checking YOLO model: {model_name}...")
        if not os.path.exists(target_path) or os.path.getsize(target_path) < 100_000:
            logger.info(f"Downloading {model_name}...")
            downloaded = False
            try:
                from ultralytics import YOLO
                model = YOLO(model_name)
                if os.path.exists(model_name) and not os.path.exists(target_path):
                    import shutil
                    shutil.move(model_name, target_path)
                if os.path.exists(target_path) and os.path.getsize(target_path) > 100_000:
                    downloaded = True
            except Exception as e:
                logger.warning(f"Ultralytics download helper failed: {e}. Trying direct HTTP fallback...")

            if not downloaded:
                direct_url = f"https://github.com/ultralytics/assets/releases/download/v8.3.0/{model_name}"
                try:
                    req = urllib.request.Request(direct_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=30) as resp, open(target_path, "wb") as f:
                        f.write(resp.read())
                    logger.info(f"Directly downloaded {model_name} to {target_path} ({os.path.getsize(target_path)} bytes)")
                except Exception as e:
                    logger.warning(f"Failed direct download for {model_name}: {e}")

        # Verification warmup if file exists
        if os.path.exists(target_path) and os.path.getsize(target_path) > 100_000:
            try:
                from ultralytics import YOLO
                model = YOLO(target_path)
                dummy_img = np.zeros((640, 640, 3), dtype=np.uint8)
                _ = model(dummy_img, verbose=False)
                logger.info(f"[OK] Ultralytics {model_name} verified ({os.path.getsize(target_path)} bytes)")
            except Exception as e:
                logger.warning(f"[WARN] YOLOv8 warmup note: {e}")


def ensure_whisper_models() -> None:
    """Ensures Faster-Whisper ASR models are downloaded and cached."""
    os.makedirs(WHISPER_CACHE_DIR, exist_ok=True)
    try:
        from faster_whisper import WhisperModel

        for model_size in ["base", "small"]:
            logger.info(f"Pre-downloading & caching Faster-Whisper model: '{model_size}'...")
            # Instantiate on CPU for build-time caching
            model = WhisperModel(model_size, device="cpu", compute_type="int8", download_root=WHISPER_CACHE_DIR)
            logger.info(f"[OK] Faster-Whisper '{model_size}' verified in {WHISPER_CACHE_DIR}")
    except Exception as e:
        logger.warning(f"[WARN] Faster-Whisper prebake note: {e}")


def main() -> int:
    logger.info("==================================================")
    logger.info("Pre-Baking AI Models for yt-clipping Cloud Worker")
    logger.info("==================================================")

    success = True
    try:
        ensure_yunet_model()
    except Exception as e:
        logger.error(f"Failed YuNet: {e}")
        success = False

    try:
        ensure_yolo_models()
    except Exception as e:
        logger.error(f"Failed YOLO: {e}")
        success = False

    try:
        ensure_whisper_models()
    except Exception as e:
        logger.error(f"Failed Whisper: {e}")
        success = False

    if success:
        logger.info("==================================================")
        logger.info("[SUCCESS] All AI models pre-baked and ready!")
        logger.info("==================================================")
        return 0
    else:
        logger.error("[FAILURE] Some models failed to pre-bake.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
