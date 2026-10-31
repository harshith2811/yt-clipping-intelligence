"""
Tests for FFmpeg rendering filtergraphs, layout modes, subtitle generation, and atomic file promotion.
"""

import pytest
import os
from src.yt_clipping.contracts.models import HighlightCandidate, ScoreBreakdown, RenderProfile, Transcript, TranscriptSegment, WordTimestamp
from src.yt_clipping.rendering.captions import SubtitleGenerator
from src.yt_clipping.rendering.renderer import FFmpegRenderer


def test_ass_subtitle_generation_with_safe_margins(tmp_path):
    sub_gen = SubtitleGenerator()
    cand = HighlightCandidate(
        candidate_id="c1",
        video_id="v1",
        start_seconds=10.0,
        end_seconds=30.0,
        duration_seconds=20.0,
        score=75.0,
        breakdown=ScoreBreakdown(),
        hook_title="Subtitle Test",
    )
    words = [
        WordTimestamp(word="Building", start=10.0, end=10.5),
        WordTimestamp(word="reliable", start=10.6, end=11.2),
        WordTimestamp(word="AI", start=11.3, end=11.8),
        WordTimestamp(word="clipping", start=12.0, end=12.6),
    ]
    seg = TranscriptSegment(segment_id=1, start=10.0, end=15.0, text="Building reliable AI clipping", words=words)
    transcript = Transcript(
        video_id="v1", language="en", duration_seconds=60.0, text="Building reliable AI clipping", segments=[seg]
    )

    out_ass = str(tmp_path / "test_captions.ass")
    sub_gen.generate_ass(cand, transcript, out_ass)

    assert os.path.exists(out_ass)
    with open(out_ass, "r", encoding="utf-8") as f:
        content = f.read()

    # Verify 1080x1920 play resolution and safe vertical margins
    assert "PlayResX: 1080" in content
    assert "PlayResY: 1920" in content
    assert "MarginV" in content
    assert "Dialogue:" in content
    assert "Building reliable AI clipping" in content


def test_kinetic_karaoke_subtitle_generation(tmp_path):
    sub_gen = SubtitleGenerator(style_preset="karaoke")
    cand = HighlightCandidate(
        candidate_id="c_karaoke",
        video_id="v_karaoke",
        start_seconds=0.0,
        end_seconds=10.0,
        duration_seconds=10.0,
        score=85.0,
        breakdown=ScoreBreakdown(),
        hook_title="Karaoke Test",
    )
    words = [
        WordTimestamp(word="Automated", start=0.5, end=1.2),
        WordTimestamp(word="video", start=1.3, end=1.8),
        WordTimestamp(word="clipping", start=1.9, end=2.5),
    ]
    seg = TranscriptSegment(segment_id=1, start=0.5, end=2.5, text="Automated video clipping", words=words)
    transcript = Transcript(
        video_id="v_karaoke", language="en", duration_seconds=10.0, text="Automated video clipping", segments=[seg]
    )

    out_ass = str(tmp_path / "karaoke_captions.ass")
    sub_gen.generate_ass(cand, transcript, out_ass)

    assert os.path.exists(out_ass)
    with open(out_ass, "r", encoding="utf-8") as f:
        content = f.read()

    # Verify karaoke {\k...} tags and font styling
    assert r"{\k" in content
    assert "Style: Default,Impact,58" in content
    assert "MarginV,290" in content or "290,1" in content
    assert "Dialogue:" in content


def test_ffmpeg_filtergraph_construction():
    renderer = FFmpegRenderer()
    profile_center = RenderProfile(width=1080, height=1920, layout_mode="crop_center")
    vf_center = renderer.build_filtergraph(profile_center, subtitle_ass_path="subs.ass")
    assert "crop=ih*9/16:ih:(iw-ow)/2:0" in vf_center
    assert "scale=1080:1920" in vf_center
    assert "setsar=1" in vf_center
    assert "subtitles='subs.ass'" in vf_center

    cmd_center = renderer.build_ffmpeg_command("src.mp4", 0.0, 30.0, profile_center, "out.mp4", "subs.ass")
    assert "-vf" in cmd_center

    # Blur background padding layout
    profile_blur = RenderProfile(width=1080, height=1920, layout_mode="blur_background")
    vf_blur = renderer.build_filtergraph(profile_blur, subtitle_ass_path="subs.ass")
    assert "boxblur=25:5" in vf_blur
    assert "overlay=0:(H-h)/2" in vf_blur
    assert "setsar=1" in vf_blur
    assert "subtitles='subs.ass'" in vf_blur

    cmd_blur = renderer.build_ffmpeg_command("src.mp4", 0.0, 30.0, profile_blur, "out.mp4", "subs.ass")
    assert "-filter_complex" in cmd_blur
    assert "-map" in cmd_blur
    assert "[v]" in cmd_blur

    # Split screen dual-aspect 9:8 layout
    profile_split = RenderProfile(width=1080, height=1920, layout_mode="split_screen")
    vf_split = renderer.build_filtergraph(profile_split)
    assert "crop=ih*9/8:ih:0:0" in vf_split
    assert "crop=ih*9/8:ih:iw-ow:0" in vf_split
    assert "vstack=inputs=2[stacked]" in vf_split
    assert "[stacked]setsar=1[v]" in vf_split

    # Verify split screen with subtitles burns onto stacked pad
    vf_split_subs = renderer.build_filtergraph(profile_split, subtitle_ass_path="subs.ass")
    assert "[stacked]setsar=1,subtitles='subs.ass'[v]" in vf_split_subs

    cmd_split = renderer.build_ffmpeg_command("src.mp4", 0.0, 30.0, profile_split, "out.mp4", "subs.ass")
    assert "-filter_complex" in cmd_split
    assert "-map" in cmd_split
    assert "[v]" in cmd_split

    # Verify NVIDIA NVENC GPU hardware encoder command assembly
    profile_nvenc = RenderProfile(vcodec="h264_nvenc")
    cmd_nvenc = renderer.build_ffmpeg_command("src.mp4", 0.0, 30.0, profile_nvenc, "out.mp4")
    assert "-c:v" in cmd_nvenc
    assert "h264_nvenc" in cmd_nvenc
    assert "-preset" in cmd_nvenc
    assert "p4" in cmd_nvenc
    assert "-cq" in cmd_nvenc


def test_atomic_file_promotion_and_synthetic_render(tmp_path):
    renderer = FFmpegRenderer()
    cand = HighlightCandidate(
        candidate_id="cand_test_atomic",
        video_id="vid_test_atomic",
        start_seconds=5.0,
        end_seconds=35.0,
        duration_seconds=30.0,
        score=82.0,
        breakdown=ScoreBreakdown(),
        hook_title="Atomic Render Test",
    )
    profile = RenderProfile()

    # Create dummy source
    src_file = str(tmp_path / "source.mp4")
    with open(src_file, "wb") as f:
        f.write(b"dummy source video payload")

    rendered = renderer.render_clip(
        source_path=src_file,
        candidate=cand,
        profile=profile,
        output_dir=str(tmp_path / "output"),
    )

    # Verify final artifact exists and temp file was cleaned up
    assert os.path.exists(rendered.file_path)
    assert not os.path.exists(f"{rendered.file_path}.tmp.mp4")
    assert os.path.exists(rendered.manifest_path)
    assert len(rendered.file_hash) == 64  # SHA-256


def test_hormozi_kinetic_bounce_subtitles_and_sentiment(tmp_path):
    sub_gen = SubtitleGenerator(style_preset="hormozi")
    cand = HighlightCandidate(
        candidate_id="c_hormozi",
        video_id="v_hormozi",
        start_seconds=0.0,
        end_seconds=10.0,
        duration_seconds=10.0,
        score=90.0,
        breakdown=ScoreBreakdown(),
        hook_title="Hormozi Kinetic Test",
    )
    words = [
        WordTimestamp(word="The", start=0.5, end=0.8),
        WordTimestamp(word="infamous", start=0.9, end=1.4),
        WordTimestamp(word="Zodiac", start=1.5, end=2.0),
        WordTimestamp(word="killer", start=2.1, end=2.7),
    ]
    seg = TranscriptSegment(segment_id=1, start=0.5, end=2.7, text="The infamous Zodiac killer", words=words)
    transcript = Transcript(video_id="v_hormozi", language="en", duration_seconds=10.0, text="The infamous Zodiac killer", segments=[seg])

    out_ass = str(tmp_path / "hormozi.ass")
    sub_gen.generate_ass(cand, transcript, out_ass)

    assert os.path.exists(out_ass)
    with open(out_ass, "r", encoding="utf-8") as f:
        content = f.read()

    # Verify Impact font, uppercase conversion, and bounce animations
    assert "Style: Default,Impact,66" in content
    assert r"\fscx116" in content  # Bounce animation tag
    assert "KILLER" in content     # Uppercase styling
    assert r"\c&H002020FF&" in content  # Danger crimson red for 'KILLER'
    assert r"\c&H0000D7FF&" in content  # Mystery gold for 'ZODIAC'


def test_beast_bounce_rapid_chunks(tmp_path):
    sub_gen = SubtitleGenerator(style_preset="beast_bounce")
    assert sub_gen.chunk_size == 2
    assert sub_gen.highlight_color == "&H0033FF00"  # Lime Green
    assert sub_gen.bounce_animation is True
    assert sub_gen.uppercase is True

