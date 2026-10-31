"""
Word-Synced Subtitle and Kinetic Caption Generation.
Supports ASS (Advanced SubStation Alpha) and SRT formats with
customizable presets (bold_social, karaoke, clean_editorial, classic),
active-word highlighting, and platform safe-zone margins (Shorts, TikTok, Reels).
Includes rigorous escaping to prevent ASS syntax injection or parsing errors.
"""

from typing import List, Optional, Dict, Any
import os
import re
from ..contracts.models import Transcript, HighlightCandidate, WordTimestamp


def escape_ass_text(text: str) -> str:
    """
    Escapes special characters in transcript text to prevent ASS syntax corruption.
    - Replaces braces { and } with ( and ) so they cannot be confused with override blocks
    - Replaces backslashes with double backslashes
    - Converts newlines to ASS line break tag \\N
    """
    if not text:
        return ""
    # Strip dangerous control characters
    cleaned = "".join(ch for ch in text if ch >= " " or ch in "\n\r\t")
    # Escape backslashes first
    cleaned = cleaned.replace("\\", "\\\\")
    # Replace newlines with ASS newline tag
    cleaned = re.sub(r"\r?\n", "\\\\N", cleaned)
    # Neutralize curly braces to prevent override block injection
    cleaned = cleaned.replace("{", "(").replace("}", ")")
    return cleaned.strip()


class SubtitleGenerator:
    """
    Generates ASS and SRT subtitle files aligned to candidate intervals.
    Enforces safe margins (leaving bottom 280px clear of UI overlays).
    """

    STYLE_PRESETS: Dict[str, Dict[str, Any]] = {
        "bold_social": {
            "font_name": "Arial",
            "font_size": 56,
            "primary_color": "&H00FFFFFF",     # White text
            "secondary_color": "&H0000FFFF",   # Bright Yellow active highlight
            "outline_color": "&H00000000",     # Black outline
            "back_color": "&H80000000",        # Translucent shadow
            "bold": -1,
            "outline": 4,
            "shadow": 2,
            "margin_v": 280,
            "chunk_size": 4,
            "word_highlight": True,
        },
        "karaoke": {
            "font_name": "Impact",
            "font_size": 58,
            "primary_color": "&H00FFFFFF",
            "secondary_color": "&H0000FFFF",   # Yellow karaoke fill
            "outline_color": "&H00000000",
            "back_color": "&HA0000000",
            "bold": -1,
            "outline": 5,
            "shadow": 1,
            "margin_v": 290,
            "chunk_size": 3,
            "word_highlight": True,
        },
        "clean_editorial": {
            "font_name": "Arial",
            "font_size": 48,
            "primary_color": "&H00FFFFFF",
            "secondary_color": "&H00CCCCCC",
            "outline_color": "&H00111111",
            "back_color": "&H60000000",
            "bold": 0,
            "outline": 2,
            "shadow": 1,
            "margin_v": 260,
            "chunk_size": 5,
            "word_highlight": False,
        },
        "classic": {
            "font_name": "Arial",
            "font_size": 52,
            "primary_color": "&H00FFFFFF",
            "secondary_color": "&H0000FFFF",
            "outline_color": "&H00000000",
            "back_color": "&H80000000",
            "bold": -1,
            "outline": 3,
            "shadow": 2,
            "margin_v": 260,
            "chunk_size": 4,
            "word_highlight": False,
        },
    }

    def __init__(
        self,
        style_preset: str = "classic",
        font_name: Optional[str] = None,
        font_size: Optional[int] = None,
        primary_color: Optional[str] = None,
        highlight_color: Optional[str] = None,
        word_highlight: Optional[bool] = None,
        use_karaoke_tags: Optional[bool] = None,
    ):
        self.style_preset = style_preset
        preset = self.STYLE_PRESETS.get(style_preset, self.STYLE_PRESETS["classic"])
        self.font_name = font_name or preset["font_name"]
        self.font_size = font_size or preset["font_size"]
        self.primary_color = primary_color or preset["primary_color"]
        self.highlight_color = highlight_color or preset["secondary_color"]
        self.outline_color = preset["outline_color"]
        self.back_color = preset["back_color"]
        self.bold = preset["bold"]
        self.outline = preset["outline"]
        self.shadow = preset["shadow"]
        self.margin_v = preset["margin_v"]
        self.chunk_size = preset["chunk_size"]
        self.word_highlight = word_highlight if word_highlight is not None else preset["word_highlight"]
        self.use_karaoke_tags = use_karaoke_tags if use_karaoke_tags is not None else (style_preset == "karaoke")

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
        Supports word-level kinetic highlighting when word timestamps are present.
        """
        c_start = candidate.start_seconds
        c_end = candidate.end_seconds

        events = []
        for seg in transcript.segments:
            if seg.end < c_start or seg.start > c_end:
                continue

            words_in_seg = [w for w in seg.words if w.end >= c_start and w.start <= c_end]
            if not words_in_seg:
                # Segment fallback: phrase-level line
                rel_start = max(seg.start - c_start, 0.0)
                rel_end = max(min(seg.end - c_start, candidate.duration_seconds), rel_start + 0.1)
                t_start = self._format_timestamp_ass(rel_start)
                t_end = self._format_timestamp_ass(rel_end)
                safe_text = escape_ass_text(seg.text)
                events.append(f"Dialogue: 0,{t_start},{t_end},Default,,0,0,0,,{safe_text}")
            else:
                # Chunk words for short-form mobile readability
                chunk_sz = self.chunk_size
                for i in range(0, len(words_in_seg), chunk_sz):
                    chunk = words_in_seg[i : i + chunk_sz]
                    chunk_start = max(chunk[0].start - c_start, 0.0)
                    chunk_end = max(min(chunk[-1].end - c_start, candidate.duration_seconds), chunk_start + 0.1)

                    if self.use_karaoke_tags:
                        # FEATURE-03: Word-level {\k...} karaoke timing tags
                        t_start = self._format_timestamp_ass(chunk_start)
                        t_end = self._format_timestamp_ass(chunk_end)
                        styled_words = []
                        for w in chunk:
                            dur_cs = max(int(round((w.end - w.start) * 100)), 1)
                            clean_word = escape_ass_text(w.word)
                            styled_words.append(f"{{\\k{dur_cs}}}{clean_word}")
                        line_text = " ".join(styled_words)
                        events.append(f"Dialogue: 0,{t_start},{t_end},Default,,0,0,0,,{line_text}")
                    elif self.word_highlight:
                        # Produce individual word events with active highlight color
                        for w_idx, active_word in enumerate(chunk):
                            w_rel_start = max(active_word.start - c_start, chunk_start)
                            w_rel_end = max(min(active_word.end - c_start, chunk_end), w_rel_start + 0.08)
                            t_start = self._format_timestamp_ass(w_rel_start)
                            t_end = self._format_timestamp_ass(w_rel_end)

                            # Format chunk where active word is highlighted with secondary color
                            styled_words = []
                            for j, w in enumerate(chunk):
                                clean_word = escape_ass_text(w.word)
                                if j == w_idx:
                                    styled_words.append(f"{{\\c{self.highlight_color}&}}{clean_word}{{\\c{self.primary_color}&}}")
                                else:
                                    styled_words.append(clean_word)

                            line_text = " ".join(styled_words)
                            events.append(f"Dialogue: 0,{t_start},{t_end},Default,,0,0,0,,{line_text}")
                    else:
                        t_start = self._format_timestamp_ass(chunk_start)
                        t_end = self._format_timestamp_ass(chunk_end)
                        clean_text = " ".join(escape_ass_text(w.word) for w in chunk)
                        events.append(f"Dialogue: 0,{t_start},{t_end},Default,,0,0,0,,{clean_text}")

        # Construct ASS script
        ass_content = f"""[Script Info]
Title: Antigravity Vertical Shorts Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{self.font_name},{self.font_size},{self.primary_color},{self.highlight_color},{self.outline_color},{self.back_color},{self.bold},0,0,0,100,100,0,0,1,{self.outline},{self.shadow},2,60,60,{self.margin_v},1

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
        """Generates standard SRT subtitles with escaped content."""
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
            clean_text = seg.text.strip().replace("\r\n", "\n")
            srt_blocks.append(f"{idx}\n{t_start} --> {t_end}\n{clean_text}\n")
            idx += 1

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_blocks))

        return output_path
