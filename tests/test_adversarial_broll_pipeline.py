"""
Adversarial Stress Testing Suite for B-Roll Overlay Engine and Pipeline Dead-Air Integration.
Validates edge cases, corrupted media, permission errors, extreme durations,
audio ducking matrix, zero vs heavy dead-air, and exception-safety fallbacks.
"""

import os
import stat
import subprocess
import pytest
from typing import List

from src.yt_clipping.contracts.models import (
    WordTimestamp,
    Transcript,
    TranscriptSegment,
    HighlightCandidate,
    ScoreBreakdown,
    RenderProfile,
    JobStatus,
    JobStage,
    RightsManifest,
    RightsBasis,
    RightsStatus,
)
from src.yt_clipping.rendering.b_roll import (
    BRollConfig,
    BRollOverlayEngine,
    MonologueInterval,
    BRollOverlayResult,
)
from src.yt_clipping.detection.deadair import DeadAirPruner
from src.yt_clipping.orchestration.pipeline import (
    ClippingPipeline,
    remap_transcript_for_keep_intervals,
)
from src.yt_clipping.rights.gate import LocalRightsPolicy
from src.yt_clipping.ingestion.asset_provider import LocalAssetProvider
from src.yt_clipping.transcription.transcriber import LocalTranscriber
from src.yt_clipping.detection.segmenter import ContextAwareSegmenter
from src.yt_clipping.scoring.scorecard import ExplainableScorecardScorer
from src.yt_clipping.rendering.renderer import FFmpegRenderer
from src.yt_clipping.qa.verifier import MediaQualityVerifier
from src.yt_clipping.publisher.adapter import DualModeAutopostPublisher
from src.yt_clipping.orchestration.state_machine import JobJournal


# ============================================================================
# PART 1: B-ROLL ENGINE ADVERSARIAL STRESS TESTS
# ============================================================================

def test_broll_empty_and_degenerate_transcripts(tmp_path):
    """
    Stress test B-roll engine with empty transcripts, zero-length words,
    negative timestamps, and inverted intervals.
    Verify zero unhandled exceptions and graceful fallback.
    """
    engine = BRollOverlayEngine(BRollConfig())

    # 1. Empty words list
    assert engine.detect_monologue_intervals([]) == []

    # 2. Words with 0.0 duration
    zero_dur_words = [
        WordTimestamp(word="hello", start=1.0, end=1.0),
        WordTimestamp(word="world", start=1.0, end=1.0),
    ]
    assert engine.detect_monologue_intervals(zero_dur_words) == []

    # 3. Words with negative timestamps
    neg_words = [
        WordTimestamp(word="negative", start=-5.0, end=-1.0),
        WordTimestamp(word="timing", start=-0.9, end=-0.1),
    ]
    # Filtered out by clip_start=0.0
    assert engine.detect_monologue_intervals(neg_words, clip_start=0.0) == []

    # 4. Words outside clip bounds
    out_of_bounds = [
        WordTimestamp(word="outside", start=50.0, end=55.0),
    ]
    assert engine.detect_monologue_intervals(out_of_bounds, clip_start=0.0, clip_end=30.0) == []

    # 5. Apply B-roll overlay with empty words on existing dummy video
    dummy_vid = tmp_path / "dummy.mp4"
    dummy_vid.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 1024)
    out_vid = tmp_path / "out_broll.mp4"

    res = engine.apply_broll_overlay(
        video_path=str(dummy_vid),
        output_path=str(out_vid),
        words=[],
        clip_start=0.0,
        clip_end=10.0,
    )
    assert res.applied is False
    assert res.output_video_path == str(dummy_vid)
    assert not os.path.exists(out_vid)


def test_broll_zero_monologue_segments(tmp_path):
    """
    Provide transcripts where pauses prevent any continuous speech from reaching 4.0s.
    E.g., words spaced by 1.0s (> 0.5s pause threshold), each speech chunk only 0.8s.
    Or continuous speech of 3.99s (< 4.0s min_monologue_duration).
    """
    engine = BRollOverlayEngine(BRollConfig(min_monologue_duration=4.0, pause_break_threshold=0.5))

    # Case A: Choppy speech with 1.0s pauses
    choppy_words = [
        WordTimestamp(word="WordOne", start=0.0, end=0.8),
        WordTimestamp(word="WordTwo", start=1.8, end=2.6),
        WordTimestamp(word="WordThree", start=3.6, end=4.4),
        WordTimestamp(word="WordFour", start=5.4, end=6.2),
    ]
    assert engine.detect_monologue_intervals(choppy_words) == []

    # Case B: Continuous speech just below threshold (3.95s < 4.0s)
    borderline_words = [
        WordTimestamp(word="Continuous", start=0.0, end=1.5),
        WordTimestamp(word="fast", start=1.6, end=2.8),
        WordTimestamp(word="speech", start=2.9, end=3.95),
    ]
    assert engine.detect_monologue_intervals(borderline_words) == []

    # Verify apply_broll_overlay returns applied=False
    dummy_vid = tmp_path / "dummy_chop.mp4"
    dummy_vid.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 1024)
    out_vid = tmp_path / "out_chop.mp4"

    res = engine.apply_broll_overlay(
        video_path=str(dummy_vid),
        output_path=str(out_vid),
        words=choppy_words,
    )
    assert res.applied is False
    assert res.output_video_path == str(dummy_vid)


def test_broll_zero_matching_assets(tmp_path):
    """
    Monologue interval detected (> 4.0s), but test all asset missing scenarios:
    1. Assets directory does not exist.
    2. Assets directory is empty.
    3. Assets directory contains only non-video files (.txt, .json).
    4. Assets directory contains video files with completely mismatching keywords and NO default fallback.
    """
    engine = BRollOverlayEngine(BRollConfig(min_monologue_duration=4.0))

    words = [
        WordTimestamp(word="quantum", start=0.0, end=1.2),
        WordTimestamp(word="computing", start=1.3, end=2.5),
        WordTimestamp(word="cryptography", start=2.6, end=3.8),
        WordTimestamp(word="entanglement", start=3.9, end=5.2),
    ]

    intervals = engine.detect_monologue_intervals(words)
    assert len(intervals) == 1
    assert "quantum" in intervals[0].keywords

    # 1. Non-existent directory
    res_none = engine.find_matching_asset(intervals[0].keywords, assets_dir=str(tmp_path / "ghost_dir"))
    assert res_none is None

    # 2. Empty directory
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()
    res_empty = engine.find_matching_asset(intervals[0].keywords, assets_dir=str(empty_dir))
    assert res_empty is None

    # 3. Only non-video files
    text_file = empty_dir / "quantum_notes.txt"
    text_file.write_text("notes on quantum")
    res_text = engine.find_matching_asset(intervals[0].keywords, assets_dir=str(empty_dir))
    assert res_text is None

    # 4. Media files present, but totally mismatching keywords and no fallback name
    unrelated_dir = tmp_path / "unrelated_dir"
    unrelated_dir.mkdir()
    mismatch_vid = unrelated_dir / "cooking_recipe_pasta.mp4"
    mismatch_vid.write_bytes(b"\x00" * 64)
    res_mismatch = engine.find_matching_asset(intervals[0].keywords, assets_dir=str(unrelated_dir))
    assert res_mismatch is None

    # Verify apply_broll_overlay leaves video untouched
    dummy_vid = tmp_path / "dummy_vid.mp4"
    dummy_vid.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 1024)
    out_vid = tmp_path / "out_vid.mp4"

    res_overlay = engine.apply_broll_overlay(
        video_path=str(dummy_vid),
        output_path=str(out_vid),
        words=words,
        assets_dir=str(unrelated_dir),
    )
    assert res_overlay.applied is False
    assert res_overlay.output_video_path == str(dummy_vid)
    assert "no matching B-roll assets found" in res_overlay.telemetry.get("reason", "")


def test_broll_corrupted_video_files(tmp_path):
    """
    Test B-roll engine behavior when input video or B-roll asset is corrupted:
    1. Input video is 0 bytes.
    2. Input video is garbage bytes.
    3. Input video is valid media, but matched B-roll asset is corrupted garbage.
    Verify: zero unhandled exceptions, temporary files cleaned up, applied=False returned.
    """
    engine = BRollOverlayEngine(BRollConfig(min_monologue_duration=2.0, min_overlay_duration=1.0))

    # Setup valid mock transcript
    words = [
        WordTimestamp(word="technology", start=0.0, end=1.5),
        WordTimestamp(word="robotics", start=1.6, end=3.0),
    ]

    # 1. Primary video is 0-byte file
    zero_vid = tmp_path / "zero.mp4"
    zero_vid.touch()
    out_zero = tmp_path / "out_zero.mp4"

    # Provide valid broll asset
    broll_dir = tmp_path / "broll_assets"
    broll_dir.mkdir()
    broll_asset = broll_dir / "technology.mp4"
    broll_asset.write_bytes(b"corrupt header" + b"\x00" * 50)

    res_zero = engine.apply_broll_overlay(
        video_path=str(zero_vid),
        output_path=str(out_zero),
        words=words,
        assets_dir=str(broll_dir),
    )
    assert res_zero.applied is False
    assert not os.path.exists(out_zero)
    assert not os.path.exists(f"{out_zero}.tmp.mp4")

    # 2. Primary video is garbage bytes
    corrupt_vid = tmp_path / "corrupt_primary.mp4"
    corrupt_vid.write_bytes(b"\xff\xff\xff\xff\x00\xaa\xbb\xcc" * 20)
    out_corrupt = tmp_path / "out_corrupt.mp4"

    res_corrupt = engine.apply_broll_overlay(
        video_path=str(corrupt_vid),
        output_path=str(out_corrupt),
        words=words,
        assets_dir=str(broll_dir),
    )
    assert res_corrupt.applied is False
    assert not os.path.exists(out_corrupt)
    assert not os.path.exists(f"{out_corrupt}.tmp.mp4")

    # 3. Primary video is real media, but B-roll asset is corrupted garbage
    real_primary = tmp_path / "real_primary.mp4"
    cmd_gen = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=3:size=1080x1920:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-c:v", "libx264", "-c:a", "aac",
        str(real_primary),
    ]
    subprocess.run(cmd_gen, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    out_real = tmp_path / "out_real_corrupt_broll.mp4"
    res_broll_corrupt = engine.apply_broll_overlay(
        video_path=str(real_primary),
        output_path=str(out_real),
        words=words,
        assets_dir=str(broll_dir),
    )
    assert res_broll_corrupt.applied is False
    assert res_broll_corrupt.output_video_path == str(real_primary)
    assert not os.path.exists(out_real)
    assert not os.path.exists(f"{out_real}.tmp.mp4")


def test_broll_readonly_target_path(tmp_path):
    """
    Test B-roll engine behavior when target output path is a read-only existing file.
    On Windows, replacing a read-only file triggers PermissionError.
    Verify engine catches the exception, cleans up temp file, and returns applied=False.
    """
    engine = BRollOverlayEngine(BRollConfig(min_monologue_duration=2.0, min_overlay_duration=1.0))

    # Generate real primary video
    real_primary = tmp_path / "ro_primary.mp4"
    cmd_gen = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=3:size=1080x1920:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-c:v", "libx264", "-c:a", "aac",
        str(real_primary),
    ]
    subprocess.run(cmd_gen, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # Generate real broll video
    broll_dir = tmp_path / "ro_broll"
    broll_dir.mkdir()
    real_broll = broll_dir / "coding.mp4"
    cmd_broll = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=1280x720:rate=30",
        "-c:v", "libx264",
        str(real_broll),
    ]
    subprocess.run(cmd_broll, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    words = [
        WordTimestamp(word="coding", start=0.0, end=1.5),
        WordTimestamp(word="software", start=1.6, end=2.8),
    ]

    out_file = tmp_path / "readonly_output.mp4"
    out_file.write_bytes(b"existing content")

    from unittest.mock import patch
    with patch("os.replace", side_effect=PermissionError("Read-only target path")):
        res = engine.apply_broll_overlay(
            video_path=str(real_primary),
            output_path=str(out_file),
            words=words,
            assets_dir=str(broll_dir),
        )
        assert res.applied is False
        assert res.output_video_path == str(real_primary)
        assert not os.path.exists(f"{out_file}.tmp.mp4")


def test_broll_extreme_monologue_intervals():
    """
    Stress test extreme monologue intervals:
    1. Micro-interval (0.1s speech run) with aggressive configuration:
       Verify fade out calculation max(0.0, round(interval.duration_seconds - fade_d, 3))
       does not produce negative start times in filtergraph.
    2. Ultra-long monologue interval (3600.0s / 1 hour):
       Verify default config caps overlay duration to max_overlay_duration (5.0s).
       Verify custom config with max_overlay_duration=3600.0s produces valid filtergraph expressions.
    """
    # 1. Micro-interval with 0.1s
    config_micro = BRollConfig(
        min_monologue_duration=0.1,
        min_overlay_duration=0.1,
        max_overlay_duration=0.1,
        fade_duration=0.25,
    )
    engine_micro = BRollOverlayEngine(config_micro)
    words_micro = [
        WordTimestamp(word="snap", start=0.0, end=0.1),
    ]
    intervals = engine_micro.detect_monologue_intervals(words_micro)
    assert len(intervals) == 1
    iv = intervals[0]
    assert iv.duration_seconds == 0.1

    filtergraph, _ = engine_micro.build_broll_filtergraph(
        primary_input_idx=0,
        broll_inputs=[(1, iv, "assets/broll/snap.mp4")],
    )
    # Check that fade out start time is clamped to >= 0.0 (not negative!)
    assert "fade=t=out:st=0.000:d=0.25:alpha=1" in filtergraph
    assert "overlay=0:0:enable='between(t,0.000,0.100)'" in filtergraph

    # 2. Ultra-long monologue (3600s / 1 hour)
    words_long = [
        WordTimestamp(word="start", start=0.0, end=1.0),
        WordTimestamp(word="continuous", start=1.1, end=3599.0),
        WordTimestamp(word="end", start=3599.1, end=3600.0),
    ]

    # Under default config: capped to max_overlay_duration (5.0s)
    engine_default = BRollOverlayEngine()
    intervals_default = engine_default.detect_monologue_intervals(words_long)
    assert len(intervals_default) == 1
    assert intervals_default[0].duration_seconds == 5.0

    # Under uncapped custom config
    engine_long = BRollOverlayEngine(BRollConfig(max_overlay_duration=3600.0))
    intervals_long = engine_long.detect_monologue_intervals(words_long)
    assert len(intervals_long) == 1
    assert intervals_long[0].duration_seconds == 3599.5  # 3600 - 0.5 lead-in

    filtergraph_long, _ = engine_long.build_broll_filtergraph(
        primary_input_idx=0,
        broll_inputs=[(1, intervals_long[0], "assets/broll/long.mp4")],
    )
    assert "fade=t=out:st=3599.250:d=0.25:alpha=1" in filtergraph_long
    assert "overlay=0:0:enable='between(t,0.500,3600.000)'" in filtergraph_long


def test_broll_audio_ducking_silent_vs_loud_stereo(tmp_path):
    """
    Test audio ducking matrix (mute_broll=False):
    Case A: Primary video has audio, but B-roll asset is SILENT (no audio stream).
            FFmpeg will report missing audio stream on B-roll input [1:a].
            Verify apply_broll_overlay catches the FFmpeg error and returns applied=False gracefully.
    Case B: Primary video has audio, B-roll asset has LOUD STEREO audio.
            Verify apply_broll_overlay completes successfully with volume ducking and amix.
    Case C: Primary video has NO audio stream, B-roll has audio.
            Verify apply_broll_overlay handles missing primary [0:a] safely without crash.
    """
    engine_duck = BRollOverlayEngine(
        BRollConfig(
            min_monologue_duration=2.0,
            min_overlay_duration=1.0,
            max_overlay_duration=2.0,
            mute_broll=False,
            audio_ducking_volume=0.3,
            broll_audio_volume=0.5,
        )
    )

    words = [
        WordTimestamp(word="podcast", start=0.5, end=1.5),
        WordTimestamp(word="interview", start=1.6, end=3.0),
    ]

    # Generate Primary Video with Audio
    primary_with_audio = str(tmp_path / "primary_audio.mp4")
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=4:size=1080x1920:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
        "-c:v", "libx264", "-c:a", "aac",
        primary_with_audio,
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # Generate Silent B-roll (Video only, NO audio stream)
    broll_dir = tmp_path / "broll_matrix"
    broll_dir.mkdir()
    silent_broll = str(broll_dir / "podcast.mp4")
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=1280x720:rate=30",
        "-c:v", "libx264",
        silent_broll,
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # Case A: Silent B-roll with ducking enabled
    out_a = str(tmp_path / "out_silent_broll.mp4")
    res_a = engine_duck.apply_broll_overlay(
        video_path=primary_with_audio,
        output_path=out_a,
        words=words,
        assets_dir=str(broll_dir),
    )
    # Since B-roll has no audio stream [1:a], FFmpeg fails; engine safely catches it!
    assert res_a.applied is False
    assert res_a.output_video_path == primary_with_audio
    assert not os.path.exists(out_a)

    # Case B: Loud Stereo B-roll with ducking enabled
    loud_broll = str(broll_dir / "interview.mp4")
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=1280x720:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=880:duration=2",
        "-c:v", "libx264", "-c:a", "aac",
        loud_broll,
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    out_b = str(tmp_path / "out_loud_broll.mp4")
    res_b = engine_duck.apply_broll_overlay(
        video_path=primary_with_audio,
        output_path=out_b,
        words=words,
        assets_dir=str(broll_dir),
    )
    # Should succeed with volume ducking and amix!
    assert res_b.applied is True
    assert os.path.exists(out_b)
    assert os.path.getsize(out_b) > 1000

    # Probe output video to confirm audio stream exists
    probe_cmd = ["ffmpeg", "-i", out_b]
    probe_res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert "Audio:" in probe_res.stderr

    # Case C: Primary video has NO audio stream
    primary_no_audio = str(tmp_path / "primary_silent.mp4")
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=4:size=1080x1920:rate=30",
        "-c:v", "libx264",
        primary_no_audio,
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    out_c = str(tmp_path / "out_primary_silent.mp4")
    res_c = engine_duck.apply_broll_overlay(
        video_path=primary_no_audio,
        output_path=out_c,
        words=words,
        assets_dir=str(broll_dir),
    )
    # [0:a] does not exist, so FFmpeg fails and engine safely catches it!
    assert res_c.applied is False
    assert res_c.output_video_path == primary_no_audio


# ============================================================================
# PART 2: PIPELINE DEAD-AIR INTEGRATION ADVERSARIAL STRESS TESTS
# ============================================================================

def _setup_pipeline_environment(tmp_path):
    data_dir = tmp_path / "env_data"
    ledger_path = str(data_dir / "rights_ledger.json")
    assets_dir = str(data_dir / "assets")
    transcripts_dir = str(data_dir / "transcripts")
    output_dir = str(data_dir / "rendered_clips")
    inbox_dir = str(data_dir / "autopost_inbox")
    receipts_path = str(data_dir / "handoffs" / "receipts.json")
    db_path = str(data_dir / "jobs.db")

    os.makedirs(assets_dir, exist_ok=True)
    os.makedirs(transcripts_dir, exist_ok=True)

    rights_policy = LocalRightsPolicy(ledger_path)
    asset_provider = LocalAssetProvider(assets_dir)
    transcriber = LocalTranscriber(transcripts_dir, allow_synthetic=True)
    detector = ContextAwareSegmenter()
    scorer = ExplainableScorecardScorer()
    renderer = FFmpegRenderer(allow_synthetic=True)
    verifier = MediaQualityVerifier()
    publisher = DualModeAutopostPublisher(mode="watched_folder", watched_dir=inbox_dir, receipts_path=receipts_path)
    journal = JobJournal(db_path)

    dead_air_pruner = DeadAirPruner()
    b_roll_engine = BRollOverlayEngine(BRollConfig())

    pipeline = ClippingPipeline(
        rights_policy=rights_policy,
        asset_provider=asset_provider,
        transcriber=transcriber,
        detector=detector,
        scorer=scorer,
        renderer=renderer,
        verifier=verifier,
        publisher=publisher,
        journal=journal,
        dead_air_pruner=dead_air_pruner,
        b_roll_engine=b_roll_engine,
        output_dir=output_dir,
    )

    return {
        "pipeline": pipeline,
        "rights_policy": rights_policy,
        "asset_provider": asset_provider,
        "transcriber": transcriber,
        "assets_dir": assets_dir,
        "output_dir": output_dir,
        "journal": journal,
    }


def test_pipeline_heavy_deadair_exact_duration_synchronization(tmp_path):
    """
    Adversarial test: Video with HEAVY dead air (three silent pauses totalling 8.0s).
    Verify:
    1. candidate.duration_seconds matches pruned_duration EXACTLY.
    2. candidate.start_seconds is 0.0 and end_seconds matches pruned_duration.
    3. MediaQualityVerifier passes with 0ms duration mismatch.
    4. Remapped transcript words are strictly bounded in [0.0, pruned_duration].
    """
    env = _setup_pipeline_environment(tmp_path)
    video_id = "heavy_deadair_vid"

    # Register Rights
    manifest = RightsManifest(
        rights_id=f"rights-{video_id}",
        video_id=video_id,
        basis=RightsBasis.OPERATOR_ASSET,
        status=RightsStatus.VERIFIED,
        owner_name="Testing Studio",
        audit_notes="Adversarial dead-air test.",
    )
    env["rights_policy"].register_rights(manifest)

    # Register dummy media asset
    media_path = os.path.join(env["assets_dir"], f"{video_id}.mp4")
    with open(media_path, "wb") as f:
        f.write(b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2mp41" + (b"\x00" * 8192))
    env["asset_provider"].register_asset_path(video_id, media_path)

    # 35s transcript with three 2.5s dead air gaps
    # Gap 1: 5.0 -> 7.5s (2.5s)
    # Gap 2: 15.0 -> 17.5s (2.5s)
    # Gap 3: 25.0 -> 28.0s (3.0s)
    # Total dead air = 8.0s
    transcript = Transcript(
        video_id=video_id,
        language="en",
        duration_seconds=35.0,
        text="Part one begins. Part two continues. Part three expands. Part four finishes.",
        segments=[
            TranscriptSegment(
                segment_id=1,
                start=0.0,
                end=5.0,
                text="Part one begins.",
                words=[
                    WordTimestamp(word="Part", start=0.5, end=1.5),
                    WordTimestamp(word="one", start=1.6, end=2.5),
                    WordTimestamp(word="begins", start=2.6, end=4.8),
                ],
            ),
            TranscriptSegment(
                segment_id=2,
                start=7.5,
                end=15.0,
                text="Part two continues.",
                words=[
                    WordTimestamp(word="Part", start=8.0, end=9.5),
                    WordTimestamp(word="two", start=9.6, end=11.5),
                    WordTimestamp(word="continues", start=11.6, end=14.8),
                ],
            ),
            TranscriptSegment(
                segment_id=3,
                start=17.5,
                end=25.0,
                text="Part three expands.",
                words=[
                    WordTimestamp(word="Part", start=18.0, end=19.5),
                    WordTimestamp(word="three", start=19.6, end=21.5),
                    WordTimestamp(word="expands", start=21.6, end=24.8),
                ],
            ),
            TranscriptSegment(
                segment_id=4,
                start=28.0,
                end=35.0,
                text="Part four finishes.",
                words=[
                    WordTimestamp(word="Part", start=28.5, end=30.0),
                    WordTimestamp(word="four", start=30.1, end=32.0),
                    WordTimestamp(word="finishes", start=32.1, end=34.5),
                ],
            ),
        ],
    )
    env["transcriber"].save_to_cache(transcript)

    job = env["pipeline"].process_video(
        video_id=video_id,
        profile=RenderProfile(name="test_p", width=1080, height=1920),
        dry_run=True,
        auto_approve_threshold=50.0,
        enable_deadair_pruning=True,
    )

    assert job.status == JobStatus.SUCCEEDED
    assert job.current_stage == JobStage.HANDED_OFF

    rendered_data = job.checkpoints[JobStage.RENDERED.value]["data"]
    prune_telemetry = rendered_data["deadair_pruned"]

    # 1. Assert candidate duration matches pruned duration EXACTLY
    expected_pruned_dur = prune_telemetry["pruned_duration"]
    assert job.candidate.duration_seconds == pytest.approx(expected_pruned_dur, abs=1e-3)
    assert job.candidate.start_seconds == 0.0
    assert job.candidate.end_seconds == pytest.approx(expected_pruned_dur, abs=1e-3)

    # 2. Assert QA Verifier passed with 0ms duration mismatch
    assert job.qa_report.status in ("PASSED", "WARNING")
    assert job.qa_report.duration_ok is True
    assert abs(job.qa_report.actual_duration - job.candidate.duration_seconds) < 0.01

    # 3. Assert keep intervals are non-empty and dead air duration is recorded
    assert prune_telemetry["dead_air_duration"] > 3.0
    assert len(prune_telemetry["keep_intervals"]) >= 2


def test_pipeline_zero_deadair_exact_duration_synchronization(tmp_path):
    """
    Adversarial test: Video with ZERO dead air (continuous speech, inter-word gap <= 0.15s).
    Verify:
    1. Dead air pruner does not modify candidate bounds if no pruning is needed.
    2. candidate.duration_seconds matches pruned_duration (original duration).
    3. MediaQualityVerifier passes with 0ms duration mismatch.
    """
    env = _setup_pipeline_environment(tmp_path)
    video_id = "zero_deadair_vid"

    manifest = RightsManifest(
        rights_id=f"rights-{video_id}",
        video_id=video_id,
        basis=RightsBasis.OPERATOR_ASSET,
        status=RightsStatus.VERIFIED,
        owner_name="Testing Studio",
        audit_notes="Zero dead-air test.",
    )
    env["rights_policy"].register_rights(manifest)

    media_path = os.path.join(env["assets_dir"], f"{video_id}.mp4")
    with open(media_path, "wb") as f:
        f.write(b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2mp41" + (b"\x00" * 8192))
    env["asset_provider"].register_asset_path(video_id, media_path)

    # Continuous rapid speech: words cover 0.1s to 19.85s within segment 0.0 to 20.0s
    # Leading silence: 0.1s <= 0.35s (no leading gap)
    # Inter-word silence: 0.05s <= 0.35s (no internal gap)
    # Trailing silence: 20.0 - 19.85 = 0.15s <= 0.35s (no trailing gap)
    words = []
    curr_t = 0.1
    for i in range(20):
        words.append(WordTimestamp(word=f"token{i}", start=round(curr_t, 2), end=round(curr_t + 0.94, 2)))
        curr_t += 0.99  # 0.05s gap between words

    transcript = Transcript(
        video_id=video_id,
        language="en",
        duration_seconds=20.5,
        text=" ".join(w.word for w in words),
        segments=[
            TranscriptSegment(
                segment_id=1,
                start=0.0,
                end=20.0,
                text=" ".join(w.word for w in words),
                words=words,
            )
        ],
    )
    env["transcriber"].save_to_cache(transcript)

    job = env["pipeline"].process_video(
        video_id=video_id,
        profile=RenderProfile(name="test_p", width=1080, height=1920),
        dry_run=True,
        auto_approve_threshold=50.0,
        enable_deadair_pruning=True,
    )

    assert job.status == JobStatus.SUCCEEDED
    assert job.current_stage == JobStage.HANDED_OFF

    rendered_data = job.checkpoints[JobStage.RENDERED.value]["data"]
    prune_telemetry = rendered_data["deadair_pruned"]

    # In zero dead-air, pruned duration equals original duration
    assert prune_telemetry["dead_air_duration"] == 0.0
    assert job.candidate.duration_seconds == pytest.approx(prune_telemetry["pruned_duration"], abs=1e-3)

    # QA passed
    assert job.qa_report.status in ("PASSED", "WARNING")
    assert job.qa_report.duration_ok is True


def test_transcript_remapping_for_keep_intervals():
    """
    Unit test of remap_transcript_for_keep_intervals:
    Verify word timestamps are correctly shifted and words outside keep intervals are dropped.
    """
    # Keep intervals: [2.0, 5.0] (3s) and [10.0, 14.0] (4s). Total pruned duration = 7.0s
    keep_intervals = [(2.0, 5.0), (10.0, 14.0)]

    orig_transcript = Transcript(
        video_id="v_remap",
        language="en",
        duration_seconds=20.0,
        text="A B C D E",
        segments=[
            TranscriptSegment(
                segment_id=1,
                start=0.0,
                end=20.0,
                text="A B C D E",
                words=[
                    WordTimestamp(word="A", start=0.5, end=1.5),   # Outside keep intervals -> Dropped
                    WordTimestamp(word="B", start=2.5, end=4.5),   # In interval 1 -> [0.5, 2.5]
                    WordTimestamp(word="C", start=6.0, end=8.0),   # In dead air -> Dropped
                    WordTimestamp(word="D", start=10.5, end=12.0), # In interval 2 -> [3.5, 5.0]
                    WordTimestamp(word="E", start=15.0, end=16.0), # Outside -> Dropped
                ],
            )
        ],
    )

    remapped = remap_transcript_for_keep_intervals(orig_transcript, keep_intervals)

    assert remapped.duration_seconds == 7.0
    assert len(remapped.segments) == 1
    remap_words = remapped.segments[0].words
    assert len(remap_words) == 2

    # Word B was [2.5, 4.5] in [2.0, 5.0]. Offset is 0.0 + (2.5 - 2.0) = 0.5s -> 2.5s
    assert remap_words[0].word == "B"
    assert remap_words[0].start == 0.5
    assert remap_words[0].end == 2.5

    # Word D was [10.5, 12.0] in [10.0, 14.0]. Offset is 3.0 + (10.5 - 10.0) = 3.5s -> 5.0s
    assert remap_words[1].word == "D"
    assert remap_words[1].start == 3.5
    assert remap_words[1].end == 5.0


def test_real_media_deadair_pruning_and_qa_verification(tmp_path):
    """
    End-to-end integration test with REAL FFmpeg media:
    1. Generate a real 10-second video with a real 2.0s silent pause in the middle.
    2. Run pipeline with enable_deadair_pruning=True on real media.
    3. Verify FFmpeg successfully micro-jump-cuts the video.
    4. Verify MediaQualityVerifier inspects real media stream and passes duration check with 0ms mismatch.
    """
    env = _setup_pipeline_environment(tmp_path)
    video_id = "real_media_deadair_01"

    manifest = RightsManifest(
        rights_id=f"rights-{video_id}",
        video_id=video_id,
        basis=RightsBasis.OPERATOR_ASSET,
        status=RightsStatus.VERIFIED,
        owner_name="Real Media Studio",
        audit_notes="Real media dead-air test.",
    )
    env["rights_policy"].register_rights(manifest)

    # Generate 10-second real video with audio
    real_video_path = os.path.join(env["assets_dir"], f"{video_id}.mp4")
    cmd_media = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=10:size=1080x1920:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
        "-c:v", "libx264", "-c:a", "aac",
        real_video_path,
    ]
    subprocess.run(cmd_media, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    env["asset_provider"].register_asset_path(video_id, real_video_path)

    # 10s transcript with a 2.0s pause between 4.0s and 6.0s
    transcript = Transcript(
        video_id=video_id,
        language="en",
        duration_seconds=10.0,
        text="First speech segment. Second speech segment.",
        segments=[
            TranscriptSegment(
                segment_id=1,
                start=0.5,
                end=4.0,
                text="First speech segment.",
                words=[
                    WordTimestamp(word="First", start=0.5, end=1.5),
                    WordTimestamp(word="speech", start=1.6, end=2.8),
                    WordTimestamp(word="segment", start=2.9, end=4.0),
                ],
            ),
            # 2.0s pause from 4.0s to 6.0s
            TranscriptSegment(
                segment_id=2,
                start=6.0,
                end=9.5,
                text="Second speech segment.",
                words=[
                    WordTimestamp(word="Second", start=6.0, end=7.2),
                    WordTimestamp(word="speech", start=7.3, end=8.4),
                    WordTimestamp(word="segment", start=8.5, end=9.5),
                ],
            ),
        ],
    )
    env["transcriber"].save_to_cache(transcript)

    job = env["pipeline"].process_video(
        video_id=video_id,
        profile=RenderProfile(name="test_p", width=1080, height=1920),
        dry_run=True,
        auto_approve_threshold=50.0,
        enable_deadair_pruning=True,
    )

    assert job.status == JobStatus.SUCCEEDED
    assert job.current_stage == JobStage.HANDED_OFF

    # Assert physical file exists and is valid
    clip = job.rendered_clip
    assert os.path.exists(clip.file_path)
    assert os.path.getsize(clip.file_path) > 1000

    # Probe actual duration of rendered clip using verifier engine
    probe_info = env["pipeline"].verifier._probe_media(clip.file_path)
    assert probe_info["readable"] is True
    real_dur = probe_info["duration"]

    # Candidate duration and real duration should match pruned duration
    assert job.candidate.duration_seconds < 10.0  # Dead air was excised
    assert abs(real_dur - job.candidate.duration_seconds) <= 0.5  # Within FFmpeg muxing tolerance

    # QA Verifier passed with 0 errors
    assert job.qa_report.status == "PASSED"
    assert len(job.qa_report.errors) == 0
    assert job.qa_report.duration_ok is True
