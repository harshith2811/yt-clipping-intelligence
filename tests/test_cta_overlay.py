"""
Targeted Regression Test Suite for Self-Contained Animated CTA Overlay Engine.
Tests:
- CTA timing windows (end, intro, persistent, ultra-short clips)
- Entrance and exit duration scaling
- Safe-zone constraints and coordinates calculation (9:16 vertical, landscape, square)
- Subtitle collision avoidance & podcast center divider clearance
- Text escaping, Unicode sanitization, emoji fallback
- Visual styling presets (modern_pill, neon_banner, minimal, unsupported fallback)
- ASS subtitle injection & standalone generation
- Native FFmpeg drawbox/drawtext filtergraph snippet generation
- Full FFmpegRenderer integration with and without subtitles
"""

import os
import pytest
import tempfile
from yt_clipping.rendering.cta_overlay import (
    CTAOverlayEngine,
    CTAConfig,
    CTAStyle,
    CTATiming,
    CTATimingWindow,
    escape_ass_text,
    escape_ffmpeg_drawtext,
    sanitize_unicode_for_render,
)
from yt_clipping.contracts.models import (
    RenderProfile,
    HighlightCandidate,
    ScoreBreakdown,
    Transcript,
    TranscriptSegment,
    WordTimestamp,
)
from yt_clipping.rendering.renderer import FFmpegRenderer


@pytest.fixture
def cta_engine():
    return CTAOverlayEngine()


# ---------------------------------------------------------------------------
# 1. Timing and Duration Tests
# ---------------------------------------------------------------------------

def test_cta_timing_end_mode(cta_engine):
    """Timing mode 'end' should anchor CTA to the end of the clip."""
    cfg = CTAConfig(timing="end", duration=3.5, entrance_duration=0.35, exit_duration=0.30)
    window = cta_engine.compute_timing(clip_duration=30.0, config=cfg)

    assert window.start_time == 26.5
    assert window.end_time == 30.0
    assert window.duration == 3.5
    assert window.entrance_duration == 0.35
    assert window.exit_duration == 0.30
    assert window.active_duration == pytest.approx(2.85, 0.01)


def test_cta_timing_intro_mode(cta_engine):
    """Timing mode 'intro' should start shortly after opening (0.5s) and span duration."""
    cfg = CTAConfig(timing="intro", duration=3.0)
    window = cta_engine.compute_timing(clip_duration=20.0, config=cfg)

    assert window.start_time == 0.5
    assert window.end_time == 3.5
    assert window.duration == 3.0


def test_cta_timing_persistent_mode(cta_engine):
    """Timing mode 'persistent' spans the entirety of the clip."""
    cfg = CTAConfig(timing="persistent")
    window = cta_engine.compute_timing(clip_duration=15.0, config=cfg)

    assert window.start_time == 0.0
    assert window.end_time == 15.0
    assert window.duration == 15.0


def test_cta_timing_short_clip_scaling(cta_engine):
    """When clip is shorter than CTA duration, timing scales without error or overlap."""
    cfg = CTAConfig(timing="end", duration=5.0, entrance_duration=0.35, exit_duration=0.30)
    # Clip is only 0.8 seconds long
    window = cta_engine.compute_timing(clip_duration=0.8, config=cfg)

    assert window.start_time == 0.0
    assert window.end_time == 0.8
    assert window.duration == 0.8
    # Entrance and exit durations must scale down proportionally
    assert window.entrance_duration <= (0.8 * 0.4) + 1e-5
    assert window.exit_duration <= (0.8 * 0.35) + 1e-5
    assert window.entrance_duration + window.exit_duration <= window.duration + 1e-5


def test_cta_timing_zero_or_negative_duration(cta_engine):
    """Degenerate zero or negative duration safely handled."""
    cfg = CTAConfig(timing="end", duration=3.0)
    window = cta_engine.compute_timing(clip_duration=0.0, config=cfg)
    assert window.duration > 0.0
    assert window.end_time >= window.start_time


# ---------------------------------------------------------------------------
# 2. Safe-Zone and Layout Placement Tests
# ---------------------------------------------------------------------------

def test_cta_placement_vertical_9_16(cta_engine):
    """Standard 1080x1920 vertical format placement in lower third above bottom UI."""
    placement = cta_engine.calculate_placement(width=1080, height=1920)

    assert placement["center_x"] == 540
    # Safe margin bottom is 250px, lower third should sit above this margin
    assert placement["center_y"] == 1920 - 250 - 40
    assert placement["safe_width"] == 1080 - (120 * 2)


def test_cta_placement_podcast_split_screen(cta_engine):
    """Podcast split screen layout avoids the center divider at Y=960."""
    placement = cta_engine.calculate_placement(
        width=1080, height=1920, layout_mode="split_screen"
    )

    # Center divider in 1080x1920 split screen is at y=960.
    # Placement must clear 960 and sit comfortably in bottom speaker frame
    assert placement["center_y"] > 960 + 200
    assert placement["center_y"] < 1920 - 100


def test_cta_placement_custom_offset(cta_engine):
    """Custom offset overrides standard anchor calculation."""
    cfg = CTAConfig(custom_y_offset=1400)
    placement = cta_engine.calculate_placement(width=1080, height=1920, config=cfg)
    assert placement["center_y"] == 1400


def test_cta_placement_landscape_and_square(cta_engine):
    """Placement adapts cleanly to landscape 1920x1080 and square 1080x1080."""
    p_land = cta_engine.calculate_placement(width=1920, height=1080)
    assert p_land["center_x"] == 960
    assert p_land["center_y"] > 540  # lower third

    p_sq = cta_engine.calculate_placement(width=1080, height=1080)
    assert p_sq["center_x"] == 540
    assert p_sq["center_y"] > 540


# ---------------------------------------------------------------------------
# 3. Unicode, Emoji, and Text Escaping Tests
# ---------------------------------------------------------------------------

def test_unicode_and_emoji_sanitization():
    """Emoji and control characters are cleanly sanitized without crashing."""
    raw = "🔔 Subscribe now! 👉 Join us 🔥"
    cleaned = sanitize_unicode_for_render(raw)
    assert "[Bell]" in cleaned
    assert ">>" in cleaned
    assert "*" in cleaned
    assert "Subscribe now!" in cleaned

    # Empty string fallback
    assert sanitize_unicode_for_render("") == "Subscribe for more"

    # Control characters stripped
    ctrl = "Hello\x00\x08World\x1f!"
    assert sanitize_unicode_for_render(ctrl) == "HelloWorld!"


def test_ass_and_drawtext_escaping():
    """Tests proper escaping of single quotes, colons, brackets, and braces."""
    text = "Don't miss: [Special] {Feature} \\ Update"
    ass_esc = escape_ass_text(text)
    assert "\\{" in ass_esc and "\\}" in ass_esc

    drawtext_esc = escape_ffmpeg_drawtext(text)
    assert "\\:" in drawtext_esc
    assert "\\'" in drawtext_esc or "'\\''" in drawtext_esc
    assert "\\[" in drawtext_esc and "\\]" in drawtext_esc


# ---------------------------------------------------------------------------
# 4. Style Presets and Unsupported Fallbacks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("style_name", ["modern_pill", "neon_banner", "minimal"])
def test_cta_supported_styles(cta_engine, style_name):
    """All documented styles produce valid style definitions."""
    cfg = CTAConfig(style=style_name)
    style_def, events = cta_engine.generate_ass_events(clip_duration=10.0, config=cfg)
    assert "Style: CTA_Overlay" in style_def
    assert len(events) == 1
    assert "Dialogue:" in events[0]


def test_cta_unsupported_style_fallback(cta_engine):
    """Unsupported style gracefully falls back to modern_pill."""
    cfg = CTAConfig(style="non_existent_cyber_style")
    style_def, events = cta_engine.generate_ass_events(clip_duration=10.0, config=cfg)
    assert "Style: CTA_Overlay" in style_def
    # Should use modern_pill default font Impact
    assert "Impact" in style_def


# ---------------------------------------------------------------------------
# 5. ASS Generation and Injection Tests
# ---------------------------------------------------------------------------

def test_cta_ass_injection_into_existing_file(cta_engine, tmp_path):
    """Injects CTA style and dialogue into existing ASS script preserving subtitles."""
    original_ass = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,60,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,Hello world subtitle\n"
    )
    ass_file = tmp_path / "subs.ass"
    ass_file.write_text(original_ass, encoding="utf-8")

    cta_engine.inject_into_ass_file(str(ass_file), clip_duration=10.0)

    updated_content = ass_file.read_text(encoding="utf-8")
    # Verify original subtitle is preserved
    assert "Hello world subtitle" in updated_content
    # Verify CTA style is injected
    assert "Style: CTA_Overlay" in updated_content
    # Verify CTA dialogue event is injected
    assert "CTA_Overlay" in updated_content
    assert "\\move(" in updated_content
    assert "\\fad(" in updated_content


def test_cta_standalone_ass_generation(cta_engine, tmp_path):
    """Creates standalone ASS file when subtitles are disabled."""
    out_file = tmp_path / "cta_standalone.ass"
    cta_engine.generate_standalone_ass_file(str(out_file), clip_duration=20.0)

    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "[Script Info]" in content
    assert "[V4+ Styles]" in content
    assert "[Events]" in content
    assert "CTA_Overlay" in content


# ---------------------------------------------------------------------------
# 6. Native Filtergraph Snippet Tests
# ---------------------------------------------------------------------------

def test_cta_build_filtergraph_snippet(cta_engine):
    """Builds valid FFmpeg drawbox and drawtext filter strings."""
    cfg = CTAConfig(text="Follow us on YouTube", duration=4.0)
    fg = cta_engine.build_filtergraph_snippet(
        clip_duration=10.0, width=1080, height=1920, config=cfg
    )

    assert "drawbox=" in fg
    assert "drawtext=" in fg
    assert "between(t," in fg
    assert "Follow us on YouTube" in fg


# ---------------------------------------------------------------------------
# 7. End-to-End FFmpegRenderer CTA Integration Tests
# ---------------------------------------------------------------------------

def test_renderer_with_cta_enabled(tmp_path):
    """FFmpegRenderer incorporates CTA into command and filtergraph."""
    renderer = FFmpegRenderer(allow_synthetic=True)
    profile = RenderProfile(
        width=1080,
        height=1920,
        layout_mode="blur_background",
        burn_subtitles=True,
        enable_cta=True,
        cta_text="Subscribe now for more clips",
        cta_timing="end",
        cta_style="modern_pill",
    )

    candidate = HighlightCandidate(
        candidate_id="c_test_cta",
        video_id="v_test_cta",
        start_seconds=10.0,
        end_seconds=25.0,
        duration_seconds=15.0,
        score=85.0,
        breakdown=ScoreBreakdown(hook_score=9.0, moment_score=8.0),
        hook_title="Amazing AI Discovery",
    )

    transcript = Transcript(
        video_id="v_test_cta",
        language="en",
        duration_seconds=120.0,
        text="This is an incredible AI breakthrough.",
        segments=[
            TranscriptSegment(
                segment_id=1,
                start=10.5,
                end=14.0,
                text="This is an incredible AI breakthrough.",
                words=[
                    WordTimestamp(word="This", start=10.5, end=11.0),
                    WordTimestamp(word="is", start=11.0, end=11.5),
                    WordTimestamp(word="incredible", start=11.5, end=12.5),
                    WordTimestamp(word="breakthrough", start=12.5, end=14.0),
                ],
            )
        ],
    )

    clip = renderer.render_clip(
        source_path="dummy_source.mp4",
        candidate=candidate,
        profile=profile,
        output_dir=str(tmp_path),
        transcript=transcript,
    )

    assert os.path.exists(clip.file_path)
    assert os.path.exists(clip.manifest_path)

    # Verify subtitle .ass file contains injected CTA overlay
    sub_file = tmp_path / f"{candidate.candidate_id}.ass"
    assert sub_file.exists()
    content = sub_file.read_text(encoding="utf-8")
    assert "CTA_Overlay" in content
    assert "Subscribe now for more clips" in content


def test_renderer_with_cta_no_subtitles(tmp_path):
    """FFmpegRenderer generates standalone CTA ASS file when burn_subtitles is False."""
    renderer = FFmpegRenderer(allow_synthetic=True)
    profile = RenderProfile(
        width=1080,
        height=1920,
        layout_mode="crop_center",
        burn_subtitles=False,
        enable_cta=True,
        cta_text="Follow our daily show",
    )

    candidate = HighlightCandidate(
        candidate_id="c_test_cta_nosub",
        video_id="v_test_cta_nosub",
        start_seconds=5.0,
        end_seconds=15.0,
        duration_seconds=10.0,
        score=78.0,
        breakdown=ScoreBreakdown(hook_score=8.0, moment_score=7.5),
        hook_title="Clean Clip",
    )

    clip = renderer.render_clip(
        source_path="dummy_source.mp4",
        candidate=candidate,
        profile=profile,
        output_dir=str(tmp_path),
        transcript=None,
    )

    assert os.path.exists(clip.file_path)
    cta_ass = tmp_path / f"{candidate.candidate_id}_cta.ass"
    assert cta_ass.exists()
    content = cta_ass.read_text(encoding="utf-8")
    assert "Follow our daily show" in content


def test_podcast_short_maker_cta_overlay_integration(tmp_path):
    """
    Verify that PodcastShortMaker integrates with CTAOverlayEngine:
    1. Injects CTA into subtitle ASS when burn_subtitles is True.
    2. Generates standalone CTA ASS when burn_subtitles is False.
    3. Respects split-screen lower-third positioning avoiding the center divider bar.
    """
    from yt_clipping.podcast.config import PodcastLayoutConfig
    from yt_clipping.podcast.pipeline import PodcastShortMaker

    cfg_subs = PodcastLayoutConfig(
        burn_subtitles=True,
        enable_cta=True,
        cta_text="Subscribe to the podcast",
        cta_timing="end",
        cta_style="modern_pill",
    )
    maker = PodcastShortMaker(config=cfg_subs)

    # 1. Placement safe zone for split screen
    placement = maker.cta_engine.calculate_placement(1080, 1920, layout_mode="split_screen")
    # Divider is at 960px. Center of CTA must be in bottom speaker area (> 960)
    assert placement["center_y"] > 960
    assert placement["center_y"] == int(960 + 960 * 0.78)

    # 2. Standalone CTA generation when burn_subtitles=False
    cta_ass = str(tmp_path / "podcast_cta.ass")
    maker.cta_engine.generate_standalone_ass_file(
        output_path=cta_ass,
        clip_duration=20.0,
        config=CTAConfig(text="Follow the podcast", style="neon_banner"),
        width=1080,
        height=1920,
        layout_mode="split_screen",
    )
    assert os.path.exists(cta_ass)
    content = open(cta_ass, "r", encoding="utf-8").read()
    assert "CTA_Overlay" in content
    assert "Follow the podcast" in content
    assert f",{placement['center_x']},{placement['center_y']}," in content

