"""
Best-in-Class YouTube Replay Heatmap & Retention Intelligence Engine.
Extracts YouTube's 100-segment 'Most Replayed' heatmap telemetry,
applies topological peak prominence signal processing, provides
graceful fallbacks via comment timestamp clustering and acoustic density,
and snaps retention hotspots to transcript sentence boundaries.
"""

from typing import List, Dict, Optional, Tuple, Any
import os
import sys
import json
import re
import math
import subprocess
import urllib.request
from datetime import datetime, timezone
import numpy as np
from dotenv import load_dotenv

load_dotenv()

from ..contracts.models import (
    HeatmapPoint,
    HeatmapPeak,
    HeatmapData,
    Transcript,
    TranscriptSegment,
)


class HeatmapAnalyzer:
    """
    Analyzes online audience retention curves to identify viral moments and replay hotspots.
    """

    def __init__(self, cache_dir: str = "data/heatmaps", api_key: Optional[str] = None):
        self.cache_dir = cache_dir
        self.api_key = api_key or os.getenv("YOUTUBE_API_KEY")
        os.makedirs(self.cache_dir, exist_ok=True)

    def extract_heatmap(
        self,
        video_id: str,
        source_url: Optional[str] = None,
        duration_seconds: float = 0.0,
        transcript: Optional[Transcript] = None,
    ) -> HeatmapData:
        """
        Extracts heatmap retention curve using tiered fallback strategy:
        1. Local cache inspection
        2. Direct YouTube player response parsing (yt-dlp heatmap array)
        3. Crowdsourced comment timestamp density clustering (via YouTube Data API v3)
        4. Speech & punctuation density curve synthesis
        """
        cache_path = os.path.join(self.cache_dir, f"{video_id}.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cached_dict = json.load(f)
                    return HeatmapData.from_dict(cached_dict)
            except Exception:
                pass

        url = source_url or f"https://www.youtube.com/watch?v={video_id}"
        points: List[HeatmapPoint] = []
        source_tag = "YOUTUBE_HEATMAP"

        # Tier 1: YouTube online player response heatmap
        raw_hm = self._fetch_ytdlp_heatmap(url)
        if raw_hm:
            points = [
                HeatmapPoint(
                    start_time=float(p.get("start_time", 0.0)),
                    end_time=float(p.get("end_time", 0.0)),
                    value=float(p.get("value", 0.0)),
                )
                for p in raw_hm
            ]

        # Tier 2: Crowdsourced comment timestamp density (if heatmap unavailable or blocked)
        if not points and self.api_key:
            comment_points = self._synthesize_from_comments(video_id, duration_seconds)
            if comment_points:
                points = comment_points
                source_tag = "COMMENT_DENSITY"

        # Tier 3: Speech & narrative density synthesis from transcript
        if not points:
            points = self._synthesize_from_transcript(duration_seconds, transcript)
            source_tag = "SYNTHETIC_SPEECH_DENSITY"

        # Calculate video duration from points if not provided
        total_duration = duration_seconds or (points[-1].end_time if points else 60.0)

        # Detect prominent peaks
        peaks = self.detect_peaks(points, total_duration, transcript=transcript)
        global_peak = max(peaks, key=lambda pk: pk.intensity) if peaks else None

        heatmap_data = HeatmapData(
            video_id=video_id,
            source=source_tag,
            points=points,
            peaks=peaks,
            global_peak=global_peak,
        )

        # Cache result to disk
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(heatmap_data.to_dict(), f, indent=2)
        except Exception:
            pass

        return heatmap_data

    def _fetch_ytdlp_heatmap(self, url: str) -> Optional[List[Dict[str, Any]]]:
        """Runs yt-dlp to dump YouTube player JSON and extract 'heatmap' array."""
        try:
            cmd = [
                sys.executable,
                "-m",
                "yt_dlp",
                "--dump-json",
                "--skip-download",
                "--no-playlist",
                url,
            ]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=25,
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                hm = data.get("heatmap")
                if isinstance(hm, list) and len(hm) > 0:
                    return hm
        except Exception:
            pass
        return None

    def _synthesize_from_comments(self, video_id: str, duration_seconds: float) -> List[HeatmapPoint]:
        """
        Builds a crowdsourced retention density curve by extracting timestamps
        from top YouTube comments using YouTube Data API v3.
        """
        if not self.api_key:
            return []

        try:
            url = (
                f"https://www.googleapis.com/youtube/v3/commentThreads"
                f"?part=snippet&videoId={video_id}&order=relevance&maxResults=50&key={self.api_key}"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            items = data.get("items", [])
            ts_pattern = re.compile(r"\b(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\b")
            timestamps: List[Tuple[float, int]] = []  # (second, like_weight)

            dur = duration_seconds or 300.0

            for item in items:
                snippet = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
                text = snippet.get("textDisplay", "")
                likes = max(int(snippet.get("likeCount", 0)), 1)
                matches = ts_pattern.findall(text)
                for h, m, s in matches:
                    hours = int(h) if h else 0
                    mins = int(m)
                    secs = int(s)
                    total_sec = float(hours * 3600 + mins * 60 + secs)
                    if total_sec <= dur:
                        timestamps.append((total_sec, likes))

            if not timestamps:
                return []

            # 100-bin histogram with Gaussian kernel density smoothing
            num_bins = 100
            bin_size = max(dur / num_bins, 1.0)
            bins = np.zeros(num_bins, dtype=float)

            for sec, likes in timestamps:
                idx = min(int(sec / bin_size), num_bins - 1)
                weight = 1.0 + math.log10(likes + 1)
                # Spread weight to adjacent bins (Gaussian spread)
                for offset in [-2, -1, 0, 1, 2]:
                    target = idx + offset
                    if 0 <= target < num_bins:
                        factor = math.exp(-0.5 * (offset ** 2))
                        bins[target] += weight * factor

            max_val = np.max(bins)
            if max_val > 0:
                bins = bins / max_val  # Normalize 0.0 to 1.0

            points = []
            for i in range(num_bins):
                st = i * bin_size
                et = (i + 1) * bin_size
                points.append(HeatmapPoint(start_time=round(st, 2), end_time=round(et, 2), value=round(float(bins[i]), 4)))

            return points
        except Exception:
            return []

    def _synthesize_from_transcript(
        self, duration_seconds: float, transcript: Optional[Transcript]
    ) -> List[HeatmapPoint]:
        """
        Synthesizes a 100-bin baseline engagement curve based on speech pacing and exclamation patterns.
        Avoids normalizing flat signals into artificial 100% peaks.
        """
        num_bins = 100
        dur = duration_seconds or (transcript.duration_seconds if transcript else 60.0)
        dur = max(dur, 10.0)
        bin_size = dur / num_bins
        bins = np.ones(num_bins, dtype=float) * 0.2  # Baseline attention level

        has_features = False
        if transcript and transcript.segments:
            for seg in transcript.segments:
                seg_mid = (seg.start + seg.end) / 2.0
                idx = min(int(seg_mid / bin_size), num_bins - 1)
                text = seg.text.strip()
                wpm = len(text.split()) / max((seg.end - seg.start) / 60.0, 0.1)

                boost = 0.0
                if 130 <= wpm <= 180:
                    boost += 0.2
                if any(p in text for p in ["?", "!"]):
                    boost += 0.3
                if any(kw in text.lower() for kw in ["secret", "never", "why", "insane", "truth"]):
                    boost += 0.4

                if boost > 0.0:
                    bins[idx] = min(bins[idx] + boost, 1.0)
                    has_features = True

        # Use edge padding instead of zero padding to prevent edge droop and boundary artifacts
        kernel = np.array([0.25, 0.5, 0.25])
        padded = np.pad(bins, len(kernel) // 2, mode="edge")
        smoothed = np.convolve(padded, kernel, mode="valid")

        # BUG-07 fix: only scale if there is meaningful variation, do not boost flat signals to 1.0
        val_range = float(np.max(smoothed) - np.min(smoothed))
        if val_range > 0.10:
            smoothed = (smoothed - np.min(smoothed)) / val_range * 0.8 + 0.2

        return [
            HeatmapPoint(
                start_time=round(i * bin_size, 2),
                end_time=round((i + 1) * bin_size, 2),
                value=round(float(smoothed[i]), 4),
            )
            for i in range(num_bins)
        ]

    def detect_peaks(
        self,
        points: List[HeatmapPoint],
        total_duration: float,
        min_intensity: float = 0.35,
        min_prominence: float = 0.08,
        transcript: Optional[Transcript] = None,
    ) -> List[HeatmapPeak]:
        """
        Applies signal smoothing and topological prominence analysis to find true retention peaks.
        Rejects flat signals, NaNs, and infinities without manufacturing false peaks.
        """
        if len(points) < 3:
            return []

        raw_values = np.array([float(p.value) for p in points], dtype=float)
        # Sanitize NaNs and infinities
        raw_values = np.nan_to_num(raw_values, nan=0.0, posinf=1.0, neginf=0.0)

        # BUG-07 fix: Detect flat / constant signals and return empty peaks
        val_range = float(np.max(raw_values) - np.min(raw_values))
        val_variance = float(np.var(raw_values))
        if val_range < 0.03 or val_variance < 1e-4:
            return []

        # Smooth using edge padding to eliminate boundary convolution artifacts
        kernel = np.array([0.2, 0.6, 0.2])
        padded = np.pad(raw_values, len(kernel) // 2, mode="edge")
        smoothed = np.convolve(padded, kernel, mode="valid")

        peaks: List[HeatmapPeak] = []
        n = len(smoothed)
        global_max_val = float(np.max(smoothed))

        for i in range(1, n - 1):
            # Check local maximum condition
            if smoothed[i] > smoothed[i - 1] and smoothed[i] >= smoothed[i + 1]:
                val = float(smoothed[i])
                if val < min_intensity:
                    continue

                # Compute topological prominence:
                # Find left baseline valley
                l_min = val
                for j in range(i - 1, -1, -1):
                    if smoothed[j] > val:
                        break
                    if smoothed[j] < l_min:
                        l_min = smoothed[j]

                # Find right baseline valley
                r_min = val
                for j in range(i + 1, n):
                    if smoothed[j] > val:
                        break
                    if smoothed[j] < r_min:
                        r_min = smoothed[j]

                baseline = max(l_min, r_min)
                prominence = val - baseline

                if prominence < min_prominence and val < 0.75:
                    continue

                st = points[i].start_time
                et = points[i].end_time
                center = (st + et) / 2.0

                # Calculate width at half prominence (FWHM)
                half_level = val - (prominence / 2.0)
                l_idx = i
                while l_idx > 0 and smoothed[l_idx] > half_level:
                    l_idx -= 1
                r_idx = i
                while r_idx < n - 1 and smoothed[r_idx] > half_level:
                    r_idx += 1
                width_sec = max(points[r_idx].end_time - points[l_idx].start_time, et - st)

                # Classification
                if abs(val - global_max_val) < 0.01:
                    classification = "GLOBAL_MAXIMA"
                elif width_sec < 45.0 and prominence > 0.15:
                    classification = "SPIKE_PAYOFF"
                else:
                    classification = "SUSTAINED_ENGAGEMENT"

                # Calculate suggested clipping window with sentence boundary snapping
                clip_st, clip_et = self.snap_peak_to_window(
                    center_time=center,
                    transcript=transcript,
                    total_duration=total_duration,
                    target_duration=35.0,
                )

                peak = HeatmapPeak(
                    peak_id=f"peak-{len(peaks)+1:02d}-{int(center)}s",
                    start_time=round(st, 2),
                    end_time=round(et, 2),
                    center_time=round(center, 2),
                    intensity=round(val, 4),
                    prominence=round(float(prominence), 4),
                    width_seconds=round(width_sec, 1),
                    classification=classification,
                    suggested_clip_start=round(clip_st, 2),
                    suggested_clip_end=round(clip_et, 2),
                )
                peaks.append(peak)

        # Sort peaks by composite score (60% intensity + 40% prominence)
        peaks.sort(key=lambda pk: (pk.intensity * 0.6 + pk.prominence * 0.4), reverse=True)
        return peaks

    def snap_peak_to_window(
        self,
        center_time: float,
        transcript: Optional[Transcript],
        total_duration: float,
        target_duration: float = 35.0,
        min_duration: float = 20.0,
        max_duration: float = 60.0,
    ) -> Tuple[float, float]:
        """
        Snaps a peak's timestamp to surrounding sentence boundaries or media bounds.
        BUG-08 fix: Strictly guarantees duration bounds regardless of transcript presence.
        """
        # Adjust effective target if media is shorter than target_duration
        effective_target = min(target_duration, total_duration)
        effective_min = min(min_duration, total_duration)

        ideal_start = max(center_time - (effective_target * 0.55), 0.0)
        ideal_end = min(center_time + (effective_target * 0.45), total_duration)

        if not transcript or not transcript.segments:
            best_start = ideal_start
            best_end = ideal_end
        else:
            # Search for closest sentence start before ideal_start
            best_start = ideal_start
            min_st_diff = float("inf")
            for seg in transcript.segments:
                if abs(seg.start - ideal_start) < min_st_diff and seg.start <= center_time:
                    min_st_diff = abs(seg.start - ideal_start)
                    best_start = seg.start

            # Search for closest sentence end after ideal_end
            best_end = ideal_end
            min_et_diff = float("inf")
            for seg in transcript.segments:
                if abs(seg.end - ideal_end) < min_et_diff and seg.end >= center_time:
                    min_et_diff = abs(seg.end - ideal_end)
                    best_end = seg.end

        # Enforce universal duration constraints
        dur = best_end - best_start
        if dur < effective_min:
            # Expand backwards if near the end of media
            if best_end >= total_duration:
                best_start = max(0.0, total_duration - effective_min)
                best_end = total_duration
            else:
                best_end = min(best_start + effective_min, total_duration)

        dur = best_end - best_start
        if dur > max_duration:
            best_end = min(best_start + max_duration, total_duration)

        best_start = max(0.0, best_start)
        best_end = min(total_duration, max(best_start + 0.1, best_end))

        return round(best_start, 2), round(best_end, 2)

    def render_ascii_curve(self, heatmap: HeatmapData, width: int = 50, height: int = 6) -> str:
        """
        Renders a clean ASCII sparkline/waveform representing viewer retention over time.
        """
        if not heatmap.points:
            return "No retention heatmap data available."

        n_pts = len(heatmap.points)
        sampled = []
        step = n_pts / float(width)
        for w in range(width):
            idx = min(int(w * step), n_pts - 1)
            sampled.append(heatmap.points[idx].value)

        # Standard universal ASCII characters for 100% terminal compatibility (Windows cp1252 / UTF-8)
        chars = [" ", ".", ":", "-", "=", "+", "*", "#", "@"]
        lines = []
        lines.append(f"Viewer Replay Retention Waveform [{heatmap.source}] (Duration: {heatmap.points[-1].end_time:.0f}s):")
        
        row_str = ""
        for val in sampled:
            char_idx = int(val * (len(chars) - 1))
            row_str += chars[max(0, min(char_idx, len(chars) - 1))]
        lines.append(f"  ^ 100% |{row_str}|")

        # Add time markers
        t_total = heatmap.points[-1].end_time
        t_mid = t_total / 2.0
        lines.append(f"  v   0%  00:00{' ' * max(width // 2 - 8, 2)}{t_mid/60:02.0f}:{t_mid%60:02.0f}{' ' * max(width // 2 - 8, 2)}{t_total/60:02.0f}:{t_total%60:02.0f}")

        if heatmap.peaks:
            lines.append("\nProminent Replay Peaks:")
            for i, pk in enumerate(heatmap.peaks[:4], 1):
                mins = int(pk.center_time // 60)
                secs = int(pk.center_time % 60)
                lines.append(
                    f"  #{i} [{pk.classification}] {mins:02d}:{secs:02d} | "
                    f"Intensity: {pk.intensity*100:.1f}%, Prominence: {pk.prominence*100:.1f}%, "
                    f"Suggested: {pk.suggested_clip_start:.1f}s - {pk.suggested_clip_end:.1f}s ({pk.suggested_clip_end - pk.suggested_clip_start:.1f}s)"
                )

        return "\n".join(lines)
