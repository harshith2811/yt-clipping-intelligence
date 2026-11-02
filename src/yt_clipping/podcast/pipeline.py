"""
Podcast Short Maker Pipeline.
High-level orchestrator that takes a podcast video interval, performs shot classification,
generates kinetic center subtitles, and renders a 9:16 vertical Short.
"""

from typing import List, Optional, Tuple, Dict, Any
import os
import sys
import shutil
import subprocess
import tempfile
import cv2

from ..contracts.models import HighlightCandidate, Transcript, WordTimestamp
from ..detection.deadair import DeadAirPruner, PruneResult
from .config import PodcastLayoutConfig
from .shot_detector import PodcastShotDetector, PodcastShot, PodcastShotType
from .layout import build_podcast_split_filtergraph, build_podcast_closeup_filtergraph, escape_libass_path
from .captions import PodcastSubtitleGenerator
from ..rendering.cta_overlay import CTAOverlayEngine, CTAConfig



def get_ffmpeg_path() -> str:
    """Finds available FFmpeg binary across Python environment and system PATH."""
    env_bin = os.environ.get("FFMPEG_BINARY")
    if env_bin and os.path.exists(env_bin):
        return env_bin

    scripts_dir = os.path.join(os.path.dirname(sys.executable), "Scripts")
    py_ffmpeg = os.path.join(scripts_dir, "ffmpeg.exe")
    if os.path.exists(py_ffmpeg):
        return py_ffmpeg

    found = shutil.which("ffmpeg")
    return found or "ffmpeg"


class PodcastShortMaker:
    """
    Creates broadcast-grade 9:16 vertical podcast shorts from source footage.
    Supports Stacked Split-Screen, Director Hybrid Cuts, and Center Word-Synced Captions.
    """

    def __init__(
        self,
        config: Optional[PodcastLayoutConfig] = None,
        shot_detector: Optional[PodcastShotDetector] = None,
    ):
        self.config = config or PodcastLayoutConfig()
        self.detector = shot_detector or PodcastShotDetector()
        self.ffmpeg_bin = get_ffmpeg_path()
        self.pruner = DeadAirPruner(dead_air_threshold=self.config.dead_air_threshold)
        self.cta_engine = CTAOverlayEngine()


    def create_short(
        self,
        video_path: str,
        start_sec: float,
        duration_sec: float,
        output_path: str,
        transcript: Optional[Transcript] = None,
        candidate: Optional[HighlightCandidate] = None,
        words_data: Optional[List[Tuple[str, float, float]]] = None,
    ) -> Dict[str, Any]:
        """
        Renders a full podcast short from source video.
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Source video not found: {video_path}")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        # Inspect source dimensions
        cap = cv2.VideoCapture(video_path)
        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 854
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
        cap.release()

        # Step 0: Optional Dead-Air & Pacing Analysis
        prune_result: Optional[PruneResult] = None
        try:
            if words_data:
                wt_list = [WordTimestamp(word=w[0], start=w[1], end=w[2]) for w in words_data]
                prune_result = self.pruner.prune_words(wt_list, clip_start=start_sec, clip_end=start_sec + duration_sec)
            elif candidate and transcript:
                prune_result = self.pruner.prune_candidate(candidate, transcript)
        except Exception:
            pass

        # Step 1: Detect shots in candidate interval
        shots = self.detector.detect_shots(video_path, start_sec=start_sec, duration_sec=duration_sec)

        # Step 2: Generate subtitles if requested
        sub_path = None
        temp_dir = tempfile.mkdtemp(prefix="podcast_render_")
        try:
            if self.config.burn_subtitles:
                sub_gen = PodcastSubtitleGenerator(self.config)
                candidate_sub_path = os.path.join(temp_dir, "subtitles.ass")
                if words_data:
                    sub_gen.generate_from_words(words_data, start_sec, duration_sec, candidate_sub_path)
                    sub_path = candidate_sub_path
                elif candidate and transcript:
                    sub_gen.generate_subtitles(candidate, transcript, candidate_sub_path)
                    sub_path = candidate_sub_path

            # Inject or generate animated CTA overlay if enabled
            if getattr(self.config, "enable_cta", False):
                cta_cfg = CTAConfig(
                    text=getattr(self.config, "cta_text", "Subscribe to this channel for more"),
                    timing=getattr(self.config, "cta_timing", "end"),
                    style=getattr(self.config, "cta_style", "modern_pill"),
                    duration=getattr(self.config, "cta_duration", 3.5),
                )
                if sub_path and os.path.exists(sub_path):
                    self.cta_engine.inject_into_ass_file(
                        sub_path,
                        duration_sec,
                        config=cta_cfg,
                        width=self.config.width,
                        height=self.config.height,
                        layout_mode="split_screen",
                    )
                else:
                    cta_ass_path = os.path.join(temp_dir, "cta_overlay.ass")
                    self.cta_engine.generate_standalone_ass_file(
                        cta_ass_path,
                        duration_sec,
                        config=cta_cfg,
                        width=self.config.width,
                        height=self.config.height,
                        layout_mode="split_screen",
                    )
                    sub_path = cta_ass_path

            # Step 3: Render based on split_mode
            has_closeup = any(s.shot_type == PodcastShotType.SINGLE_CLOSEUP for s in shots)
            use_hybrid = self.config.split_mode == "hybrid" and has_closeup and len(shots) > 1

            # Micro-jump-cut intervals if configured
            active_keep_intervals = (
                prune_result.keep_intervals
                if (self.config.apply_micro_jump_cuts and prune_result and prune_result.dead_air_gaps)
                else None
            )

            if not use_hybrid:
                # Mode A: Single-pass Stacked Split Screen
                self._render_single_pass_stacked(
                    video_path=video_path,
                    start_sec=start_sec,
                    duration_sec=duration_sec,
                    src_w=src_w,
                    src_h=src_h,
                    sub_path=sub_path,
                    output_path=output_path,
                    shots=shots,
                    keep_intervals=active_keep_intervals,
                )
            else:
                # Mode B: Multi-shot Director Hybrid (Stacked on wide, Full on closeup)
                self._render_hybrid_multi_shot(
                    video_path=video_path,
                    start_sec=start_sec,
                    duration_sec=duration_sec,
                    src_w=src_w,
                    src_h=src_h,
                    sub_path=sub_path,
                    output_path=output_path,
                    shots=shots,
                    temp_dir=temp_dir
                )

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        final_duration = (
            round(prune_result.pruned_duration, 2)
            if (active_keep_intervals and prune_result)
            else duration_sec
        )

        return {
            "output_path": output_path,
            "duration_seconds": final_duration,
            "resolution": f"{self.config.width}x{self.config.height}",
            "split_mode": self.config.split_mode,
            "shots_detected": len(shots),
            "shot_breakdown": [s.shot_type.value for s in shots],
            "file_size_bytes": os.path.getsize(output_path),
            "pacing_telemetry": prune_result.to_dict() if prune_result else None,
        }


    def _render_single_pass_stacked(
        self,
        video_path: str,
        start_sec: float,
        duration_sec: float,
        src_w: int,
        src_h: int,
        sub_path: Optional[str],
        output_path: str,
        shots: List[PodcastShot],
        keep_intervals: Optional[List[Tuple[float, float]]] = None,
    ) -> None:
        """Renders stacked split-screen directly in one native FFmpeg pass."""
        # Find best host and guest center X from detected shots
        host_cx = None
        guest_cx = None
        for s in shots:
            if s.host_center_x is not None:
                host_cx = s.host_center_x
                guest_cx = s.guest_center_x
                break

        select_v_expr = None
        select_a_expr = None
        if keep_intervals:
            select_v_expr, select_a_expr = self.pruner.generate_select_expressions(
                keep_intervals, offset_seconds=start_sec
            )

        fg = build_podcast_split_filtergraph(
            src_w=src_w,
            src_h=src_h,
            config=self.config,
            host_cx=host_cx,
            guest_cx=guest_cx,
            subtitle_ass_path=sub_path,
            select_filter_expr=select_v_expr,
        )

        audio_maps = ["-map", "0:a?"]
        if select_a_expr:
            fg += f";[0:a]{select_a_expr}[a]"
            audio_maps = ["-map", "[a]"]

        tmp_out = output_path + ".tmp.mp4"
        cmd = [
            self.ffmpeg_bin, "-y",
            "-ss", f"{start_sec:.3f}",
            "-i", video_path,
            "-t", f"{duration_sec:.3f}",
            "-filter_complex", fg,
            "-map", "[v]",
        ] + audio_maps + [
            "-c:v", self.config.vcodec,
            "-preset", "ultrafast" if self.config.preview else "fast",
            "-crf", str(self.config.crf),
            "-pix_fmt", "yuv420p",
            "-c:a", self.config.acodec,
            tmp_out
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
            raise RuntimeError(f"FFmpeg split render failed:\n{res.stderr[-800:]}")

        os.replace(tmp_out, output_path)

    def _render_hybrid_multi_shot(
        self,
        video_path: str,
        start_sec: float,
        duration_sec: float,
        src_w: int,
        src_h: int,
        sub_path: Optional[str],
        output_path: str,
        shots: List[PodcastShot],
        temp_dir: str,
    ) -> None:
        """Renders individual camera takes and concatenates them with continuous subtitles."""
        part_paths = []
        concat_list = os.path.join(temp_dir, "concat.txt")

        for idx, s in enumerate(shots):
            part_out = os.path.join(temp_dir, f"part_{idx:02d}.mp4")
            abs_shot_start = start_sec + s.start_sec

            if s.shot_type == PodcastShotType.DUAL_WIDE:
                fg = build_podcast_split_filtergraph(
                    src_w=src_w,
                    src_h=src_h,
                    config=self.config,
                    host_cx=s.host_center_x,
                    guest_cx=s.guest_center_x,
                    subtitle_ass_path=None,  # Subtitles burned after concat
                )
                cmd = [
                    self.ffmpeg_bin, "-y",
                    "-ss", f"{abs_shot_start:.3f}",
                    "-i", video_path,
                    "-t", f"{s.duration_sec:.3f}",
                    "-filter_complex", fg,
                    "-map", "[v]", "-map", "0:a?",
                    "-c:v", self.config.vcodec,
                    "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p",
                    "-c:a", self.config.acodec,
                    part_out
                ]
            else:
                # Single close-up shot
                vf = build_podcast_closeup_filtergraph(
                    src_w=src_w,
                    src_h=src_h,
                    config=self.config,
                    speaker_cx=s.speaker_center_x,
                    subtitle_ass_path=None,
                )
                cmd = [
                    self.ffmpeg_bin, "-y",
                    "-ss", f"{abs_shot_start:.3f}",
                    "-i", video_path,
                    "-t", f"{s.duration_sec:.3f}",
                    "-vf", vf,
                    "-c:v", self.config.vcodec,
                    "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p",
                    "-c:a", self.config.acodec,
                    part_out
                ]

            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                raise RuntimeError(f"Shot {idx} render failed:\n{res.stderr[-800:]}")
            part_paths.append(part_out)

        # Write concat demuxer manifest
        with open(concat_list, "w", encoding="utf-8") as f:
            for p in part_paths:
                norm_p = os.path.abspath(p).replace("\\", "/")
                f.write(f"file '{norm_p}'\n")

        merged_raw = os.path.join(temp_dir, "merged.mp4")
        cmd_merge = [
            self.ffmpeg_bin, "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_list,
            "-c", "copy",
            merged_raw
        ]
        res_merge = subprocess.run(cmd_merge, capture_output=True, text=True)
        if res_merge.returncode != 0:
            raise RuntimeError(f"Concat failed:\n{res_merge.stderr[-800:]}")

        # Burn subtitles if provided
        tmp_final = output_path + ".tmp.mp4"
        if sub_path and os.path.exists(sub_path):
            sub_esc = escape_libass_path(sub_path)
            cmd_burn = [
                self.ffmpeg_bin, "-y",
                "-i", merged_raw,
                "-vf", f"subtitles='{sub_esc}'",
                "-c:v", self.config.vcodec,
                "-preset", "ultrafast" if self.config.preview else "fast",
                "-pix_fmt", "yuv420p",
                "-c:a", "copy",
                tmp_final
            ]
            res_burn = subprocess.run(cmd_burn, capture_output=True, text=True)
            if res_burn.returncode != 0:
                raise RuntimeError(f"Subtitle burn failed:\n{res_burn.stderr[-800:]}")
        else:
            shutil.copyfile(merged_raw, tmp_final)

        os.replace(tmp_final, output_path)
