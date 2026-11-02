"""
Self-Contained Animated Call-to-Action (CTA) Overlay Engine.
Provides native, zero-external-asset dynamic Call-to-Action overlays:
- Libass animated vector & text styling (slide-up entrance, pulse, fade-out).
- Native FFmpeg drawbox and drawtext filtergraph expressions.
- Safe-zone calculation (1080x1920 vertical, split-screen podcast divider clearance, platform UI protection).
- Unicode safety, emoji fallback, and text sanitization.
- Support for modern_pill, neon_banner, and minimal styling presets.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, Dict, Any, Tuple, List
import os
import re
import math


class CTAStyle(str, Enum):
    MODERN_PILL = "modern_pill"
    NEON_BANNER = "neon_banner"
    MINIMAL = "minimal"


class CTATiming(str, Enum):
    END = "end"
    INTRO = "intro"
    PERSISTENT = "persistent"


@dataclass
class CTAConfig:
    """Configuration for animated Call-to-Action overlay."""
    text: str = "Subscribe to this channel for more"
    timing: str = "end"            # "end", "intro", "persistent"
    style: str = "modern_pill"     # "modern_pill", "neon_banner", "minimal"
    duration: float = 3.5          # duration in seconds
    entrance_duration: float = 0.35  # slide-up / fade-in duration
    exit_duration: float = 0.30     # fade-out duration
    safe_zone_margin_bottom: int = 250  # px from bottom in 1080x1920
    safe_zone_margin_top: int = 150     # px from top
    safe_zone_margin_sides: int = 120   # px from sides
    font_name: str = "Impact"
    font_size: int = 42
    bg_color: str = "#0F172A"      # Slate 900
    bg_opacity: float = 0.85       # ~85% opacity
    text_color: str = "#FFFFFF"
    accent_color: str = "#00FFFF"  # Electric cyan / neon highlight
    anchor: str = "lower_third"    # "lower_third", "center", "upper_third"
    custom_y_offset: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CTAConfig:
        return cls(**data)


@dataclass(frozen=True)
class CTATimingWindow:
    """Exact computed timing boundaries for CTA rendering."""
    start_time: float
    end_time: float
    duration: float
    entrance_duration: float
    exit_duration: float
    active_duration: float


def escape_ass_text(text: str) -> str:
    """Escapes special characters in ASS subtitle dialogue."""
    s = text.replace("\\", "\\\\")
    s = s.replace("{", "\\{").replace("}", "\\}")
    return s


def escape_ffmpeg_drawtext(text: str) -> str:
    """Escapes special characters for FFmpeg drawtext filter parameter."""
    s = text.replace("\\", "\\\\")
    s = s.replace("'", "'\\''")
    s = s.replace(":", "\\:")
    s = s.replace("%", "\\%")
    s = s.replace("[", "\\[").replace("]", "\\]")
    return s


def sanitize_unicode_for_render(text: str, preserve_ascii_fallback: bool = True) -> str:
    """
    Sanitizes input text for video rendering:
    - Normalizes excessive whitespace
    - Strips unprintable control characters
    - Translates common emoji symbols to text labels if font lacks glyphs (when preserve_ascii_fallback=True)
    """
    if not text:
        return "Subscribe for more"

    cleaned = text
    if preserve_ascii_fallback:
        # Replace common emoji with readable text equivalents if requested
        emoji_replacements = {
            "🔔": "[Bell]",
            "👉": ">>",
            "👇": "v",
            "🔥": "*",
            "✨": "*",
            "❤️": "<3",
            "👍": "[Like]",
            "🚀": ">>",
            "▶️": ">",
            "⭐": "*",
        }
        for emo, rep in emoji_replacements.items():
            cleaned = cleaned.replace(emo, rep)

    # Strip remaining unprintable control characters (except standard printable unicode)
    cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", cleaned)
    cleaned = cleaned.strip()
    return cleaned or (text if not preserve_ascii_fallback else "Subscribe for more")


class CTAOverlayEngine:
    """
    Self-contained Call-to-Action (CTA) overlay engine.
    Supports animated Libass vector pill/banner events and native FFmpeg filter expressions.
    """

    STYLE_SPECS: Dict[str, Dict[str, Any]] = {
        "modern_pill": {
            "font_name": "Impact",
            "font_size": 52,
            "primary_color": "&H00FFFFFF",     # Crisp White text
            "secondary_color": "&H0000FFFF",   # Neon Cyan highlight
            "outline_color": "&H002A170F",     # Deep Slate 900 background box (BGR format: &H002A170F)
            "back_color": "&H0000E6FF",        # Electric Gold/Cyan glowing border/shadow
            "bold": -1,
            "outline": 22,                     # Generous pill box padding
            "shadow": 4,                       # Glowing accent line
            "border_style": 3,                 # Opaque bounding box
        },
        "neon_banner": {
            "font_name": "Impact",
            "font_size": 52,
            "primary_color": "&H00FFFFFF",     # Crisp White text
            "secondary_color": "&H00FFFF00",   # Electric Neon Cyan/Yellow
            "outline_color": "&H0018120B",     # Dark obsidian box
            "back_color": "&H0000FFFF",        # Glowing cyan border/shadow
            "bold": -1,
            "outline": 24,
            "shadow": 5,
            "border_style": 3,
        },
        "minimal": {
            "font_name": "Arial",
            "font_size": 44,
            "primary_color": "&H00F1F5F9",     # Slate 100
            "secondary_color": "&H00CBD5E1",   # Slate 300
            "outline_color": "&H33000000",     # Semi-transparent dark box (80% opacity)
            "back_color": "&H80000000",
            "bold": 0,
            "outline": 16,
            "shadow": 2,
            "border_style": 3,
        },
    }

    def __init__(self, default_config: Optional[CTAConfig] = None):
        self.default_config = default_config or CTAConfig()

    def compute_timing(
        self,
        clip_duration: float,
        config: Optional[CTAConfig] = None,
    ) -> CTATimingWindow:
        """
        Calculates exact start and end timestamps and choreography intervals for CTA.
        Guarantees overlay remains strictly within [0.0, clip_duration].
        """
        cfg = config or self.default_config
        safe_clip_dur = max(0.1, float(clip_duration))

        timing_mode = str(cfg.timing).lower()
        target_duration = min(max(0.2, float(cfg.duration)), safe_clip_dur)

        if timing_mode == "intro":
            start_t = min(0.5, safe_clip_dur * 0.1)
            end_t = min(safe_clip_dur, start_t + target_duration)
        elif timing_mode == "persistent":
            start_t = 0.0
            end_t = safe_clip_dur
        else:  # "end" default
            start_t = max(0.0, safe_clip_dur - target_duration)
            end_t = safe_clip_dur

        actual_dur = max(0.1, end_t - start_t)

        # Scale entrance and exit animations if clip/window is too short
        ent_d = min(cfg.entrance_duration, round(actual_dur * 0.4, 3))
        ext_d = min(cfg.exit_duration, round(actual_dur * 0.35, 3))
        act_d = max(0.0, round(actual_dur - ent_d - ext_d, 3))

        return CTATimingWindow(
            start_time=round(start_t, 3),
            end_time=round(end_t, 3),
            duration=round(actual_dur, 3),
            entrance_duration=round(ent_d, 3),
            exit_duration=round(ext_d, 3),
            active_duration=round(act_d, 3),
        )

    def calculate_placement(
        self,
        width: int,
        height: int,
        config: Optional[CTAConfig] = None,
        layout_mode: str = "blur_background",
    ) -> Dict[str, Any]:
        """
        Calculates UI safe-zone coordinates avoiding video borders, subtitles,
        and podcast split dividers.
        """
        cfg = config or self.default_config
        w = max(320, width)
        h = max(320, height)

        margin_bottom = int(cfg.safe_zone_margin_bottom * (h / 1920.0))
        margin_top = int(cfg.safe_zone_margin_top * (h / 1920.0))
        margin_sides = int(cfg.safe_zone_margin_sides * (w / 1080.0))

        center_x = w // 2

        if cfg.custom_y_offset is not None:
            target_y = int(cfg.custom_y_offset)
        elif layout_mode == "split_screen":
            # In podcast split screen, divider is at h // 2. Place CTA safely in bottom speaker lower third
            split_divider_y = h // 2
            # Bottom region is [split_divider_y, h]. Safe lower third inside bottom region:
            target_y = int(split_divider_y + (h - split_divider_y) * 0.78)
        elif cfg.anchor == "upper_third":
            target_y = margin_top + 80
        elif cfg.anchor == "center":
            target_y = h // 2
        else:  # "lower_third" default
            target_y = h - margin_bottom - 40

        # Subtitle clearance check:
        # Standard subtitles sit between (h * 0.65) and (h * 0.80).
        # Our lower-third default sits around (h * 0.85), clearing the subtitle band.
        return {
            "center_x": center_x,
            "center_y": target_y,
            "margin_bottom": margin_bottom,
            "margin_top": margin_top,
            "margin_sides": margin_sides,
            "safe_width": max(200, w - (margin_sides * 2)),
        }

    def generate_ass_style(
        self,
        style_name: str = "modern_pill",
        custom_style_name: str = "CTA_Overlay",
    ) -> str:
        """
        Generates ASS style header definition for the CTA banner.
        """
        spec = self.STYLE_SPECS.get(style_name, self.STYLE_SPECS["modern_pill"])
        return (
            f"Style: {custom_style_name},{spec['font_name']},{spec['font_size']},"
            f"{spec['primary_color']},{spec['secondary_color']},{spec['outline_color']},{spec['back_color']},"
            f"{spec['bold']},0,0,0,100,100,0,0,{spec['border_style']},{spec['outline']},{spec['shadow']},"
            f"2,30,30,30,1"
        )

    def generate_ass_events(
        self,
        clip_duration: float,
        config: Optional[CTAConfig] = None,
        width: int = 1080,
        height: int = 1920,
        layout_mode: str = "blur_background",
        style_name: str = "CTA_Overlay",
    ) -> Tuple[str, List[str]]:
        """
        Generates Libass style definition and animated Dialogue event lines.
        Animates entrance slide-up and fade, sustained readability, and smooth fade-out.
        """
        cfg = config or self.default_config
        timing = self.compute_timing(clip_duration, cfg)
        placement = self.calculate_placement(width, height, cfg, layout_mode)

        sanitized_text = sanitize_unicode_for_render(cfg.text, preserve_ascii_fallback=False)
        sanitized_text = sanitized_text.replace("[Bell]", "🔔")
        if (cfg.style == "modern_pill" or getattr(cfg, "include_bell", False)) and not sanitized_text.startswith("🔔"):
            display_text = f"🔔  {sanitized_text}"
        else:
            display_text = sanitized_text

        escaped_text = escape_ass_text(display_text)

        # Style line
        style_def = self.generate_ass_style(cfg.style, custom_style_name=style_name)
        spec = self.STYLE_SPECS.get(cfg.style, self.STYLE_SPECS["modern_pill"])
        base_font = spec.get("font_name", "Impact")
        if "🔔" in escaped_text:
            escaped_text = escaped_text.replace("🔔", f"{{\\fnSegoe UI Emoji}}🔔{{\\fn{base_font}}}")

        # Timings in ASS format (H:MM:SS.cs)
        def to_ass_ts(sec: float) -> str:
            hrs = int(sec // 3600)
            mins = int((sec % 3600) // 60)
            secs = sec % 60
            return f"{hrs}:{mins:02d}:{secs:05.2f}"

        start_str = to_ass_ts(timing.start_time)
        end_str = to_ass_ts(timing.end_time)

        # Millisecond intervals for Libass tags
        ent_ms = int(timing.entrance_duration * 1000)
        ext_ms = int(timing.exit_duration * 1000)

        cx = placement["center_x"]
        cy = placement["center_y"]
        slide_offset = 35  # slide up by 35px during entrance

        # Animated Libass dialogue tag:
        # \an5: centered alignment on coordinates
        # \move(x1, y1, x2, y2, t1, t2): slide-up entrance
        # \fad(in_ms, out_ms): smooth alpha fade entrance and exit
        ass_tag = (
            f"{{\\an5"
            f"\\move({cx},{cy + slide_offset},{cx},{cy},0,{ent_ms})"
            f"\\fad({ent_ms},{ext_ms})"
            f"}}"
        )

        event_line = f"Dialogue: 2,{start_str},{end_str},{style_name},,0,0,0,,{ass_tag}{escaped_text}"
        return style_def, [event_line]

    def inject_into_ass(
        self,
        ass_content: str,
        clip_duration: float,
        config: Optional[CTAConfig] = None,
        width: int = 1080,
        height: int = 1920,
        layout_mode: str = "blur_background",
    ) -> str:
        """
        Injects CTA style and animated event line into an existing ASS subtitle script.
        """
        style_def, event_lines = self.generate_ass_events(
            clip_duration=clip_duration,
            config=config,
            width=width,
            height=height,
            layout_mode=layout_mode,
            style_name="CTA_Overlay",
        )

        lines = ass_content.splitlines()
        new_lines: List[str] = []
        style_injected = False
        event_injected = False

        for line in lines:
            new_lines.append(line)
            # Inject style right after [V4+ Styles] section or last Style: line
            if not style_injected and line.strip().startswith("Style:"):
                new_lines.append(style_def)
                style_injected = True
            elif not style_injected and line.strip() == "[V4+ Styles]":
                # Will wait for Style: or format
                pass

        if not style_injected:
            # Append style section if missing
            new_lines.extend(["", "[V4+ Styles]", "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding", style_def])

        # Append dialogue event under [Events]
        if "[Events]" in ass_content:
            events_idx = -1
            for i, l in enumerate(new_lines):
                if l.strip() == "[Events]":
                    events_idx = i
                    break
            if events_idx != -1:
                # Find the end of events header
                insert_idx = events_idx + 1
                while insert_idx < len(new_lines) and new_lines[insert_idx].startswith("Format:"):
                    insert_idx += 1
                for ev in event_lines:
                    new_lines.insert(insert_idx, ev)
                    insert_idx += 1
                event_injected = True

        if not event_injected:
            new_lines.extend(["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text", *event_lines])

        return "\n".join(new_lines) + "\n"

    def inject_into_ass_file(
        self,
        ass_file_path: str,
        clip_duration: float,
        config: Optional[CTAConfig] = None,
        width: int = 1080,
        height: int = 1920,
        layout_mode: str = "blur_background",
    ) -> str:
        """
        Injects CTA overlay into an on-disk ASS file.
        """
        if not os.path.exists(ass_file_path):
            return self.generate_standalone_ass_file(
                output_path=ass_file_path,
                clip_duration=clip_duration,
                config=config,
                width=width,
                height=height,
                layout_mode=layout_mode,
            )

        with open(ass_file_path, "r", encoding="utf-8") as f:
            content = f.read()

        updated = self.inject_into_ass(
            ass_content=content,
            clip_duration=clip_duration,
            config=config,
            width=width,
            height=height,
            layout_mode=layout_mode,
        )

        with open(ass_file_path, "w", encoding="utf-8") as f:
            f.write(updated)

        return ass_file_path

    def generate_standalone_ass_file(
        self,
        output_path: str,
        clip_duration: float,
        config: Optional[CTAConfig] = None,
        width: int = 1080,
        height: int = 1920,
        layout_mode: str = "blur_background",
    ) -> str:
        """
        Creates a clean standalone ASS file containing only the animated CTA overlay.
        """
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        style_def, event_lines = self.generate_ass_events(
            clip_duration=clip_duration,
            config=config,
            width=width,
            height=height,
            layout_mode=layout_mode,
            style_name="CTA_Overlay",
        )

        content = (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {width}\n"
            f"PlayResY: {height}\n"
            "WrapStyle: 0\n"
            "ScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"{style_def}\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            f"{event_lines[0]}\n"
        )

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        return output_path

    def build_filtergraph_snippet(
        self,
        clip_duration: float,
        width: int,
        height: int,
        config: Optional[CTAConfig] = None,
        layout_mode: str = "blur_background",
    ) -> str:
        """
        Generates native FFmpeg drawbox and drawtext filterchain filters as an alternative
        to libass subtitles.
        """
        cfg = config or self.default_config
        timing = self.compute_timing(clip_duration, cfg)
        placement = self.calculate_placement(width, height, cfg, layout_mode)

        sanitized_text = sanitize_unicode_for_render(cfg.text)
        escaped_text = escape_ffmpeg_drawtext(sanitized_text)

        box_w = min(placement["safe_width"], max(400, int(len(sanitized_text) * cfg.font_size * 0.65)))
        box_h = int(cfg.font_size * 2.2)
        box_x = placement["center_x"] - (box_w // 2)
        box_y = placement["center_y"] - (box_h // 2)

        st = timing.start_time
        et = timing.end_time

        enable_expr = f"between(t,{st:.3f},{et:.3f})"
        bg_col = "0x0F172A@0.85" if cfg.style != "minimal" else "0x000000@0.60"
        txt_col = "white"

        filters = [
            f"drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}:color={bg_col}:t=fill:enable='{enable_expr}'",
            f"drawtext=text='{escaped_text}':fontsize={cfg.font_size}:fontcolor={txt_col}:x=(w-text_w)/2:y={box_y + (box_h // 4)}:enable='{enable_expr}'",
        ]
        return ",".join(filters)
