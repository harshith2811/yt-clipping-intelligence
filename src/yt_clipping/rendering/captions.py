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


# Keyword sentiment categories for dynamic color accents
DANGER_KEYWORDS = {
    "KILLER", "KILLING", "MURDER", "MURDERER", "MURDERING", "DEAD", "DEATH",
    "DIED", "BOMB", "THREAT", "BLOOD", "VICTIM", "VICTIMS", "ATTACK", "ATTACKED",
    "GUN", "SHOOT", "SHOT", "STRIKES", "EXECUTIONER", "CRIME", "TERROR", "WARNING", "POLICE"
}

MYSTERY_KEYWORDS = {
    "SECRET", "SECRETS", "CODE", "CODES", "PUZZLE",
    "DECODE", "DECODED", "DECODING", "HIDDEN", "UNKNOWN", "INFAMOUS",
    "MYSTERIOUS", "MYSTERY", "CLUE", "CLUES", "EVIDENCE", "LETTERS", "INTERRUPTED"
}

METRIC_KEYWORDS = {
    "FIRST", "MILLION", "THOUSAND", "THOUSANDS", "HUNDRED", "HUNDREDS",
    "ALONE", "NEVER", "ALWAYS", "FOREVER", "CRITICAL", "MASSIVE", "URGENT", "RUSH", "SUDDENLY"
}

EMOJI_KEYWORDS = {
    "KILLER": " 🔪",
    "KILLING": " 🔪",
    "MURDER": " 🔪",
    "BOMB": " 💣",
    "POLICE": " 🚨",
    "OFFICERS": " 🚨",
    "LETTER": " ✉️",
    "LETTERS": " ✉️",
    "CAR": " 🚗",
    "VEHICLE": " 🚗",
    "FIRE": " 🔥",
    "MONEY": " 💰",
    "DEAD": " 💀",
    "DEATH": " 💀",
    "TV": " 📺",
    "LAKE": " 🌊",
}


class SubtitleGenerator:
    """
    Generates high-retention ASS and SRT subtitle files aligned to candidate intervals.
    Supports viral presets (hormozi, beast_bounce, neon_cyber, karaoke_gold, bold_social),
    kinetic micro-scale bounce animations, dynamic keyword sentiment coloring,
    uppercase punch styling, and platform safe-zone margins.
    """

    STYLE_PRESETS: Dict[str, Dict[str, Any]] = {
        "hormozi": {
            "font_name": "Impact",
            "font_size": 72,
            "primary_color": "&H00FFFFFF",     # Crisp White text
            "secondary_color": "&H0000FFFF",   # Neon Yellow active highlight
            "outline_color": "&H00000000",     # Deep Black outline
            "back_color": "&HA0000000",        # Deep drop shadow
            "bold": -1,
            "outline": 7,
            "shadow": 3,
            "margin_v": 650,                   # Center-lower mobile safe zone
            "chunk_size": 2,                   # Rapid 2-word mobile retention pacing
            "word_highlight": True,
            "bounce_animation": True,
            "uppercase": True,
            "keyword_emphasis": True,
            "emoji_badges": False,
        },
        "beast_bounce": {
            "font_name": "Impact",
            "font_size": 74,
            "primary_color": "&H00FFFFFF",     # Crisp White text
            "secondary_color": "&H0033FF00",   # Electric Lime Green active
            "outline_color": "&H00000000",     # Deep Black outline
            "back_color": "&HA0000000",
            "bold": -1,
            "outline": 8,
            "shadow": 4,
            "margin_v": 650,
            "chunk_size": 2,                   # Rapid 2-word chunks
            "word_highlight": True,
            "bounce_animation": True,
            "uppercase": True,
            "keyword_emphasis": True,
            "emoji_badges": False,
        },
        "neon_cyber": {
            "font_name": "Arial Black",
            "font_size": 66,
            "primary_color": "&H00FFFFFF",
            "secondary_color": "&H00FFFF00",   # Electric Cyan active
            "outline_color": "&H001A0B2E",     # Midnight Purple outline
            "back_color": "&H90FF00AA",        # Neon Magenta shadow
            "bold": -1,
            "outline": 6,
            "shadow": 3,
            "margin_v": 650,
            "chunk_size": 2,
            "word_highlight": True,
            "bounce_animation": True,
            "uppercase": False,
            "keyword_emphasis": True,
            "emoji_badges": False,
        },
        "karaoke_gold": {
            "font_name": "Impact",
            "font_size": 68,
            "primary_color": "&H00FFFFFF",
            "secondary_color": "&H0000D7FF",   # Rich Gold progressive fill
            "outline_color": "&H00000000",
            "back_color": "&HA0000000",
            "bold": -1,
            "outline": 6,
            "shadow": 3,
            "margin_v": 650,
            "chunk_size": 2,
            "word_highlight": True,
            "bounce_animation": False,
            "uppercase": True,
            "keyword_emphasis": False,
            "emoji_badges": False,
            "use_karaoke_tags": True,
        },
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
            "bounce_animation": False,
            "uppercase": False,
            "keyword_emphasis": False,
            "emoji_badges": False,
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
            "bounce_animation": False,
            "uppercase": False,
            "keyword_emphasis": False,
            "emoji_badges": False,
            "use_karaoke_tags": True,
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
            "bounce_animation": False,
            "uppercase": False,
            "keyword_emphasis": False,
            "emoji_badges": False,
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
            "bounce_animation": False,
            "uppercase": False,
            "keyword_emphasis": False,
            "emoji_badges": False,
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
        bounce_animation: Optional[bool] = None,
        uppercase: Optional[bool] = None,
        keyword_emphasis: Optional[bool] = None,
        emoji_badges: Optional[bool] = None,
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
        self.use_karaoke_tags = use_karaoke_tags if use_karaoke_tags is not None else preset.get("use_karaoke_tags", False)
        self.bounce_animation = bounce_animation if bounce_animation is not None else preset.get("bounce_animation", False)
        self.uppercase = uppercase if uppercase is not None else preset.get("uppercase", False)
        self.keyword_emphasis = keyword_emphasis if keyword_emphasis is not None else preset.get("keyword_emphasis", False)
        self.emoji_badges = emoji_badges if emoji_badges is not None else preset.get("emoji_badges", False)

    def get_active_word_color(self, clean_word: str) -> str:
        """Determines active word highlight color based on keyword sentiment or preset."""
        if not self.keyword_emphasis:
            return self.highlight_color

        normalized = re.sub(r"[^\w]", "", clean_word).upper()
        if not normalized:
            return self.highlight_color

        if normalized in DANGER_KEYWORDS:
            return "&H002020FF"  # Vivid Crimson Red
        if normalized in MYSTERY_KEYWORDS:
            return "&H0000D7FF"  # Rich Amber Gold
        if normalized in METRIC_KEYWORDS or any(char.isdigit() for char in normalized):
            return "&H00FFFF00"  # Electric Cyan

        return self.highlight_color

    def get_emoji_badge(self, clean_word: str) -> str:
        """Returns contextual emoji suffix for key emotional terms if enabled."""
        if not self.emoji_badges:
            return ""
        normalized = re.sub(r"[^\w]", "", clean_word).upper()
        return EMOJI_KEYWORDS.get(normalized, "")

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
        Supports word-level kinetic highlighting, micro-bounce animations, and sentiment styling.
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
                if self.uppercase:
                    safe_text = safe_text.upper()
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
                            if self.uppercase:
                                clean_word = clean_word.upper()
                            styled_words.append(f"{{\\k{dur_cs}}}{clean_word}")
                        line_text = " ".join(styled_words)
                        events.append(f"Dialogue: 0,{t_start},{t_end},Default,,0,0,0,,{line_text}")
                    elif self.word_highlight:
                        # Produce seamless word events with active highlight color & micro-bounce
                        # Avoid gaps/flicker by holding the chunk continuously on-screen
                        natural_chunk_end = max(min(chunk[-1].end - c_start, candidate.duration_seconds), chunk_start + 0.1)
                        if i + chunk_sz < len(words_in_seg):
                            next_start = max(words_in_seg[i + chunk_sz].start - c_start, chunk_start)
                            # Bridge micro-pauses (< 0.45s) between chunks to avoid flickering
                            if (next_start - natural_chunk_end) < 0.45:
                                seamless_chunk_end = next_start
                            else:
                                seamless_chunk_end = natural_chunk_end + 0.15
                        else:
                            seamless_chunk_end = min(natural_chunk_end + 0.20, candidate.duration_seconds)

                        for w_idx, active_word in enumerate(chunk):
                            if w_idx == 0:
                                w_rel_start = chunk_start
                            else:
                                w_rel_start = max(active_word.start - c_start, chunk_start)

                            if w_idx < len(chunk) - 1:
                                next_w_start = max(chunk[w_idx + 1].start - c_start, w_rel_start + 0.08)
                                natural_w_end = max(active_word.end - c_start, w_rel_start + 0.08)
                                # Cap active word duration so highlight does not linger across silence
                                w_rel_end = min(next_w_start, max(natural_w_end + 0.06, w_rel_start + 0.12))
                            else:
                                natural_w_end = max(active_word.end - c_start, w_rel_start + 0.08)
                                w_rel_end = min(seamless_chunk_end, max(natural_w_end + 0.10, w_rel_start + 0.15))

                            if w_rel_end <= w_rel_start:
                                w_rel_end = w_rel_start + 0.10

                            t_start = self._format_timestamp_ass(w_rel_start)
                            t_end = self._format_timestamp_ass(w_rel_end)

                            styled_words = []
                            for j, w in enumerate(chunk):
                                clean_word = escape_ass_text(w.word)
                                if self.uppercase:
                                    clean_word = clean_word.upper()

                                if j == w_idx:
                                    active_color = self.get_active_word_color(clean_word)
                                    badge = self.get_emoji_badge(clean_word)
                                    word_display = f"{clean_word}{badge}"
                                    is_hook_opening = (w_rel_start <= 3.5 and getattr(getattr(candidate, "breakdown", None), "hook_score", 0.0) >= 7.5)
                                    if self.bounce_animation:
                                        bounce_tag = (
                                            r"{\t(0,60,\fscx124\fscy124)\t(60,130,\fscx100\fscy100)}"
                                            if is_hook_opening
                                            else r"{\t(0,60,\fscx118\fscy118)\t(60,130,\fscx100\fscy100)}"
                                        )
                                        styled_words.append(f"{bounce_tag}{{\\c{active_color}&}}{word_display}{{\\fscx100\\fscy100\\c{self.primary_color}&}}")
                                    else:
                                        styled_words.append(f"{{\\c{active_color}&}}{word_display}{{\\c{self.primary_color}&}}")
                                else:
                                    styled_words.append(clean_word)

                            line_text = " ".join(styled_words)
                            events.append(f"Dialogue: 0,{t_start},{t_end},Default,,0,0,0,,{line_text}")
                    else:
                        t_start = self._format_timestamp_ass(chunk_start)
                        t_end = self._format_timestamp_ass(chunk_end)
                        words_formatted = [escape_ass_text(w.word).upper() if self.uppercase else escape_ass_text(w.word) for w in chunk]
                        clean_text = " ".join(words_formatted)
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
