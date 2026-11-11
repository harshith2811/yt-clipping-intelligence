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
import logging
from datetime import datetime, timezone

from ..contracts.models import HighlightCandidate, RenderProfile, RenderedClip, Transcript
from ..contracts.interfaces import Renderer
from .captions import SubtitleGenerator
from .face_tracker import FaceFocusedFramer
from .cta_overlay import CTAOverlayEngine, CTAConfig
from .outro_card import OutroCardEngine, OutroCardConfig


logger = logging.getLogger(__name__)


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
    Guarantees atomic file promotion, encoder compatibility, broadcast polish,
    animated CTA overlays, and non-synthetic production behavior.
    """

    def __init__(
        self,
        subtitle_generator: Optional[SubtitleGenerator] = None,
        face_framer: Optional[FaceFocusedFramer] = None,
        cta_overlay_engine: Optional[CTAOverlayEngine] = None,
        outro_card_engine: Optional[OutroCardEngine] = None,
        allow_synthetic: Optional[bool] = None,
    ):
        self.subtitles = subtitle_generator or SubtitleGenerator()
        self.face_framer = face_framer or FaceFocusedFramer()
        self.cta_engine = cta_overlay_engine or CTAOverlayEngine()
        self.outro_engine = outro_card_engine or OutroCardEngine()
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
        duration_seconds: Optional[float] = None,
    ) -> str:
        """
        Builds FFmpeg video filtergraph for vertical 9:16 cropping.
        Uses explicit split filters to prevent input pad reuse.
        Guarantees even dimensions, compatible scaling, and broadcast fade transitions.
        """
        w, h = profile.width, profile.height
        # Force even dimensions
        if w % 2 != 0:
            w -= 1
        if h % 2 != 0:
            h -= 1

        escaped_sub = ""
        should_burn = (profile.burn_subtitles or getattr(profile, "enable_cta", False))
        if subtitle_ass_path and should_burn:
            escaped_path = escape_ffmpeg_subtitle_path(subtitle_ass_path)
            escaped_sub = f",subtitles='{escaped_path}'"

        # Broadcast Polish: Subtle video hook fade-in and smooth outro fade-out
        fade_vf = ""
        dur = float(duration_seconds) if duration_seconds is not None else 0.0
        if getattr(profile, "enable_pacing_polish", False) and dur > 0.3:
            v_in = min(getattr(profile, "video_fade_in_seconds", 0.15), dur / 2.0)
            v_out = min(getattr(profile, "video_fade_out_seconds", 0.25), dur / 2.0)
            fade_parts = []
            if v_in > 0.0:
                fade_parts.append(f"fade=t=in:st=0:d={v_in:.3f}")
            if v_out > 0.0:
                fade_parts.append(f"fade=t=out:st={dur - v_out:.3f}:d={v_out:.3f}")
            if fade_parts:
                fade_vf = "," + ",".join(fade_parts)

        if profile.layout_mode == "blur_background":
            # BUG-21 fix: split [0:v] into two distinct streams so [0:v] is never reused
            # BUG-22 fix: use scale={w}:-2 to guarantee even height on foreground
            return (
                f"[0:v]split=2[in_bg][in_fg];"
                f"[in_bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=25:5[bg];"
                f"[in_fg]scale={w}:-2[fg];"
                f"[bg][fg]overlay=0:(H-h)/2[comp];"
                f"[comp]setsar=1{escaped_sub}{fade_vf}[v]"
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
                f"[stacked]setsar=1{escaped_sub}{fade_vf}[v]"
            )

        if profile.layout_mode == "active_speaker":
            # FEATURE-02 dynamic crop framing
            crop_filter = crop_override or f"crop=ih*9/16:ih:(iw-ow)/2:0"
            return f"[0:v]{crop_filter},scale={w}:{h},setsar=1{escaped_sub}{fade_vf}[v]"

        # Default Center 9:16 crop
        vf = f"crop=ih*9/16:ih:(iw-ow)/2:0,scale={w}:{h},setsar=1{escaped_sub}{fade_vf}"
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
        """Assembles standard FFmpeg command line arguments with H.264 yuv420p profile and anti-pop audio fades."""
        vf = self.build_filtergraph(
            profile,
            subtitle_ass_path=subtitle_ass_path,
            crop_override=crop_override,
            duration_seconds=duration_seconds,
        )
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

        # Audio filters: A/V sync lock and anti-pop fade-in / outro fade-out
        af_filters = ["aresample=async=1:first_pts=0"]
        if getattr(profile, "enable_pacing_polish", False) and duration_seconds > 0.05:
            a_in = min(getattr(profile, "audio_fade_in_seconds", 0.02), duration_seconds / 2.0)
            a_out = min(getattr(profile, "audio_fade_out_seconds", 0.25), duration_seconds / 2.0)
            if a_in > 0.0:
                af_filters.append(f"afade=t=in:ss=0:d={a_in:.3f}:curve=hsin")
            if a_out > 0.0:
                af_filters.append(f"afade=t=out:st={duration_seconds - a_out:.3f}:d={a_out:.3f}:curve=hsin")
        af_spec = ",".join(af_filters)

        # BUG-20 fix: explicitly specify -pix_fmt yuv420p for standard MP4 playback compatibility
        # Audio sync fix: aresample=async=1 and avoid_negative_ts make_zero locks A/V alignment to PTS 0
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
            "-af", af_spec,
            "-avoid_negative_ts", "make_zero",
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
            generator = self.subtitles
            preset = getattr(profile, "subtitle_preset", None)
            if preset and preset in SubtitleGenerator.STYLE_PRESETS:
                generator = SubtitleGenerator(style_preset=preset)
            generator.generate_ass(candidate, transcript, sub_path)

        # Inject or generate animated CTA overlay if enabled
        if getattr(profile, "enable_cta", False):
            cta_cfg = CTAConfig(
                text=getattr(profile, "cta_text", "Subscribe to this channel for more"),
                timing=getattr(profile, "cta_timing", "end"),
                style=getattr(profile, "cta_style", "modern_pill"),
                duration=getattr(profile, "cta_duration", 3.5),
                safe_zone_margin_bottom=getattr(profile, "cta_margin_bottom", 440),
            )
            if sub_path and os.path.exists(sub_path):
                self.cta_engine.inject_into_ass_file(
                    sub_path,
                    candidate.duration_seconds,
                    config=cta_cfg,
                    width=profile.width,
                    height=profile.height,
                    layout_mode=profile.layout_mode,
                )
            else:
                cta_ass_path = os.path.join(output_dir, f"{candidate.candidate_id}_cta.ass")
                self.cta_engine.generate_standalone_ass_file(
                    cta_ass_path,
                    candidate.duration_seconds,
                    config=cta_cfg,
                    width=profile.width,
                    height=profile.height,
                    layout_mode=profile.layout_mode,
                )
                sub_path = cta_ass_path

        # Compute dynamic framing and auto-layout resolution
        effective_profile = profile
        crop_override = None
        if profile.layout_mode == "auto":
            framer_res = self.face_framer.analyze_crop_window(
                video_path=source_path,
                start_seconds=candidate.start_seconds,
                duration_seconds=candidate.duration_seconds,
            )
            rec_layout = framer_res.get("recommended_layout", "blur_background")
            crop_override = framer_res.get("ffmpeg_crop_filter") if rec_layout == "active_speaker" else None
            # Clone profile with dynamically resolved layout mode
            from dataclasses import replace
            effective_profile = replace(profile, layout_mode=rec_layout)
        elif profile.layout_mode == "active_speaker":
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
            profile=effective_profile,
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

        # Graceful CPU fallback if NVENC failed or is unavailable on this hardware
        if not rendered_via_cli and effective_profile.vcodec == "h264_nvenc":
            logger.warning("NVENC GPU rendering failed or unavailable. Falling back gracefully to CPU libx264.")
            from dataclasses import replace
            cpu_profile = replace(effective_profile, vcodec="libx264")
            cpu_cmd = self.build_ffmpeg_command(
                source_path=source_path,
                start_seconds=candidate.start_seconds,
                duration_seconds=candidate.duration_seconds,
                profile=cpu_profile,
                output_path=temp_path,
                subtitle_ass_path=sub_path,
                crop_override=crop_override,
            )
            try:
                res_cpu = subprocess.run(cpu_cmd, capture_output=True, text=True, timeout=180)
                if res_cpu.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                    rendered_via_cli = True
                else:
                    last_error = f"CPU fallback returncode {res_cpu.returncode}: {res_cpu.stderr[-500:] if res_cpu.stderr else 'No stderr'}"
            except (subprocess.SubprocessError, FileNotFoundError) as ex:
                last_error = f"CPU fallback failed: {ex}"

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

        final_duration = candidate.duration_seconds
        # Render and append dedicated animated outro card if requested
        if getattr(profile, "enable_outro_card", False) and not (self.allow_synthetic and not rendered_via_cli):
            try:
                # 1. Extract final frame of main clip for cinematic blurred backdrop
                last_frame_path = os.path.join(output_dir, f"{candidate.candidate_id}_last_frame.jpg")
                subprocess.run(
                    ["ffmpeg", "-y", "-sseof", "-0.1", "-i", final_path, "-vframes", "1", last_frame_path],
                    capture_output=True,
                    check=False,
                )

                # 2. Build outro card configuration
                channel_title = getattr(profile, "outro_channel_name", None) or getattr(candidate, "video_id", "Subscribe")
                outro_dur = float(getattr(profile, "outro_duration", 2.5))
                outro_cfg = OutroCardConfig(
                    channel_name=channel_title,
                    sub_heading=getattr(profile, "outro_sub_heading", "Thanks for watching!"),
                    cta_prompt=getattr(profile, "outro_prompt", "Turn on notifications for more clips!"),
                    duration=outro_dur,
                    enable_chime=getattr(profile, "enable_outro_chime", True),
                    chime_style=getattr(profile, "outro_chime_style", "soft_zen"),
                    width=profile.width,
                    height=profile.height,
                    fps=float(getattr(profile, "fps", 60) or 60.0),
                )

                # 3. Render standalone outro card MP4
                outro_path = os.path.join(output_dir, f"{candidate.candidate_id}_outro.mp4")
                bg_arg = last_frame_path if os.path.exists(last_frame_path) else None
                self.outro_engine.render_outro_clip(
                    output_mp4_path=outro_path,
                    config=outro_cfg,
                    background_image_path=bg_arg,
                    vcodec=profile.vcodec,
                )

                # 4. Concatenate main clip with outro card
                combined_path = os.path.join(output_dir, f"{candidate.candidate_id}_combined.mp4")
                self.outro_engine.concat_clip_with_outro(
                    main_clip_path=final_path,
                    outro_clip_path=outro_path,
                    output_path=combined_path,
                    vcodec=profile.vcodec,
                )

                # 5. Promote combined clip to final_path
                if os.path.exists(combined_path):
                    if os.path.exists(final_path):
                        os.remove(final_path)
                    os.rename(combined_path, final_path)
                    final_duration += outro_dur

                # Intermediate temp cleanup
                for tmp_file in [last_frame_path, outro_path]:
                    if tmp_file and os.path.exists(tmp_file):
                        try:
                            os.remove(tmp_file)
                        except OSError:
                            pass
            except Exception as outro_err:
                # Graceful degradation: keep original main clip if outro fails
                logger.warning(f"Failed to append outro card: {outro_err}", exc_info=True)

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
            duration_seconds=final_duration,
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
            "loop_affinity_score": getattr(candidate, "loop_affinity_score", 0.0),
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
