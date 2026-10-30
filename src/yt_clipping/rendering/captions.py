"""
Word-Synced Subtitle and Caption Generation.
Supports ASS (Advanced SubStation Alpha) and SRT formats with
subtitle-safe vertical margins tailored for vertical platforms (Shorts, TikTok, Reels).
"""

from typing import List, Optional
import os
from ..contracts.models import Transcript, HighlightCandidate, WordTimestamp


class SubtitleGenerator:
    """
    Generates ASS and SRT subtitle files aligned to candidate intervals.
    Enforces safe margins (leaving bottom 220px clear of UI overlays).
    """

    def __init__(self, font_name: str = "Arial", font_size: int = 56, primary_color: str = "&H00FFFFFF", highlight_color: str = "&H0000FFFF"):
        self.font_name = font_name
        self.font_size = font_size
        self.primary_color = primary_color  # White
        self.highlight_color = highlight_color  # Yellow

    @staticmethod
    def _format_timestamp_ass(seconds: float) -> str:
        """Formats seconds into ASS timestamp H:MM:SS.cs with safe rollover carry."""
        total_cs = max(int(round(seconds * 100)), 0)
        cs = total_cs % 100
        total_s = total_cs // 100
        s = total_s % 60
        total_m = total_s // 60
        m = total_m % 60
        h = total_m // 60
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    @staticmethod
    def _format_timestamp_srt(seconds: float) -> str:
        """Formats seconds into SRT timestamp HH:MM:SS,mmm with safe rollover carry."""
        total_ms = max(int(round(seconds * 1000)), 0)
        ms = total_ms % 1000
        total_s = total_ms // 1000
        s = total_s % 60
        total_m = total_s // 60
        m = total_m % 60
        h = total_m // 60
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def generate_ass(
        self, candidate: HighlightCandidate, transcript: Transcript, output_path: str
    ) -> str:
        """
        Builds an ASS subtitle file with platform safe-zone margins and centered alignment.
        """
        # Collect relevant words within candidate window [cand.start_seconds, cand.end_seconds]
        c_start = candidate.start_seconds
        c_end = candidate.end_seconds

        events = []
        for seg in transcript.segments:
            if seg.end < c_start or seg.start > c_end:
                continue

            # Group words in chunks of 3-5 words for clean mobile readability
            words_in_seg = [w for w in seg.words if w.end >= c_start and w.start <= c_end]
            if not words_in_seg:
                # Use segment text directly if word timestamps not present
                rel_start = max(seg.start - c_start, 0.0)
                rel_end = max(min(seg.end - c_start, candidate.duration_seconds), rel_start + 0.1)
                t_start = self._format_timestamp_ass(rel_start)
                t_end = self._format_timestamp_ass(rel_end)
                events.append(f"Dialogue: 0,{t_start},{t_end},Default,,0,0,0,,{seg.text.strip()}")
            else:
                chunk_size = 4
                for i in range(0, len(words_in_seg), chunk_size):
                    chunk = words_in_seg[i : i + chunk_size]
                    rel_start = max(chunk[0].start - c_start, 0.0)
                    rel_end = max(min(chunk[-1].end - c_start, candidate.duration_seconds), rel_start + 0.1)
                    t_start = self._format_timestamp_ass(rel_start)
                    t_end = self._format_timestamp_ass(rel_end)
                    text = " ".join(w.word for w in chunk)
                    events.append(f"Dialogue: 0,{t_start},{t_end},Default,,0,0,0,,{text}")

        # Construct ASS script
        ass_content = f"""[Script Info]
Title: Antigravity Vertical Shorts Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{self.font_name},{self.font_size},{self.primary_color},&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,60,60,280,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(events) + "\n"

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        return output_path

    def generate_srt(
        self, candidate: HighlightCandidate, transcript: Transcript, output_path: str
    ) -> str:
        """Generates standard SRT subtitles."""
        c_start = candidate.start_seconds
        c_end = candidate.end_seconds

        srt_blocks = []
        idx = 1
        for seg in transcript.segments:
            if seg.end < c_start or seg.start > c_end:
                continue
            rel_start = max(seg.start - c_start, 0.0)
            rel_end = max(min(seg.end - c_start, candidate.duration_seconds), rel_start + 0.1)
            t_start = self._format_timestamp_srt(rel_start)
            t_end = self._format_timestamp_srt(rel_end)
            srt_blocks.append(f"{idx}\n{t_start} --> {t_end}\n{seg.text.strip()}\n")
            idx += 1

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_blocks))

        return output_path
