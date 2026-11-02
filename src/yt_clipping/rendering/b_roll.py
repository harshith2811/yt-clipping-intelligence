"""
Automated B-Roll Overlay Engine (Adapted from ShortGPT asset sourcing mechanics).
Identifies continuous speech monologues in short-form content, extracts content keywords,
fuzzy-matches local stock footage, and builds composite FFmpeg filtergraphs with
smooth 0.25s alpha fade transitions, 9:16 vertical scaling, and optional audio ducking.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple, Any, Set
import os
import re
import subprocess
import shutil
import hashlib
from collections import Counter
from datetime import datetime, timezone

from ..contracts.models import HighlightCandidate, Transcript, WordTimestamp
from ..scoring.packaging_linter import GENERIC_STOP_WORDS, LAZY_ADJECTIVES_MAP
from ..detection.deadair import STANDALONE_FILLER_WORDS

# Common conversational English stop words to filter during keyword extraction
EXTRA_STOP_WORDS: Set[str] = {
    "with", "from", "that", "this", "have", "about", "there", "their", "they",
    "what", "when", "where", "which", "will", "would", "could", "should",
    "your", "just", "more", "some", "been", "were", "them", "then", "into",
    "also", "than", "very", "much", "such", "only", "other", "after", "before",
    "over", "under", "again", "because", "being", "both", "down", "each",
    "here", "most", "same", "then", "through", "well", "what", "really",
    "going", "know", "like", "want", "think", "make", "take", "come", "good",
    "people", "time", "year", "years", "said", "look", "first", "give", "tell",
    "at", "as", "by", "on", "or", "if", "my", "me", "we", "he", "so", "no", "up", "do", "go", "am", "be", "us",
}


@dataclass(frozen=True)
class MonologueInterval:
    """Represents a speech segment requiring visual reinforcement via B-roll."""
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    text: str
    keywords: List[str] = field(default_factory=list)
    matched_asset_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BRollConfig:
    """Configurable parameters for B-roll detection and compositing."""
    min_monologue_duration: float = 4.0      # Continuous speech >= 4.0s triggers B-roll
    max_overlay_duration: float = 5.0        # Individual overlay cap to avoid losing speaker
    min_overlay_duration: float = 2.0        # Minimum overlay duration
    fade_duration: float = 0.25              # Fade-in and fade-out duration (seconds)
    pause_break_threshold: float = 0.5       # Pauses > 0.5s are considered natural breaks
    mute_broll: bool = True                  # Default stock footage to muted
    audio_ducking_volume: float = 0.4        # Primary audio volume during B-roll if unmuted
    broll_audio_volume: float = 0.3          # B-roll audio volume if unmuted
    assets_dir: str = "assets/broll"         # Default search path for stock clips
    width: int = 1080                        # Target vertical width
    height: int = 1920                       # Target vertical height
    vcodec: str = "libx264"
    crf: int = 22


@dataclass
class BRollOverlayResult:
    """Provenance telemetry resulting from B-roll overlay execution."""
    applied: bool
    input_video_path: str
    output_video_path: str
    monologue_intervals: List[MonologueInterval] = field(default_factory=list)
    matched_assets: List[str] = field(default_factory=list)
    filtergraph: str = ""
    file_hash: str = ""
    telemetry: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "applied": self.applied,
            "input_video_path": self.input_video_path,
            "output_video_path": self.output_video_path,
            "monologue_intervals": [m.to_dict() for m in self.monologue_intervals],
            "matched_assets": self.matched_assets,
            "filtergraph": self.filtergraph,
            "file_hash": self.file_hash,
            "telemetry": self.telemetry,
        }


def _compute_sha256(filepath: str) -> str:
    """Computes SHA-256 hash of a file efficiently."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class BRollOverlayEngine:
    """
    Automated B-Roll Overlay Engine.
    Detects monologue sections, extracts high-value keywords, fuzzy matches stock footage,
    and composites professional alpha-faded overlays.
    """

    def __init__(self, config: Optional[BRollConfig] = None):
        self.config = config or BRollConfig()

    def detect_monologue_intervals(
        self,
        words: List[WordTimestamp],
        clip_start: float = 0.0,
        clip_end: Optional[float] = None,
        candidate: Optional[HighlightCandidate] = None,
    ) -> List[MonologueInterval]:
        """
        Analyzes word timestamps to detect runs of continuous speech >= min_monologue_duration (4.0s)
        where inter-word pauses do not exceed pause_break_threshold (0.5s).
        Returns intervals expressed relative to clip_start.
        """
        if not words:
            return []

        # Filter words within the active clip window
        valid_words = [
            w for w in words
            if (clip_end is None or w.start < clip_end) and w.end > clip_start
        ]
        if not valid_words:
            return []

        # Group words into continuous speech runs
        runs: List[List[WordTimestamp]] = []
        current_run: List[WordTimestamp] = [valid_words[0]]

        for i in range(1, len(valid_words)):
            prev_w = valid_words[i - 1]
            curr_w = valid_words[i]
            pause = curr_w.start - prev_w.end

            if pause > self.config.pause_break_threshold:
                runs.append(current_run)
                current_run = [curr_w]
            else:
                current_run.append(curr_w)

        if current_run:
            runs.append(current_run)

        intervals: List[MonologueInterval] = []
        for run in runs:
            run_start = run[0].start
            run_end = run[-1].end
            run_dur = run_end - run_start

            if run_dur >= self.config.min_monologue_duration:
                # Provide a 0.5s visual lead-in for speaker continuity if run duration permits
                lead_in = 0.5 if (run_dur - 0.5 >= self.config.min_overlay_duration) else 0.0
                overlay_start = run_start + lead_in
                overlay_dur = min(run_end - overlay_start, self.config.max_overlay_duration)

                if overlay_dur >= self.config.min_overlay_duration:
                    start_rel = round(max(0.0, overlay_start - clip_start), 3)
                    end_rel = round(start_rel + overlay_dur, 3)
                    run_text = " ".join(w.word for w in run)
                    keywords = self.extract_keywords(run_text, candidate=candidate)

                    intervals.append(
                        MonologueInterval(
                            start_seconds=start_rel,
                            end_seconds=end_rel,
                            duration_seconds=round(overlay_dur, 3),
                            text=run_text,
                            keywords=keywords,
                        )
                    )

        return intervals

    def extract_keywords(
        self,
        text: str,
        candidate: Optional[HighlightCandidate] = None,
    ) -> List[str]:
        """
        Extracts content nouns, verbs, and topic tokens while filtering generic stop words,
        filler words, and lazy buzzwords.
        """
        tokens = re.findall(r"\b[a-zA-Z]{2,}\b", text.lower())
        filtered = [
            t for t in tokens
            if t not in GENERIC_STOP_WORDS
            and t not in STANDALONE_FILLER_WORDS
            and t not in LAZY_ADJECTIVES_MAP
            and t not in EXTRA_STOP_WORDS
        ]

        counts = Counter(filtered)

        # Incorporate candidate hook and topic metadata if available
        if candidate:
            if getattr(candidate, "hook_title", None):
                title_tokens = [
                    t for t in re.findall(r"\b[a-zA-Z]{2,}\b", candidate.hook_title.lower())
                    if t not in GENERIC_STOP_WORDS
                    and t not in STANDALONE_FILLER_WORDS
                    and t not in LAZY_ADJECTIVES_MAP
                    and t not in EXTRA_STOP_WORDS
                ]
                for t in title_tokens:
                    counts[t] += 2

            ai_meta = getattr(candidate, "ai_metadata", None)
            if ai_meta and isinstance(ai_meta, dict):
                hashtags = ai_meta.get("hashtags", [])
                for tag in hashtags:
                    clean_tag = re.sub(r"[^\w]", "", tag).lower()
                    if len(clean_tag) >= 2 and clean_tag not in EXTRA_STOP_WORDS:
                        counts[clean_tag] += 2

        # Return top 5 most frequent content keywords
        return [k for k, _ in counts.most_common(5)]

    def find_matching_asset(
        self,
        keywords: List[str],
        assets_dir: Optional[str] = None,
    ) -> Optional[str]:
        """
        Searches directory for video clips matching extracted keywords via token scoring.
        Falls back to default stock video (default.mp4 / stock.mp4) if no keyword matches.
        """
        search_dir = assets_dir or self.config.assets_dir
        if not os.path.exists(search_dir) or not os.path.isdir(search_dir):
            return None

        valid_extensions = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
        media_files: List[str] = []

        for root, _, files in os.walk(search_dir):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in valid_extensions:
                    media_files.append(os.path.join(root, f))

        if not media_files:
            return None

        best_score = 0
        best_asset = None

        for path in media_files:
            rel = os.path.relpath(path, search_dir)
            tokens = set(re.findall(r"[a-zA-Z0-9]{2,}", rel.lower()))

            score = 0
            for kw in keywords:
                kw_lower = kw.lower()
                if kw_lower in tokens:
                    score += 3
                elif any(kw_lower in tok or tok in kw_lower for tok in tokens):
                    score += 1

            if score > best_score:
                best_score = score
                best_asset = path

        if best_score > 0 and best_asset:
            return best_asset

        # Fallback check for generic stock footage
        fallback_names = {"default", "stock", "generic", "background", "fallback"}
        for path in media_files:
            base = os.path.splitext(os.path.basename(path))[0].lower()
            if any(fb in base for fb in fallback_names):
                return path

        return None

    def build_broll_filtergraph(
        self,
        primary_input_idx: int = 0,
        broll_inputs: Optional[List[Tuple[int, MonologueInterval, str]]] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> Tuple[str, List[str]]:
        """
        Constructs multi-input FFmpeg filtergraph:
        - Scales each B-roll asset to vertical 9:16 crop.
        - Adds 0.25s alpha fade-in and fade-out transitions.
        - Overlays on primary video during monologue intervals.
        - Ducks primary audio if B-roll audio is active.
        """
        broll_inputs = broll_inputs or []
        w = width or self.config.width
        h = height or self.config.height

        if not broll_inputs:
            return "", ["-map", f"{primary_input_idx}:v", "-map", f"{primary_input_idx}:a?"]

        filter_chains: List[str] = []

        # 1. Scale, Crop, and Fade Transitions for each B-roll stream
        for idx, interval, _ in broll_inputs:
            crop_label = f"broll_crop_{idx}"
            scale_crop = (
                f"[{idx}:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h}:(iw-ow)/2:(ih-oh)/2[{crop_label}]"
            )
            filter_chains.append(scale_crop)

            fade_d = self.config.fade_duration
            fade_out_start = max(0.0, round(interval.duration_seconds - fade_d, 3))
            faded_label = f"broll_faded_{idx}"
            fade_filter = (
                f"[{crop_label}]format=yuva420p,"
                f"fade=t=in:st=0:d={fade_d}:alpha=1,"
                f"fade=t=out:st={fade_out_start:.3f}:d={fade_d}:alpha=1,"
                f"setpts=PTS-STARTPTS+{interval.start_seconds:.3f}/TB[{faded_label}]"
            )
            filter_chains.append(fade_filter)

        # 2. Sequential Video Overlay
        curr_v = f"{primary_input_idx}:v"
        for i, (idx, interval, _) in enumerate(broll_inputs):
            out_v = f"v_overlay_{idx}" if i < len(broll_inputs) - 1 else "v_broll_out"
            faded_label = f"broll_faded_{idx}"
            overlay_filter = (
                f"[{curr_v}][{faded_label}]overlay=0:0:"
                f"enable='between(t,{interval.start_seconds:.3f},{interval.end_seconds:.3f})'[{out_v}]"
            )
            filter_chains.append(overlay_filter)
            curr_v = out_v

        # 3. Audio Handling
        if self.config.mute_broll:
            output_maps = ["-map", f"[{curr_v}]", "-map", f"{primary_input_idx}:a?"]
        else:
            curr_a = f"{primary_input_idx}:a"
            for i, (idx, interval, _) in enumerate(broll_inputs):
                duck_label = f"a_ducked_{idx}"
                broll_a_label = f"broll_a_{idx}"
                out_a = f"a_comp_{idx}" if i < len(broll_inputs) - 1 else "a_broll_out"

                duck_filter = (
                    f"[{curr_a}]volume=enable='between(t,{interval.start_seconds:.3f},{interval.end_seconds:.3f})':"
                    f"volume={self.config.audio_ducking_volume}[{duck_label}]"
                )
                filter_chains.append(duck_filter)

                broll_audio = (
                    f"[{idx}:a]atrim=0:{interval.duration_seconds:.3f},"
                    f"asetpts=PTS-STARTPTS+{interval.start_seconds:.3f}/TB,"
                    f"volume={self.config.broll_audio_volume}[{broll_a_label}]"
                )
                filter_chains.append(broll_audio)

                amix = f"[{duck_label}][{broll_a_label}]amix=inputs=2:duration=first[{out_a}]"
                filter_chains.append(amix)
                curr_a = out_a

            output_maps = ["-map", f"[{curr_v}]", "-map", f"[{curr_a}]"]

        return ";".join(filter_chains), output_maps

    def apply_broll_overlay(
        self,
        video_path: str,
        output_path: str,
        words: List[WordTimestamp],
        candidate: Optional[HighlightCandidate] = None,
        clip_start: float = 0.0,
        clip_end: Optional[float] = None,
        assets_dir: Optional[str] = None,
    ) -> BRollOverlayResult:
        """
        Executes end-to-end B-roll overlay on a rendered vertical video.
        Gracefully preserves video untouched if no intervals or matching assets are found.
        """
        if not os.path.exists(video_path):
            return BRollOverlayResult(
                applied=False,
                input_video_path=video_path,
                output_video_path=video_path,
                telemetry={"error": f"Input video not found: {video_path}"},
            )

        intervals = self.detect_monologue_intervals(words, clip_start, clip_end, candidate=candidate)
        if not intervals:
            return BRollOverlayResult(
                applied=False,
                input_video_path=video_path,
                output_video_path=video_path,
                telemetry={"reason": "No monologue intervals detected exceeding duration threshold"},
            )

        # Match assets for each interval
        matched_intervals: List[MonologueInterval] = []
        broll_inputs: List[Tuple[int, MonologueInterval, str]] = []
        matched_paths: List[str] = []

        for interval in intervals:
            asset = self.find_matching_asset(interval.keywords, assets_dir)
            if asset:
                interval_with_asset = MonologueInterval(
                    start_seconds=interval.start_seconds,
                    end_seconds=interval.end_seconds,
                    duration_seconds=interval.duration_seconds,
                    text=interval.text,
                    keywords=interval.keywords,
                    matched_asset_path=asset,
                )
                matched_intervals.append(interval_with_asset)
                input_idx = len(broll_inputs) + 1  # 0 is primary video
                broll_inputs.append((input_idx, interval_with_asset, asset))
                matched_paths.append(asset)

        if not broll_inputs:
            return BRollOverlayResult(
                applied=False,
                input_video_path=video_path,
                output_video_path=video_path,
                monologue_intervals=intervals,
                matched_assets=[],
                telemetry={"reason": "Monologues detected but no matching B-roll assets found"},
            )

        filtergraph, output_maps = self.build_broll_filtergraph(
            primary_input_idx=0,
            broll_inputs=broll_inputs,
            width=self.config.width,
            height=self.config.height,
        )

        tmp_out = f"{output_path}.tmp.mp4"
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        cmd = ["ffmpeg", "-y", "-i", video_path]
        for _, _, asset_path in broll_inputs:
            cmd.extend(["-i", asset_path])

        cmd.extend(["-filter_complex", filtergraph])
        cmd.extend(output_maps)
        cmd.extend([
            "-c:v", self.config.vcodec,
            "-crf", str(self.config.crf),
            "-preset", "fast",
        ])

        if self.config.mute_broll:
            cmd.extend(["-c:a", "copy"])
        else:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])

        cmd.append(tmp_out)

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0 and os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 0:
                os.replace(tmp_out, output_path)
                sha256 = _compute_sha256(output_path)
                return BRollOverlayResult(
                    applied=True,
                    input_video_path=video_path,
                    output_video_path=output_path,
                    monologue_intervals=matched_intervals,
                    matched_assets=matched_paths,
                    filtergraph=filtergraph,
                    file_hash=sha256,
                    telemetry={"num_overlays": len(broll_inputs), "status": "COMPLETED"},
                )
            else:
                if os.path.exists(tmp_out):
                    try:
                        os.remove(tmp_out)
                    except OSError:
                        pass
                return BRollOverlayResult(
                    applied=False,
                    input_video_path=video_path,
                    output_video_path=video_path,
                    monologue_intervals=matched_intervals,
                    matched_assets=matched_paths,
                    filtergraph=filtergraph,
                    telemetry={"error": f"FFmpeg failed with code {res.returncode}", "stderr": res.stderr[-500:] if res.stderr else ""},
                )
        except Exception as e:
            if os.path.exists(tmp_out):
                try:
                    os.remove(tmp_out)
                except OSError:
                    pass
            return BRollOverlayResult(
                applied=False,
                input_video_path=video_path,
                output_video_path=video_path,
                monologue_intervals=matched_intervals,
                matched_assets=matched_paths,
                filtergraph=filtergraph,
                telemetry={"exception": str(e)},
            )
