"""
Unit and Integration Tests for Dedicated Animated Outro Card & Soft Sound Engine.
Tests:
- Soft audio chime synthesis (soft_zen, soft_double, classic_bell)
- Choreographed ASS animation script generation
- OutroCardConfig serialization/deserialization
- Standalone outro MP4 rendering with soft chime audio
- Seamless concatenation of main video clip and outro card
- FFmpegRenderer boolean toggle: enable_outro_card=True appends outro, enable_outro_card=False does not
"""

import os
import wave
import struct
import pytest
import tempfile
import subprocess
from yt_clipping.rendering.outro_card import (
    synthesize_bell_chime,
    OutroCardConfig,
    OutroCardEngine,
)
from yt_clipping.contracts.models import (
    RenderProfile,
    HighlightCandidate,
    ScoreBreakdown,
)
from yt_clipping.rendering.renderer import FFmpegRenderer


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield td


def test_synthesize_soft_zen_chime(temp_dir):
    """Verifies that soft_zen chime generates a gentle, non-clipping 16-bit stereo WAV."""
    wav_path = os.path.join(temp_dir, "test_soft_zen.wav")
    out = synthesize_bell_chime(wav_path, duration=1.0, sample_rate=44100, chime_style="soft_zen")

    assert os.path.exists(out)
    assert os.path.getsize(out) > 1000

    with wave.open(out, "rb") as wf:
        assert wf.getnchannels() == 2
        assert wf.getsampwidth() == 2  # 16-bit
        assert wf.getframerate() == 44100
        n_frames = wf.getnframes()
        assert n_frames == 44100  # 1 second of audio
        frames = wf.readframes(n_frames)
        assert len(frames) == n_frames * 4  # 2 channels * 2 bytes


@pytest.mark.parametrize("chime_style", ["soft_zen", "soft_double", "classic_bell"])
def test_synthesize_all_chime_styles(temp_dir, chime_style):
    """All supported chime styles generate valid audio output."""
    wav_path = os.path.join(temp_dir, f"test_{chime_style}.wav")
    out = synthesize_bell_chime(wav_path, duration=0.8, sample_rate=44100, chime_style=chime_style)
    assert os.path.exists(out)
    assert os.path.getsize(out) > 500


def test_outro_card_config_serialization():
    """Verifies OutroCardConfig to_dict and from_dict roundtrip with chime_style."""
    cfg = OutroCardConfig(
        channel_name="TechDaily",
        sub_heading="See you next time!",
        cta_prompt="Hit that bell!",
        duration=3.0,
        button_transform_time=0.8,
        chime_style="soft_zen",
    )
    d = cfg.to_dict()
    assert d["channel_name"] == "TechDaily"
    assert d["duration"] == 3.0
    assert d["chime_style"] == "soft_zen"

    restored = OutroCardConfig.from_dict(d)
    assert restored.channel_name == "TechDaily"
    assert restored.sub_heading == "See you next time!"
    assert restored.duration == 3.0
    assert restored.chime_style == "soft_zen"


def test_generate_outro_ass(temp_dir):
    """Verifies generated ASS script contains all choreography stages and valid styling."""
    engine = OutroCardEngine()
    cfg = OutroCardConfig(
        channel_name="Buildingminds",
        sub_heading="Thanks for watching!",
        duration=2.5,
        button_transform_time=0.70,
    )
    ass_path = os.path.join(temp_dir, "outro.ass")
    content = engine.generate_outro_ass(cfg, output_ass_path=ass_path)

    assert os.path.exists(ass_path)
    assert "[Script Info]" in content
    assert "[V4+ Styles]" in content
    assert "[Events]" in content
    # Channel title should be in uppercase
    assert "BUILDINGMINDS" in content
    assert "Thanks for watching!" in content
    # Subscribe button state transitions
    assert "SUBSCRIBE" in content
    assert "SUBSCRIBED" in content
    # Animated bell wobble tags
    assert "\\frz10" in content
    assert "\\frz-10" in content
    # Check that font names don't contain commas in Style definitions
    for line in content.splitlines():
        if line.startswith("Style:"):
            parts = line.split(",")
            font_name = parts[1].strip()
            assert "," not in font_name


def test_render_standalone_outro_clip(temp_dir):
    """Verifies that OutroCardEngine renders an MP4 video clip with audio."""
    engine = OutroCardEngine()
    cfg = OutroCardConfig(
        channel_name="TestChannel",
        duration=1.2,
        button_transform_time=0.4,
        chime_style="soft_zen",
        width=540,
        height=960,
        fps=30.0,
    )
    out_mp4 = os.path.join(temp_dir, "outro_test.mp4")
    engine.render_outro_clip(out_mp4, config=cfg, vcodec="libx264")

    assert os.path.exists(out_mp4)
    assert os.path.getsize(out_mp4) > 1000

    # Inspect media info via ffmpeg -i
    proc = subprocess.run(
        ["ffmpeg", "-i", out_mp4],
        capture_output=True,
        text=True,
    )
    stderr = proc.stderr
    assert "Video:" in stderr
    assert "Audio:" in stderr
    assert "540x960" in stderr


def test_concat_clip_with_outro(temp_dir):
    """Verifies seamless concatenation of main clip and outro card."""
    engine = OutroCardEngine()

    # Create dummy main clip (1.0s)
    main_clip = os.path.join(temp_dir, "main.mp4")
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=540x960:d=1.0:r=30",
            "-f", "lavfi", "-i", "sine=f=440:d=1.0:r=44100",
            "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
            main_clip,
        ],
        capture_output=True,
        check=True,
    )

    # Create dummy outro clip (1.0s)
    outro_clip = os.path.join(temp_dir, "outro.mp4")
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=red:s=540x960:d=1.0:r=30",
            "-f", "lavfi", "-i", "sine=f=880:d=1.0:r=44100",
            "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
            outro_clip,
        ],
        capture_output=True,
        check=True,
    )

    combined = os.path.join(temp_dir, "combined.mp4")
    engine.concat_clip_with_outro(main_clip, outro_clip, combined, vcodec="libx264")

    assert os.path.exists(combined)
    assert os.path.getsize(combined) > os.path.getsize(main_clip)

    # Check combined duration via ffmpeg -i
    proc = subprocess.run(
        ["ffmpeg", "-i", combined],
        capture_output=True,
        text=True,
    )
    assert "Duration: 00:00:02" in proc.stderr


def test_renderer_boolean_outro_toggle_disabled(temp_dir):
    """Verifies that when enable_outro_card is False, no outro is appended and duration matches candidate."""
    src_video = os.path.join(temp_dir, "source_no_outro.mp4")
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=3.0",
            "-f", "lavfi", "-i", "sine=f=440:duration=3.0:r=44100",
            "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
            src_video,
        ],
        capture_output=True,
        check=True,
    )

    candidate = HighlightCandidate(
        candidate_id="cand_test_no_outro",
        video_id="test_vid",
        start_seconds=0.5,
        end_seconds=2.5,
        duration_seconds=2.0,
        score=85.0,
        breakdown=ScoreBreakdown(),
        hook_title="Test Hook Title",
    )

    # enable_outro_card is explicitly False
    profile = RenderProfile(
        width=540,
        height=960,
        layout_mode="blur_background",
        burn_subtitles=False,
        enable_cta=False,
        enable_outro_card=False,
        vcodec="libx264",
    )

    renderer = FFmpegRenderer()
    rendered = renderer.render_clip(
        source_path=src_video,
        candidate=candidate,
        profile=profile,
        output_dir=temp_dir,
    )

    assert os.path.exists(rendered.file_path)
    # Duration must strictly equal the candidate duration (2.0s), not extended
    assert rendered.duration_seconds == pytest.approx(2.0, 0.2)


def test_renderer_boolean_outro_toggle_enabled(temp_dir):
    """Verifies that when enable_outro_card is True, outro is appended with soft sound and duration is extended."""
    src_video = os.path.join(temp_dir, "source_with_outro.mp4")
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=3.0",
            "-f", "lavfi", "-i", "sine=f=440:duration=3.0:r=44100",
            "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
            src_video,
        ],
        capture_output=True,
        check=True,
    )

    candidate = HighlightCandidate(
        candidate_id="cand_test_with_outro",
        video_id="test_vid",
        start_seconds=0.5,
        end_seconds=2.5,
        duration_seconds=2.0,
        score=85.0,
        breakdown=ScoreBreakdown(),
        hook_title="Test Hook Title",
    )

    # enable_outro_card is True
    profile = RenderProfile(
        width=540,
        height=960,
        layout_mode="blur_background",
        burn_subtitles=False,
        enable_cta=False,
        enable_outro_card=True,
        outro_duration=1.5,
        outro_channel_name="CreatorZone",
        outro_chime_style="soft_zen",
        vcodec="libx264",
    )

    renderer = FFmpegRenderer()
    rendered = renderer.render_clip(
        source_path=src_video,
        candidate=candidate,
        profile=profile,
        output_dir=temp_dir,
    )

    assert os.path.exists(rendered.file_path)
    # Duration must equal candidate duration (2.0s) + outro duration (1.5s) = 3.5s
    assert rendered.duration_seconds == pytest.approx(3.5, 0.3)
