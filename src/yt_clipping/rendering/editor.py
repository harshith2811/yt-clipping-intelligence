"""
Manual Video Editor Engine.
Provides frame extraction, millisecond-accurate trimming, multi-aspect-ratio
re-composition (9:16, 16:9, 1:1), pan/crop positioning, custom text overlays,
and multi-clip batch export integrated with ProjectStore.
"""

from typing import Dict, Any, Optional, List, Tuple
import os
import subprocess
import json
import uuid
import logging
import hashlib
import tempfile
from datetime import datetime, timezone

from ..orchestration.project_store import ProjectStore, ClipSidecarRecord

logger = logging.getLogger("yt_clipping.rendering.editor")

TARGET_RESOLUTIONS = {
    "9:16": {"width": 1080, "height": 1920, "label": "Vertical Short / Reel (9:16)"},
    "16:9": {"width": 1920, "height": 1080, "label": "Landscape Standard (16:9)"},
    "1:1": {"width": 1080, "height": 1080, "label": "Square Social (1:1)"},
}


class VideoEditorEngine:
    """
    Modular video editing engine utilizing FFmpeg for high-performance,
    synchronization-safe video clipping, cropping, and composition.
    """

    def __init__(self, output_dir: Optional[str] = None):
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self.output_dir = output_dir or os.path.join(base_dir, "data", "rendered_clips")
        os.makedirs(self.output_dir, exist_ok=True)

    def get_video_metadata(self, file_path: str) -> Dict[str, Any]:
        """Probes video dimensions, duration, and frame rate via ffmpeg."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Source video not found: {file_path}")

        cmd = ["ffmpeg", "-hide_banner", "-i", file_path]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
            stderr = res.stderr
            import re
            m_dim = re.search(r"Stream.*Video:.*?(\d{2,5})x(\d{2,5})", stderr)
            m_dur = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)

            width = int(m_dim.group(1)) if m_dim else 1920
            height = int(m_dim.group(2)) if m_dim else 1080
            duration = 60.0
            if m_dur:
                h, m, s = float(m_dur.group(1)), float(m_dur.group(2)), float(m_dur.group(3))
                duration = h * 3600.0 + m * 60.0 + s

            size_bytes = os.path.getsize(file_path)
            return {
                "width": width,
                "height": height,
                "duration": duration,
                "size_bytes": size_bytes,
                "file_path": file_path,
            }
        except Exception as e:
            logger.warning(f"ffmpeg probe failed for {file_path}: {e}")
            size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
            return {"width": 1920, "height": 1080, "duration": 60.0, "size_bytes": size, "file_path": file_path}

    def extract_frame_preview(
        self,
        file_path: str,
        timestamp_s: float,
        output_image_path: Optional[str] = None,
    ) -> str:
        """Extracts a single frame JPEG at the given timestamp for scrubbing inspection."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Source video not found: {file_path}")

        if not output_image_path:
            frame_id = f"frame_{uuid.uuid4().hex[:8]}_{int(timestamp_s * 1000)}.jpg"
            output_image_path = os.path.join(self.output_dir, frame_id)

        cmd = [
            "ffmpeg",
            "-y",
            "-ss", f"{max(0.0, timestamp_s):.3f}",
            "-i", file_path,
            "-vframes", "1",
            "-q:v", "2",
            output_image_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0 or not os.path.exists(output_image_path):
            raise RuntimeError(f"FFmpeg frame extraction failed: {res.stderr}")
        return output_image_path

    def build_crop_filter(
        self,
        in_w: int,
        in_h: int,
        target_aspect: str = "9:16",
        center_x: float = 0.5,
        center_y: float = 0.5,
    ) -> Tuple[str, int, int]:
        """
        Computes crop parameters and scale filter preserving subject matter.
        center_x: 0.0 (far left) to 1.0 (far right), 0.5 is centered.
        """
        cfg = TARGET_RESOLUTIONS.get(target_aspect, TARGET_RESOLUTIONS["9:16"])
        out_w, out_h = cfg["width"], cfg["height"]
        target_ratio = out_w / out_h
        in_ratio = in_w / in_h

        if in_ratio > target_ratio:
            # Source is wider than target -> Crop width, preserve full height
            crop_h = in_h
            crop_w = int(crop_h * target_ratio)
            if crop_w % 2 != 0:
                crop_w -= 1
            max_x = max(0, in_w - crop_w)
            crop_x = int(max(0, min(max_x, (in_w * center_x) - (crop_w / 2))))
            if crop_x % 2 != 0:
                crop_x = max(0, crop_x - 1)
            crop_y = 0
        else:
            # Source is taller than target -> Crop height, preserve full width
            crop_w = in_w
            crop_h = int(crop_w / target_ratio)
            if crop_h % 2 != 0:
                crop_h -= 1
            max_y = max(0, in_h - crop_h)
            crop_x = 0
            crop_y = int(max(0, min(max_y, (in_h * center_y) - (crop_h / 2))))
            if crop_y % 2 != 0:
                crop_y = max(0, crop_y - 1)

        filter_str = f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={out_w}:{out_h}"
        return filter_str, out_w, out_h

    def render_edited_clip(
        self,
        source_path: str,
        start_seconds: float,
        end_seconds: float,
        aspect_ratio: str = "9:16",
        center_x: float = 0.5,
        center_y: float = 0.5,
        text_overlay: Optional[str] = None,
        text_position: str = "top",
        output_file_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Renders an edited video clip with precision trimming, aspect ratio conversion,
        and optional text overlay, guaranteeing audio/video synchronization.
        """
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Source video not found: {source_path}")

        duration = end_seconds - start_seconds
        if duration <= 0:
            raise ValueError(f"Invalid duration: start ({start_seconds}) must be strictly less than end ({end_seconds})")

        meta = self.get_video_metadata(source_path)
        crop_filter, out_w, out_h = self.build_crop_filter(
            meta["width"], meta["height"], aspect_ratio, center_x, center_y
        )

        filter_chains = [crop_filter]

        temp_text_path = None
        try:
            # Add optional text overlay
            if text_overlay and text_overlay.strip():
                # Write text to a UTF-8 temp file to safely support quotes, colons, %, and unicode
                with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt", encoding="utf-8") as tf:
                    tf.write(text_overlay.strip())
                    temp_text_path = tf.name

                # Escape Windows path backslashes and colons for ffmpeg filtergraph
                esc_tf_path = temp_text_path.replace("\\", "/").replace(":", "\\:")

                # Position logic
                if text_position == "top":
                    y_pos = "h*0.10"
                elif text_position == "center":
                    y_pos = "(h-text_h)/2"
                else:  # bottom
                    y_pos = "h*0.82"

                drawtext = (
                    f"drawtext=textfile='{esc_tf_path}':fontcolor=white:fontsize=42:"
                    f"box=1:boxcolor=black@0.65:boxborderw=14:x=(w-text_w)/2:y={y_pos}"
                )
                filter_chains.append(drawtext)

            full_filter = ",".join(filter_chains)

            if not output_file_path:
                cid = f"clip_edit_{uuid.uuid4().hex[:8]}"
                output_file_path = os.path.join(self.output_dir, f"{cid}.mp4")

            # Command ensures frame-accurate seek and perfect A/V alignment
            cmd = [
                "ffmpeg",
                "-y",
                "-ss", f"{max(0.0, start_seconds):.3f}",
                "-to", f"{end_seconds:.3f}",
                "-i", source_path,
                "-vf", full_filter,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "20",
                "-c:a", "aac",
                "-b:a", "192k",
                "-avoid_negative_ts", "make_zero",
                output_file_path,
            ]

            logger.info(f"Rendering edited clip: {' '.join(cmd)}")
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0 or not os.path.exists(output_file_path):
                raise RuntimeError(f"FFmpeg rendering failed: {res.stderr}")
        finally:
            if temp_text_path and os.path.exists(temp_text_path):
                try:
                    os.unlink(temp_text_path)
                except Exception as e:
                    logger.debug(f"Failed to cleanup temp text file {temp_text_path}: {e}")

        file_size = os.path.getsize(output_file_path)
        return {
            "file_path": output_file_path,
            "filename": os.path.basename(output_file_path),
            "duration_seconds": round(duration, 2),
            "width": out_w,
            "height": out_h,
            "aspect_ratio": aspect_ratio,
            "file_size_bytes": file_size,
            "file_size_mb": round(file_size / (1024 * 1024), 2),
            "rendered_at": datetime.now(timezone.utc).isoformat(),
        }

    def export_multiple_clips(
        self,
        source_path: str,
        clips_specs: List[Dict[str, Any]],
        project_id: str,
        project_store: ProjectStore,
    ) -> List[ClipSidecarRecord]:
        """
        Renders multiple clip specifications from a single source video and registers
        each newly generated clip into the ProjectStore asset registry.
        """
        results: List[ClipSidecarRecord] = []
        video_id = project_id.replace("proj_", "").replace("project_", "")

        for idx, spec in enumerate(clips_specs):
            start_s = float(spec.get("start_seconds", 0.0))
            end_s = float(spec.get("end_seconds", 30.0))
            title = spec.get("title") or f"Manual Clip {idx + 1}"
            aspect_ratio = spec.get("aspect_ratio", "9:16")
            center_x = float(spec.get("center_x", 0.5))
            text_overlay = spec.get("text_overlay")

            clip_id = f"c_manual_{uuid.uuid4().hex[:6]}"
            target_filename = f"clip_{video_id}_{clip_id}.mp4"
            target_path = os.path.join(self.output_dir, target_filename)

            rendered = self.render_edited_clip(
                source_path=source_path,
                start_seconds=start_s,
                end_seconds=end_s,
                aspect_ratio=aspect_ratio,
                center_x=center_x,
                text_overlay=text_overlay,
                output_file_path=target_path,
            )

            sidecar = ClipSidecarRecord(
                clip_id=clip_id,
                project_id=project_id,
                video_id=video_id,
                file_path=target_path,
                relative_url=f"/clips/{target_filename}",
                start_seconds=start_s,
                end_seconds=end_s,
                duration_seconds=rendered["duration_seconds"],
                score=float(spec.get("score", 90.0)),
                candidate_data={
                    "hook_title": title,
                    "suggested_description": spec.get("description", f"Extracted clip: {title} #shorts"),
                },
                status="COMPLETED",
                file_size_bytes=rendered["file_size_bytes"],
            )

            project_store.save_clip_sidecar(sidecar)
            results.append(sidecar)

        return results
