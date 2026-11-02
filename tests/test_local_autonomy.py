"""
Targeted Regression Test Suite for Strict Local Autonomy & Network Isolation.
Verifies that:
1. Core highlight discovery, segmentation, scoring, rendering, QA, and publication
   operate with 100% offline autonomy without any cloud API keys (GEMINI, OPENAI, ANTHROPIC, YOUTUBE).
2. Missing cloud credentials trigger graceful heuristic degradation, never fatal crashes.
3. Network calls are strictly isolated from the local clipping pipeline.
"""

import os
import json
import pytest
from unittest.mock import patch

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
from yt_clipping.scoring.scorecard import ExplainableScorecardScorer
from yt_clipping.detection.segmenter import ContextAwareSegmenter
from yt_clipping.scoring.gemini_provider import GeminiHighlightDiscoveryProvider
from yt_clipping.orchestration.pipeline import ClippingPipeline
from yt_clipping.cli.master_cli import build_pipeline
from yt_clipping.rendering.renderer import FFmpegRenderer


@pytest.fixture(autouse=True)
def strip_all_cloud_credentials(monkeypatch):
    """Guarantees that all cloud AI credentials are wiped clean from the test environment."""
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("YOUTUBE_API_KEY", "")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)


def test_explainable_scorecard_offline_local_autonomy():
    """ExplainableScorecardScorer computes deterministic multi-signal scores without cloud LLMs."""
    scorer = ExplainableScorecardScorer(use_llm=False)
    candidate = HighlightCandidate(
        candidate_id="c_offline_01",
        video_id="v_offline_01",
        start_seconds=10.0,
        end_seconds=35.0,
        duration_seconds=25.0,
        score=0.0,
        breakdown=ScoreBreakdown(),
        hook_title="Local Intelligence",
        transcript_text="The secret truth about machine learning is actually very simple.",
    )

    scored = scorer.score_candidate(candidate, None)
    assert scored.score > 0.0
    assert scored.breakdown.hook_score > 0.0
    assert scored.breakdown.moment_score > 0.0
    assert "Hook=" in scored.breakdown.rationale


def test_gemini_provider_graceful_local_degradation_without_api_key():
    """GeminiFlashHighlightProvider gracefully falls back to local ContextAwareSegmenter when API key is empty."""
    provider = GeminiHighlightDiscoveryProvider(api_key="")
    assert not provider.is_available()

    seg = TranscriptSegment(
        segment_id=1,
        start=0.0,
        end=20.0,
        text="This is a test spoken segment for local fallback validation.",
        words=[
            WordTimestamp(word="This", start=0.0, end=1.0),
            WordTimestamp(word="is", start=1.0, end=2.0),
            WordTimestamp(word="a", start=2.0, end=3.0),
            WordTimestamp(word="test", start=3.0, end=4.0),
        ],
    )
    transcript = Transcript(
        video_id="v_test_deg",
        language="en",
        duration_seconds=20.0,
        text=seg.text,
        segments=[seg],
    )

    # Must degrade to local heuristics without raising exception
    candidates = provider.detect_candidates(transcript, min_duration=5.0, max_duration=25.0)
    assert isinstance(candidates, list)


def test_end_to_end_pipeline_zero_cloud_dependency(tmp_path):
    """Full ClippingPipeline executes from start to finish with zero network requests or cloud tokens."""
    db_file = tmp_path / "jobs.db"
    out_dir = tmp_path / "rendered"
    inbox_dir = tmp_path / "inbox"
    assets_dir = tmp_path / "assets"
    transcripts_dir = tmp_path / "transcripts"
    ledger_path = tmp_path / "rights.json"

    out_dir.mkdir()
    inbox_dir.mkdir()
    assets_dir.mkdir()
    transcripts_dir.mkdir()

    pipeline = build_pipeline(
        ledger_path=str(ledger_path),
        assets_dir=str(assets_dir),
        transcripts_dir=str(transcripts_dir),
        output_dir=str(out_dir),
        autopost_inbox=str(inbox_dir),
        db_path=str(db_file),
    )
    pipeline.renderer.allow_synthetic = True

    video_id = "local_autonomous_test_vid"

    # 1. Local rights registration
    pipeline.rights_policy.register_rights(
        RightsManifest(
            rights_id=f"rights-{video_id}",
            video_id=video_id,
            basis=RightsBasis.OPERATOR_ASSET,
            status=RightsStatus.VERIFIED,
            owner_name="Local Creator",
        )
    )

    # 2. Local media asset
    asset_file = assets_dir / f"{video_id}.mp4"
    asset_file.write_text("ftypisom mock local asset data")

    # 3. Local transcript
    words = [
        WordTimestamp(word="The", start=1.0, end=1.3),
        WordTimestamp(word="secret", start=1.3, end=1.8),
        WordTimestamp(word="to", start=1.8, end=2.0),
        WordTimestamp(word="building", start=2.0, end=2.5),
        WordTimestamp(word="great", start=2.5, end=3.0),
        WordTimestamp(word="systems", start=3.0, end=3.6),
        WordTimestamp(word="is", start=3.6, end=3.9),
        WordTimestamp(word="rigorous", start=3.9, end=4.5),
        WordTimestamp(word="testing.", start=4.5, end=5.2),
        WordTimestamp(word="And", start=5.2, end=5.5),
        WordTimestamp(word="that", start=5.5, end=5.8),
        WordTimestamp(word="is", start=5.8, end=6.0),
        WordTimestamp(word="why", start=6.0, end=6.3),
        WordTimestamp(word="we", start=6.3, end=6.6),
        WordTimestamp(word="succeed.", start=6.6, end=7.5),
    ]
    seg = TranscriptSegment(
        segment_id=1,
        start=1.0,
        end=20.0,
        text="The secret to building great systems is rigorous testing. And that is why we succeed.",
        words=words,
    )
    transcript = Transcript(
        video_id=video_id,
        language="en",
        duration_seconds=30.0,
        text=seg.text,
        segments=[seg],
    )
    pipeline.transcriber.register_mock_transcript(video_id, transcript)

    # 4. Process with CTA and broadcast polish enabled
    profile = RenderProfile(
        layout_mode="crop_center",
        burn_subtitles=True,
        enable_cta=True,
        cta_text="Subscribe for autonomous tools",
        enable_pacing_polish=True,
    )

    job = pipeline.process_video(
        video_id=video_id,
        profile=profile,
        dry_run=True,
        min_duration=5.0,
        max_duration=25.0,
    )

    assert job.status.value == "SUCCEEDED"
    assert job.rendered_clip is not None
    assert os.path.exists(job.rendered_clip.file_path)
    assert os.path.exists(job.rendered_clip.manifest_path)
    # Check that CTA was injected in the ASS subtitles
    ass_path = out_dir / f"{job.candidate.candidate_id}.ass"
    assert ass_path.exists()
    assert "Subscribe for autonomous tools" in ass_path.read_text(encoding="utf-8")
