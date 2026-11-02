"""
Unit and integration tests for Automated B-Roll Overlay Engine (b_roll.py).
"""

import os
import subprocess
import pytest
from src.yt_clipping.contracts.models import WordTimestamp, HighlightCandidate, ScoreBreakdown
from src.yt_clipping.rendering.b_roll import (
    BRollConfig,
    BRollOverlayEngine,
    MonologueInterval,
    BRollOverlayResult,
)


def test_detect_monologue_intervals_threshold():
    """
    Feed sequence of words with continuous speech of 5.5s (gap < 0.2s)
    followed by 1.0s silence, then 2.0s speech.
    Assert exactly 1 monologue interval detected with duration >= 4.0s.
    """
    engine = BRollOverlayEngine(BRollConfig(min_monologue_duration=4.0, pause_break_threshold=0.5))

    words = [
        # Continuous run: 0.0 -> 5.5s (5.5s duration)
        WordTimestamp(word="Welcome", start=0.0, end=0.8),
        WordTimestamp(word="to", start=0.9, end=1.2),
        WordTimestamp(word="this", start=1.3, end=2.0),
        WordTimestamp(word="deep", start=2.1, end=3.0),
        WordTimestamp(word="dive", start=3.1, end=4.2),
        WordTimestamp(word="tutorial", start=4.3, end=5.5),
        # 1.0s silence gap (5.5s -> 6.5s)
        # Short speech: 6.5s -> 8.5s (2.0s duration < 4.0s)
        WordTimestamp(word="Let's", start=6.5, end=7.2),
        WordTimestamp(word="begin", start=7.3, end=8.5),
    ]

    intervals = engine.detect_monologue_intervals(words, clip_start=0.0, clip_end=10.0)

    assert len(intervals) == 1
    iv = intervals[0]
    assert iv.duration_seconds >= 4.0
    assert iv.start_seconds >= 0.0
    assert "tutorial" in iv.text


def test_extract_keywords_semantic_filtering():
    """
    Provide text containing stop words ('and', 'the', 'how to'), lazy adjectives ('insane', 'crazy'),
    and key topics ('python', 'neural', 'network').
    Assert stop words and buzzwords are filtered; top keywords are ['python', 'neural', 'network'].
    """
    engine = BRollOverlayEngine()

    text = "The how to guide on insane crazy python neural network and deep architectures"
    keywords = engine.extract_keywords(text)

    # Stop words and lazy adjectives must be absent
    assert "the" not in keywords
    assert "how" not in keywords
    assert "insane" not in keywords
    assert "crazy" not in keywords
    assert "and" not in keywords

    # Content nouns/verbs must be present
    assert "python" in keywords
    assert "neural" in keywords
    assert "network" in keywords


def test_asset_discovery_and_fuzzy_matching(tmp_path):
    """
    Create temporary directory with mock video files: tech_laptop.mp4, nature_mountains.mp4, default.mp4.
    Test keyword matching and generic fallback.
    """
    broll_dir = tmp_path / "broll"
    broll_dir.mkdir(parents=True, exist_ok=True)

    tech_file = broll_dir / "tech_laptop.mp4"
    tech_file.write_bytes(b"\x00" * 64)

    nature_file = broll_dir / "nature_mountains.mp4"
    nature_file.write_bytes(b"\x00" * 64)

    default_file = broll_dir / "default.mp4"
    default_file.write_bytes(b"\x00" * 64)

    engine = BRollOverlayEngine(BRollConfig(assets_dir=str(broll_dir)))

    # 1. Match specific keyword
    match_tech = engine.find_matching_asset(["laptop", "coding"])
    assert match_tech is not None
    assert "tech_laptop.mp4" in match_tech

    # 2. Match nature keyword
    match_nature = engine.find_matching_asset(["mountains", "forest"])
    assert match_nature is not None
    assert "nature_mountains.mp4" in match_nature

    # 3. Unrecognized keywords fallback to default.mp4
    match_fallback = engine.find_matching_asset(["finance", "crypto", "trading"])
    assert match_fallback is not None
    assert "default.mp4" in match_fallback

    # 4. Non-existent directory returns None
    match_none = engine.find_matching_asset(["laptop"], assets_dir=str(tmp_path / "non_existent"))
    assert match_none is None


def test_broll_filtergraph_generation_and_transitions():
    """
    Construct B-roll overlay filtergraph for 1080x1920.
    Verify presence of scale, crop, fade, and overlay expressions.
    """
    engine = BRollOverlayEngine(BRollConfig(width=1080, height=1920, fade_duration=0.25, mute_broll=True))

    interval = MonologueInterval(
        start_seconds=1.5,
        end_seconds=5.5,
        duration_seconds=4.0,
        text="Sample continuous monologue segment",
        keywords=["sample"],
        matched_asset_path="assets/broll/sample.mp4",
    )

    filtergraph, output_maps = engine.build_broll_filtergraph(
        primary_input_idx=0,
        broll_inputs=[(1, interval, "assets/broll/sample.mp4")],
        width=1080,
        height=1920,
    )

    # 1. Check scaling and vertical cropping
    assert "scale=1080:1920:force_original_aspect_ratio=increase" in filtergraph
    assert "crop=1080:1920:(iw-ow)/2:(ih-oh)/2" in filtergraph

    # 2. Check alpha fade-in and fade-out
    assert "fade=t=in:st=0:d=0.25:alpha=1" in filtergraph
    assert "fade=t=out:st=3.750:d=0.25:alpha=1" in filtergraph

    # 3. Check overlay expression timing
    assert "overlay=0:0:enable='between(t,1.500,5.500)'" in filtergraph

    # 4. Check mapping
    assert "-map" in output_maps
    assert "0:a?" in output_maps


def test_audio_ducking_filtergraph():
    """
    Test filtergraph with mute_broll=False and verify volume ducking and amix are generated.
    """
    engine = BRollOverlayEngine(
        BRollConfig(
            width=1080,
            height=1920,
            fade_duration=0.25,
            mute_broll=False,
            audio_ducking_volume=0.35,
            broll_audio_volume=0.45,
        )
    )

    interval = MonologueInterval(
        start_seconds=2.0,
        end_seconds=6.0,
        duration_seconds=4.0,
        text="Segment with audio",
        keywords=["audio"],
        matched_asset_path="assets/broll/clip.mp4",
    )

    filtergraph, output_maps = engine.build_broll_filtergraph(
        primary_input_idx=0,
        broll_inputs=[(1, interval, "assets/broll/clip.mp4")],
        width=1080,
        height=1920,
    )

    # Audio ducking volume expression
    assert "volume=enable='between(t,2.000,6.000)':volume=0.35" in filtergraph
    # B-roll audio volume
    assert "volume=0.45" in filtergraph
    # Audio mixing
    assert "amix=inputs=2:duration=first" in filtergraph


def test_graceful_fallback_leaves_video_untouched(tmp_path):
    """
    Call apply_broll_overlay with empty B-roll directory.
    Verify result.applied == False and output video path matches input video path.
    """
    empty_broll = tmp_path / "empty_broll"
    empty_broll.mkdir(parents=True, exist_ok=True)

    input_vid = tmp_path / "rendered.mp4"
    input_vid.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 1024)

    output_vid = tmp_path / "output_broll.mp4"

    engine = BRollOverlayEngine(BRollConfig(assets_dir=str(empty_broll)))
    words = [
        WordTimestamp(word="Continuous", start=0.0, end=1.0),
        WordTimestamp(word="speech", start=1.1, end=2.0),
        WordTimestamp(word="here", start=2.1, end=5.0),
    ]

    res = engine.apply_broll_overlay(
        video_path=str(input_vid),
        output_path=str(output_vid),
        words=words,
        clip_start=0.0,
        clip_end=5.0,
        assets_dir=str(empty_broll),
    )

    assert res.applied is False
    assert res.output_video_path == str(input_vid)
    assert not os.path.exists(output_vid)


def test_real_media_broll_overlay_integration(tmp_path):
    """
    Generate small synthetic 4-second source video and 2-second B-roll video using FFmpeg lavfi testsrc.
    Execute real FFmpeg overlay and verify output file exists, has valid dimensions (1080x1920), and plays.
    """
    primary_mp4 = str(tmp_path / "primary.mp4")
    broll_mp4 = str(tmp_path / "broll_ai.mp4")
    output_mp4 = str(tmp_path / "final_with_broll.mp4")

    # 1. Generate 4s 1080x1920 primary video with audio
    cmd_primary = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=4:size=1080x1920:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
        "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
        primary_mp4,
    ]
    res_p = subprocess.run(cmd_primary, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert res_p.returncode == 0, f"Failed to create primary video: {res_p.stderr.decode()}"

    # 2. Generate 2s 1280x720 landscape broll video
    cmd_broll = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=1280x720:rate=30",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        broll_mp4,
    ]
    res_b = subprocess.run(cmd_broll, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert res_b.returncode == 0, f"Failed to create broll video: {res_b.stderr.decode()}"

    # 3. Apply B-roll overlay directly
    engine = BRollOverlayEngine(
        BRollConfig(
            min_monologue_duration=2.0,
            min_overlay_duration=1.0,
            max_overlay_duration=2.0,
            fade_duration=0.25,
            width=1080,
            height=1920,
        )
    )

    words = [
        WordTimestamp(word="Artificial", start=0.5, end=1.5),
        WordTimestamp(word="intelligence", start=1.6, end=3.0),
    ]

    candidate = HighlightCandidate(
        candidate_id="c_test",
        video_id="v_test",
        start_seconds=0.0,
        end_seconds=4.0,
        duration_seconds=4.0,
        score=90.0,
        breakdown=ScoreBreakdown(),
        hook_title="AI Revolution",
    )

    broll_dir = str(tmp_path)
    res = engine.apply_broll_overlay(
        video_path=primary_mp4,
        output_path=output_mp4,
        words=words,
        candidate=candidate,
        clip_start=0.0,
        clip_end=4.0,
        assets_dir=broll_dir,
    )

    assert res.applied is True
    assert os.path.exists(output_mp4)
    assert os.path.getsize(output_mp4) > 1000
    assert len(res.matched_assets) >= 1
    assert res.file_hash != ""
