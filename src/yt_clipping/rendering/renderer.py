"""
FFmpeg Video Rendering Engine.
Constructs vertical 9:16 filtergraphs with split pads, active-speaker framing,
even-dimension scaling, H.264 yuv420p output, Windows-safe subtitle escaping,
and atomic file promotion.
"""

from typing import Optional, Dict, Any, List
import os
import subprocess
import json
import hashlib
from datetime import datetime, timezone

from ..contracts.models import HighlightCandidate, RenderProfile, RenderedClip, Transcript
from ..contracts.interfaces import Renderer
from .captions import SubtitleGenerator
from .face_tracker import FaceFocusedFramer


class RenderingError(RuntimeError):
    """Raised when video rendering via FFmpeg fails."""
    pass


def escape_ffmpeg_subtitle_path(path: str) -> str:
    """
    Escapes subtitle file paths for FFmpeg libass subtitles filter across Windows and POSIX.
    - Forward slashes instead of backslashes
    - Escape colons (e.g. C: -> C\\:)
    - Escape single quotes
    - Escape square brackets
    """
    norm = path.replace("\\", "/")
    # Escape colons for FFmpeg filter option parsing
    norm = norm.replace(":", "\\:")
    # Escape single quotes
    norm = norm.replace("'", "'\\''")
    # Escape square brackets
    norm = norm.replace("[", "\\[").replace("]", "\\]")
    return norm


class FFmpegRenderer(Renderer):
    """
    Renders highlight candidates using robust FFmpeg filtergraphs.
    Guarantees atomic file promotion, encoder compatibility, and non-synthetic production behavior.
    """

    def __init__(
        self,
        subtitle_generator: Optional[SubtitleGenerator] = None,
        face_framer: Optional[FaceFocusedFramer] = None,
        allow_synthetic: Optional[bool] = None,
    ):
        self.subtitles = subtitle_generator or SubtitleGenerator()
        self.face_framer = face_framer or FaceFocusedFramer()
        if allow_synthetic is None:
            mode = os.environ.get("YT_EXECUTION_MODE", "production").lower()
            if mode == "production":
                self.allow_synthetic = False
            else:
                self.allow_synthetic = os.environ.get("YT_ALLOW_SYNTHETIC", "").lower() in ("1", "true")
        else:
            self.allow_synthetic = allow_synthetic

    def build_filtergraph(
        self,
        profile: RenderProfile,
        subtitle_ass_path: Optional[str] = None,
        crop_override: Optional[str] = None,
    ) -> str:
        """
        Builds FFmpeg video filtergraph for vertical 9:16 cropping.
        Uses explicit split filters to prevent input pad reuse.
        Guarantees even dimensions and compatible scaling.
        """
        w, h = profile.width, profile.height
        # Force even dimensions
        if w % 2 != 0:
            w -= 1
        if h % 2 != 0:
            h -= 1

        escaped_sub = ""
        if subtitle_ass_path and profile.burn_subtitles:
            escaped_path = escape_ffmpeg_subtitle_path(subtitle_ass_path)
            escaped_sub = f",subtitles='{escaped_path}'"

        if profile.layout_mode == "blur_background":
            # BUG-21 fix: split [0:v] into two distinct streams so [0:v] is never reused
            # BUG-22 fix: use scale={w}:-2 to guarantee even height on foreground
            return (
                f"[0:v]split=2[in_bg][in_fg];"
                f"[in_bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=25:5[bg];"
                f"[in_fg]scale={w}:-2[fg];"
                f"[bg][fg]overlay=0:(H-h)/2[comp];"
                f"[comp]setsar=1{escaped_sub}[v]"
            )

        if profile.layout_mode == "split_screen":
            # BUG-21 fix: split [0:v] into two distinct streams for top and bottom crops
            # BUG-22 fix: ensure half-height is an even integer
            half_h = (h // 2) if (h // 2) % 2 == 0 else (h // 2) - 1
            return (
                f"[0:v]split=2[in_top][in_bot];"
                f"[in_top]crop=ih*9/8:ih:0:0,scale={w}:{half_h}[top];"
                f"[in_bot]crop=ih*9/8:ih:iw-ow:0,scale={w}:{half_h}[bot];"
                f"[top][bot]vstack=inputs=2[stacked];"
                f"[stacked]setsar=1{escaped_sub}[v]"
            )

        if profile.layout_mode == "active_speaker":
            # FEATURE-02 dynamic crop framing
            crop_filter = crop_override or f"crop=ih*9/16:ih:(iw-ow)/2:0"
            return f"[0:v]{crop_filter},scale={w}:{h},setsar=1{escaped_sub}[v]"

        # Default Center 9:16 crop
        vf = f"crop=ih*9/16:ih:(iw-ow)/2:0,scale={w}:{h},setsar=1"
        if subtitle_ass_path and profile.burn_subtitles:
            escaped_path = escape_ffmpeg_subtitle_path(subtitle_ass_path)
            vf += f",subtitles='{escaped_path}'"

        return vf

    def build_ffmpeg_command(
        self,
        source_path: str,
        start_seconds: float,
        duration_seconds: float,
        profile: RenderProfile,
        output_path: str,
        subtitle_ass_path: Optional[str] = None,
        crop_override: Optional[str] = None,
    ) -> List[str]:
        """Assembles standard FFmpeg command line arguments with H.264 yuv420p profile."""
        vf = self.build_filtergraph(profile, subtitle_ass_path, crop_override)
        is_complex = profile.layout_mode in ("split_screen", "blur_background", "active_speaker") or ";" in vf or "[v]" in vf
        if is_complex:
            filter_args = ["-filter_complex", vf, "-map", "[v]", "-map", "0:a?"]
        else:
            filter_args = ["-vf", vf]

        # Encoder selection
        codec_args = (
            ["-c:v", profile.vcodec, "-preset", "p4", "-cq", str(profile.crf)]
            if "nvenc" in profile.vcodec.lower()
            else ["-c:v", profile.vcodec, "-preset", "fast", "-crf", str(profile.crf)]
        )

        # BUG-20 fix: explicitly specify -pix_fmt yuv420p for standard MP4 playback compatibility
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", f"{start_seconds:.3f}",
            "-i", source_path,
            "-t", f"{duration_seconds:.3f}",
            *filter_args,
            *codec_args,
            "-pix_fmt", "yuv420p",
            "-c:a", profile.acodec,
            "-b:a", "192k",
            "-movflags", "+faststart",
            output_path,
        ]
        return cmd

    def render_clip(
        self,
        source_path: str,
        candidate: HighlightCandidate,
        profile: RenderProfile,
        output_dir: str,
        transcript: Optional[Transcript] = None,
    ) -> RenderedClip:
        """
        Renders the clip to a temporary path and atomically promotes to final location upon success.
        Raises RenderingError if FFmpeg fails, preventing synthetic fake video in production.
        """
        os.makedirs(output_dir, exist_ok=True)
        suffix = profile.name if profile.layout_mode in profile.name else f"{profile.name}_{profile.layout_mode}"
        clip_name = f"{candidate.video_id}_{candidate.start_seconds:06.1f}_{candidate.end_seconds:06.1f}_{suffix}.mp4"
        final_path = os.path.abspath(os.path.join(output_dir, clip_name))
        temp_path = f"{final_path}.tmp.mp4"
        manifest_path = os.path.abspath(os.path.join(output_dir, f"{clip_name}.manifest.json"))

        # Generate subtitles if requested and transcript is provided
        sub_path = None
        if profile.burn_subtitles and transcript:
            sub_path = os.path.join(output_dir, f"{candidate.candidate_id}.ass")
            self.subtitles.generate_ass(candidate, transcript, sub_path)

        # Compute dynamic crop if active_speaker layout selected
        crop_override = None
        if profile.layout_mode == "active_speaker":
            framer_res = self.face_framer.analyze_crop_window(
                video_path=source_path,
                start_seconds=candidate.start_seconds,
                duration_seconds=candidate.duration_seconds,
            )
            crop_override = framer_res.get("ffmpeg_crop_filter")

        cmd = self.build_ffmpeg_command(
            source_path=source_path,
            start_seconds=candidate.start_seconds,
            duration_seconds=candidate.duration_seconds,
            profile=profile,
            output_path=temp_path,
            subtitle_ass_path=sub_path,
            crop_override=crop_override,
        )

        # Attempt to run FFmpeg CLI
        rendered_via_cli = False
        last_error = ""
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if res.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                rendered_via_cli = True
            else:
                last_error = f"Returncode {res.returncode}: {res.stderr[-500:] if res.stderr else 'No stderr'}"
        except (subprocess.SubprocessError, FileNotFoundError) as ex:
            last_error = str(ex)

        # BUG-23 fix: Do NOT generate dummy MP4 in production!
        if not rendered_via_cli:
            if not self.allow_synthetic:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
                raise RenderingError(
                    f"FFmpeg render failed for clip '{candidate.candidate_id}'. Error: {last_error}"
                )
            else:
                # Deterministic test fixture fallback for isolated unit tests without FFmpeg binary
                self._generate_synthetic_test_clip(temp_path, candidate.duration_seconds, profile)

        # Atomic promotion: replace temp with final path
        if os.path.exists(final_path):
            os.remove(final_path)
        os.replace(temp_path, final_path)

        # Calculate checksum
        sha256 = hashlib.sha256()
        with open(final_path, "rb") as f:
            while chunk := f.read(65536):
                sha256.update(chunk)
        file_hash = sha256.hexdigest()

        rendered_clip = RenderedClip(
            clip_id=f"clip-{candidate.candidate_id}",
            job_id=f"job-{candidate.candidate_id}",
            candidate_id=candidate.candidate_id,
            file_path=final_path,
            file_hash=file_hash,
            duration_seconds=candidate.duration_seconds,
            width=profile.width,
            height=profile.height,
            manifest_path=manifest_path,
            rendered_at=datetime.now(timezone.utc).isoformat(),
        )

        # Write provenance manifest
        manifest_data = {
            "clip_id": rendered_clip.clip_id,
            "candidate_id": candidate.candidate_id,
            "video_id": candidate.video_id,
            "start_seconds": candidate.start_seconds,
            "end_seconds": candidate.end_seconds,
            "duration_seconds": candidate.duration_seconds,
            "profile": profile.to_dict(),
            "file_path": rendered_clip.file_path,
            "file_hash": rendered_clip.file_hash,
            "score": candidate.score,
            "score_breakdown": candidate.breakdown.to_dict(),
            "rendered_at": rendered_clip.rendered_at,
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)

        return rendered_clip

    def _generate_synthetic_test_clip(
        self, output_path: str, duration_seconds: float, profile: RenderProfile
    ) -> None:
        """
        Creates a test fixture MP4 container with valid atom markers for unit tests.
        """
        ftyp = b'\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2mp41\x00\x00\x00\x08free'
        payload_size = max(int(duration_seconds * 1024), 2048)
        mdat_hdr = len(payload_size.to_bytes(4, 'big') + b'mdat' + (b'\x00' * payload_size)).to_bytes(4, 'big') + b'mdat'
        payload = b'\x00' * payload_size
        moov = b'\x00\x00\x00\x18moov\x00\x00\x00\x10mvhd\x00\x00\x00\x00\x00\x00\x00\x00'

        with open(output_path, "wb") as f:
            f.write(ftyp + mdat_hdr + payload + moov)
