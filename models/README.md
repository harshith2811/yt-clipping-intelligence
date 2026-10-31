# ML Models Directory

This directory stores deep learning model weights used for visual reframing, active speaker tracking, and subject segmentation:

1. `face_detection_yunet_2023mar.onnx` (~232 KB):
   OpenCV YuNet ONNX deep learning face detector for precise active-speaker tracking.
   Download URL: `https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx`

2. `yolov8n-seg.pt` (~7 MB):
   Ultralytics YOLOv8 nano instance segmentation model for human subject identification and centroid tracking.
   Automatically downloaded on first run by Ultralytics or available via `yt-clip doctor`.

3. `yolov8n.pt` (~6.5 MB):
   Ultralytics YOLOv8 nano object detector.
