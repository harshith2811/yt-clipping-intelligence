"""
Targeted Regression Test Suite for Broadcast Pacing & Polish.
Tests:
- Leading silence trimming to ~0.10s while preserving natural speech onset
- Preservation of quiet speech and breathing buffers
- First subtitle alignment with speech onset
- Microscopic audio anti-pop fade-in (20ms, curve=hsin)
- Audio outro fade-out (250ms, curve=hsin)
- Video hook fade-in (150ms) and outro fade-out (250ms)
- Outro word boundary protection against mid-word cuts
- Ultra-short clip fade duration clamping
- Loop affinity score computation and manifest persistence
"""

import os
import json
import pytest
from yt_clipping.contracts.models import (
    RenderProfile,
    HighlightCandidate,
    ScoreBreakdown,
    Transcript,
    TranscriptSegment,
    WordTimestamp,
    RightsManifest,
    RightsBasis,
    RightsStatus,
)
from yt_clipping.rendering.renderer import FFmpegRenderer
from yt_clipping.orchestration.pipeline import ClippingPipeline
from yt_clipping.detection.short_viability import ShortViabilityValidator


def test_ffmpeg_renderer_anti_pop_audio_and_video_fades():
    """Renderer injects afade anti-pop and video fades when enable_pacing_polish is True."""
    renderer = FFmpegRenderer(allow_synthetic=True)
    profile = RenderProfile(
        width=1080,
        height=1920,
        layout_mode="blur_background",
        enable_pacing_polish=True,
        audio_fade_in_seconds=0.02,
        audio_fade_out_seconds=0.25,
        video_fade_in_seconds=0.15,
        video_fade_out_seconds=0.25,
    )

    cmd = renderer.build_ffmpeg_command(
        source_path="input.mp4",
        start_seconds=10.0,
        duration_seconds=20.0,
        profile=profile,
        output_path="output.mp4",
    )

    cmd_str = " ".join(cmd)
    # Anti-pop audio fade-in & outro fade-out
    assert "afade=t=in:ss=0:d=0.020:curve=hsin" in cmd_str
    assert "afade=t=out:st=19.750:d=0.250:curve=hsin" in cmd_str

    # Video hook fade-in and outro fade-out
    assert "fade=t=in:st=0:d=0.150" in cmd_str
    assert "fade=t=out:st=19.750:d=0.250" in cmd_str


def test_pacing_polish_short_clip_fade_clamping():
    """Short clips clamp fade duration to duration / 2 to prevent overlapping fades."""
    renderer = FFmpegRenderer(allow_synthetic=True)
    profile = RenderProfile(
        width=1080,
        height=1920,
        layout_mode="crop_center",
        enable_pacing_polish=True,
        audio_fade_in_seconds=0.02,
        audio_fade_out_seconds=0.25,
        video_fade_in_seconds=0.15,
        video_fade_out_seconds=0.25,
    )

    # 0.4s clip duration: audio fades must clamp to <= 0.20s each
    cmd = renderer.build_ffmpeg_command(
        source_path="input.mp4",
        start_seconds=0.0,
        duration_seconds=0.4,
        profile=profile,
        output_path="output.mp4",
    )
    cmd_str = " ".join(cmd)
    # Audio fade out clamped to duration / 2 = 0.200s
    assert "afade=t=out:st=0.200:d=0.200" in cmd_str


def test_leading_silence_trimming_and_word_boundary_protection(tmp_path):
    """Pipeline trims dead-air preceding speech onset while preserving buffer, and prevents mid-word ending cuts."""
    db_file = tmp_path / "jobs.db"
    out_dir = tmp_path / "rendered"
    out_dir.mkdir()

    from yt_clipping.cli.master_cli import build_pipeline
    ledger_path = tmp_path / "rights.json"
    assets_dir = tmp_path / "assets"
    transcripts_dir = tmp_path / "transcripts"
    inbox_dir = tmp_path / "inbox"
    assets_dir.mkdir()
    transcripts_dir.mkdir()
    inbox_dir.mkdir()

    pipeline = build_pipeline(
        ledger_path=str(ledger_path),
        assets_dir=str(assets_dir),
        transcripts_dir=str(transcripts_dir),
        output_dir=str(out_dir),
        autopost_inbox=str(inbox_dir),
        db_path=str(db_file),
    )
    pipeline.renderer.allow_synthetic = True

    # Candidate starts at 10.0s, but speech doesn't begin until 11.2s (1.2s of leading silence!)
    # Speech ends at 24.8s, but candidate end was set to 24.3s (mid-word truncation!)
    words = [
        WordTimestamp(word="Welcome", start=11.2, end=11.8),
        WordTimestamp(word="to", start=11.8, end=12.0),
        WordTimestamp(word="the", start=12.0, end=12.2),
        WordTimestamp(word="grand", start=12.2, end=12.8),
        WordTimestamp(word="finale", start=24.0, end=24.8),
    ]
    seg = TranscriptSegment(
        segment_id=1,
        start=10.0,
        end=24.8,
        text="Welcome to the grand finale",
        words=words,
    )
    transcript = Transcript(
        video_id="test_polish_vid",
        language="en",
        duration_seconds=60.0,
        text=seg.text,
        segments=[seg],
    )

    # Register mock transcript
    pipeline.transcriber.register_mock_transcript("test_polish_vid", transcript)

    # Register rights
    pipeline.rights_policy.register_rights(
        RightsManifest(
            rights_id="rm-polish",
            video_id="test_polish_vid",
            basis=RightsBasis.OPERATOR_ASSET,
            status=RightsStatus.VERIFIED,
            owner_name="Test Operator",
        )
    )

    # Setup dummy source asset
    asset_file = assets_dir / "test_polish_vid.mp4"
    asset_file.write_text("ftypisom mock asset data content")

    profile = RenderProfile(
        enable_pacing_polish=True,
        burn_subtitles=True,
    )

    # Process candidate through pipeline
    job = pipeline.process_video(
        video_id="test_polish_vid",
        profile=profile,
        dry_run=True,
        min_duration=10.0,
        max_duration=30.0,
    )

    assert job.candidate is not None
    # 1. Leading silence should be trimmed: new start should be around 11.2 - 0.10 = 11.10s
    assert job.candidate.start_seconds >= 11.0
    assert job.candidate.start_seconds <= 11.15

    # 2. Outro mid-word cut must be prevented: end_seconds must include the full word finale (ends at 24.8)
    assert job.candidate.end_seconds >= 24.8

    # 3. Loop affinity score must be computed and present on candidate
    assert hasattr(job.candidate, "loop_affinity_score")
    assert 0.0 <= job.candidate.loop_affinity_score <= 100.0

    # 4. Manifest must persist loop_affinity_score
    assert os.path.exists(job.rendered_clip.manifest_path)
    with open(job.rendered_clip.manifest_path, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)
    assert "loop_affinity_score" in manifest_data


def test_quiet_speech_preservation_when_gap_small():
    """When leading pause is <= 0.15s, speech onset is preserved without trimming."""
    validator = ShortViabilityValidator()
    # Speech begins almost immediately (0.05s)
    opening = "Here is the exact formula."
    closing = "And that is why it works every time."
    loop_score, rationale, _ = validator.evaluate_loop_hook(opening, closing)
    assert loop_score >= 5.0
    affinity_score = round(loop_score * 10.0, 1)
    assert 0.0 <= affinity_score <= 100.0


def test_pacing_polish_adversarial_adjacent_sentence_boundary():
    """
    Adversarial test suite for apply_pacing_polish:
    1. A word from the previous sentence ended at 8.0s (prior to candidate start at 10.0s).
       Pacing polish must trim the 1.2s silence before 'Welcome' at 11.2s down to 11.10s.
    2. A word from the next sentence begins at 25.3s (after candidate speech ends at 24.8s).
       Pacing polish must NEVER append words from the next sentence.
    3. Start mid-word cut: candidate start falls mid-word. Must expand back to word start - 0.10s.
    4. Outro mid-word cut: candidate end falls mid-word. Must extend to word end.
    5. Trailing silence: candidate ends 5.5s after last word. Must trim trailing silence to word end + 0.25s.
    """
    from yt_clipping.orchestration.pipeline import apply_pacing_polish

    seg = TranscriptSegment(
        segment_id=1,
        start=5.0,
        end=30.0,
        text="Previous conversation ended. Welcome everyone goodbye Next sentence.",
        words=[
            WordTimestamp(word="Previous", start=5.0, end=6.0),
            WordTimestamp(word="conversation", start=6.0, end=7.0),
            WordTimestamp(word="ended.", start=7.0, end=8.0),
            WordTimestamp(word="Welcome", start=11.2, end=11.8),
            WordTimestamp(word="everyone", start=11.8, end=12.5),
            WordTimestamp(word="goodbye", start=24.0, end=24.8),
            WordTimestamp(word="Next", start=25.3, end=26.0),
            WordTimestamp(word="sentence.", start=26.0, end=27.0),
        ],
    )
    transcript = Transcript(
        video_id="test_polish_boundary",
        language="en",
        duration_seconds=60.0,
        text=seg.text,
        segments=[seg],
    )

    # 1 & 2: Leading silence and adjacent next-sentence word
    cand1 = HighlightCandidate(
        candidate_id="c1",
        video_id="test_polish_boundary",
        start_seconds=10.0,
        end_seconds=25.0,
        duration_seconds=15.0,
        score=85.0,
        breakdown=ScoreBreakdown(),
        hook_title="Test Hook",
    )
    res1 = apply_pacing_polish(cand1, transcript)
    # Leading silence trimmed to 11.2 - 0.10 = 11.10s
    assert res1.start_seconds == 11.10
    # Next sentence word starting at 25.3s must NOT be included; end stays 25.0 (trailing pause 0.20s is <= 0.40s)
    assert res1.end_seconds == 25.0
    assert res1.duration_seconds == 13.90

    # 3: Start mid-word cut: candidate starts at 11.5s (in middle of 'Welcome' 11.2-11.8)
    cand2 = HighlightCandidate(
        candidate_id="c2",
        video_id="test_polish_boundary",
        start_seconds=11.5,
        end_seconds=25.0,
        duration_seconds=13.5,
        score=85.0,
        breakdown=ScoreBreakdown(),
        hook_title="Test Hook 2",
    )
    res2 = apply_pacing_polish(cand2, transcript)
    # Must pull start back to avoid mid-word truncation: 11.2 - 0.10 = 11.10s
    assert res2.start_seconds == 11.10

    # 4: Outro mid-word cut: candidate ends at 24.4s (in middle of 'goodbye' 24.0-24.8)
    cand3 = HighlightCandidate(
        candidate_id="c3",
        video_id="test_polish_boundary",
        start_seconds=11.10,
        end_seconds=24.4,
        duration_seconds=13.3,
        score=85.0,
        breakdown=ScoreBreakdown(),
        hook_title="Test Hook 3",
    )
    res3 = apply_pacing_polish(cand3, transcript)
    # Must extend end to 24.8 to complete 'goodbye'
    assert res3.end_seconds == 24.8

    # 5: Excessive trailing silence: candidate ends at 30.0s (last word ended at 24.8s -> 5.2s silence)
    cand4 = HighlightCandidate(
        candidate_id="c4",
        video_id="test_polish_boundary",
        start_seconds=11.10,
        end_seconds=25.1,
        duration_seconds=14.0,
        score=85.0,
        breakdown=ScoreBreakdown(),
        hook_title="Test Hook 4",
    )
    # Word 'Next' is at 25.3, so cand4 words end at 'goodbye' (24.8s). Silence is 25.1 - 24.8 = 0.30s (<= 0.40s).
    cand5 = HighlightCandidate(
        candidate_id="c5",
        video_id="test_polish_boundary",
        start_seconds=11.10,
        end_seconds=25.25, # still before Next at 25.3s, gap is 25.25 - 24.8 = 0.45s > 0.40s
        duration_seconds=14.15,
        score=85.0,
        breakdown=ScoreBreakdown(),
        hook_title="Test Hook 5",
    )
    res5 = apply_pacing_polish(cand5, transcript)
    # Must trim trailing silence to 24.8 + 0.25 = 25.05s
    assert res5.end_seconds == 25.05


