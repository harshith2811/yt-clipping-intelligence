"""
Integration tests for Pipeline Dead-Air Pruning and Automated B-Roll Overlay Engine.
Validates:
1. Dead-air pruning enabled via enable_deadair_pruning=True.
2. Backwards compatibility when enable_deadair_pruning=False.
3. PipelineCoordinator alias compatibility.
4. B-roll overlay enabled via enable_broll=True.
5. Combined dead-air pruning and B-roll overlay sequential execution.
"""

import os
import pytest
from src.yt_clipping.contracts.models import (
    RightsManifest,
    RightsBasis,
    RightsStatus,
    RenderProfile,
    JobStage,
    JobStatus,
    Transcript,
    TranscriptSegment,
    WordTimestamp,
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
from src.yt_clipping.orchestration.pipeline import ClippingPipeline, PipelineCoordinator
from src.yt_clipping.detection.deadair import DeadAirPruner
from src.yt_clipping.rendering.b_roll import BRollOverlayEngine, BRollConfig


def _setup_pipeline_fixture(tmp_path):
    data_dir = tmp_path / "data"
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
        "transcripts_dir": transcripts_dir,
        "output_dir": output_dir,
        "journal": journal,
    }


def _create_authorized_asset_with_transcript(fixtures, video_id: str, dead_air_pause: float = 2.0):
    # 1. Register Rights
    manifest = RightsManifest(
        rights_id=f"rights-{video_id}",
        video_id=video_id,
        basis=RightsBasis.OPERATOR_ASSET,
        status=RightsStatus.VERIFIED,
        owner_name="Operator Archive",
        audit_notes="Fixture test media.",
    )
    fixtures["rights_policy"].register_rights(manifest)

    # 2. Register Mock Media
    media_path = os.path.join(fixtures["assets_dir"], f"{video_id}.mp4")
    with open(media_path, "wb") as f:
        f.write(b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2mp41" + (b"\x00" * 8192))
    fixtures["asset_provider"].register_asset_path(video_id, media_path)

    # 3. Create realistic 60s transcript with a distinct dead-air pause
    # Segment 1: 0.0 -> 10.0s
    # Segment 2: 10.0 -> 20.0s (continuous monologue)
    # Pause of `dead_air_pause` seconds between 20.0s and 20.0s + dead_air_pause
    # Segment 3: (20.0 + dead_air_pause) -> 45.0s
    pause_end = 20.0 + dead_air_pause
    words_seg2 = [
        WordTimestamp(word="Artificial", start=10.5, end=11.5),
        WordTimestamp(word="intelligence", start=11.6, end=13.0),
        WordTimestamp(word="deep", start=13.1, end=14.5),
        WordTimestamp(word="learning", start=14.6, end=16.0),
        WordTimestamp(word="architectures", start=16.1, end=18.0),
        WordTimestamp(word="transform", start=18.1, end=19.8),
    ]

    words_seg3 = [
        WordTimestamp(word="Modern", start=pause_end + 0.5, end=pause_end + 1.5),
        WordTimestamp(word="neural", start=pause_end + 1.6, end=pause_end + 3.0),
        WordTimestamp(word="models", start=pause_end + 3.1, end=pause_end + 4.5),
        WordTimestamp(word="revolutionize", start=pause_end + 4.6, end=pause_end + 6.0),
        WordTimestamp(word="creative", start=pause_end + 6.1, end=pause_end + 7.5),
        WordTimestamp(word="workflows", start=pause_end + 7.6, end=pause_end + 9.0),
    ]

    transcript = Transcript(
        video_id=video_id,
        language="en",
        duration_seconds=50.0,
        text="Welcome to the overview. Artificial intelligence deep learning architectures transform. Modern neural models revolutionize creative workflows.",
        segments=[
            TranscriptSegment(
                segment_id=1,
                start=0.0,
                end=9.5,
                text="Welcome to the overview.",
                words=[
                    WordTimestamp(word="Welcome", start=0.5, end=2.0),
                    WordTimestamp(word="to", start=2.1, end=3.0),
                    WordTimestamp(word="the", start=3.1, end=4.0),
                    WordTimestamp(word="overview", start=4.1, end=6.0),
                ],
            ),
            TranscriptSegment(
                segment_id=2,
                start=10.0,
                end=20.0,
                text="Artificial intelligence deep learning architectures transform.",
                words=words_seg2,
            ),
            TranscriptSegment(
                segment_id=3,
                start=pause_end,
                end=pause_end + 15.0,
                text="Modern neural models revolutionize creative workflows.",
                words=words_seg3,
            ),
        ],
    )
    fixtures["transcriber"].save_to_cache(transcript)
    return media_path, transcript


def test_pipeline_deadair_pruning_enabled(tmp_path):
    """
    Execute full pipeline with enable_deadair_pruning=True on a video with 2.0s dead air.
    Verify DeadAirPruner executes, candidate duration is updated, and QA passes.
    """
    fixtures = _setup_pipeline_fixture(tmp_path)
    video_id = "test_vid_deadair_01"
    _create_authorized_asset_with_transcript(fixtures, video_id, dead_air_pause=2.0)

    job = fixtures["pipeline"].process_video(
        video_id=video_id,
        profile=RenderProfile(name="test_profile", width=1080, height=1920),
        dry_run=True,
        auto_approve_threshold=50.0,
        enable_deadair_pruning=True,
    )

    assert job.status == JobStatus.SUCCEEDED
    assert job.current_stage == JobStage.HANDED_OFF

    # Check that dead-air telemetry was recorded in RENDERED stage
    rendered_cp = job.checkpoints.get(JobStage.RENDERED.value, {})
    data = rendered_cp.get("data", {})
    assert "deadair_pruned" in data
    pruned_data = data["deadair_pruned"]
    assert pruned_data["dead_air_duration"] > 0.0

    # Candidate duration updated to match pruned duration
    assert job.candidate is not None
    assert abs(job.candidate.duration_seconds - pruned_data["pruned_duration"]) < 1e-2

    # QA passed
    assert job.qa_report is not None
    assert job.qa_report.status in ["PASSED", "WARNING"]


def test_pipeline_deadair_pruning_disabled_by_default(tmp_path):
    """
    Verify default enable_deadair_pruning=False preserves backwards compatibility
    without dead-air pruning checkpoint modification.
    """
    fixtures = _setup_pipeline_fixture(tmp_path)
    video_id = "test_vid_default_01"
    _create_authorized_asset_with_transcript(fixtures, video_id, dead_air_pause=2.0)

    job = fixtures["pipeline"].process_video(
        video_id=video_id,
        profile=RenderProfile(name="test_profile", width=1080, height=1920),
        dry_run=True,
        auto_approve_threshold=50.0,
        enable_deadair_pruning=False,
    )

    assert job.status == JobStatus.SUCCEEDED
    assert job.current_stage == JobStage.HANDED_OFF

    rendered_cp = job.checkpoints.get(JobStage.RENDERED.value, {})
    data = rendered_cp.get("data", {})
    assert "deadair_pruned" not in data


def test_pipeline_coordinator_alias_compatibility():
    """
    Verify PipelineCoordinator can be imported and is an alias for ClippingPipeline.
    """
    assert PipelineCoordinator is ClippingPipeline


def test_pipeline_broll_overlay_enabled(tmp_path):
    """
    Execute pipeline with enable_broll=True and mock B-roll folder.
    Verify B-roll overlay is evaluated and recorded in checkpoint.
    """
    fixtures = _setup_pipeline_fixture(tmp_path)
    video_id = "test_vid_broll_01"
    _create_authorized_asset_with_transcript(fixtures, video_id, dead_air_pause=0.2)

    # Create mock B-roll folder with a default stock clip
    broll_dir = tmp_path / "stock_assets"
    broll_dir.mkdir(parents=True, exist_ok=True)
    stock_clip = broll_dir / "default.mp4"
    stock_clip.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 1024)

    job = fixtures["pipeline"].process_video(
        video_id=video_id,
        profile=RenderProfile(name="test_profile", width=1080, height=1920),
        dry_run=True,
        auto_approve_threshold=50.0,
        enable_broll=True,
        broll_assets_dir=str(broll_dir),
    )

    assert job.status == JobStatus.SUCCEEDED
    assert job.current_stage == JobStage.HANDED_OFF

    rendered_cp = job.checkpoints.get(JobStage.RENDERED.value, {})
    data = rendered_cp.get("data", {})
    assert "broll_overlay" in data


def test_pipeline_deadair_plus_broll_combined(tmp_path):
    """
    Execute pipeline with both enable_deadair_pruning=True and enable_broll=True.
    Verify both stages execute sequentially and record their telemetry.
    """
    fixtures = _setup_pipeline_fixture(tmp_path)
    video_id = "test_vid_combo_01"
    _create_authorized_asset_with_transcript(fixtures, video_id, dead_air_pause=2.5)

    broll_dir = tmp_path / "stock_assets_combo"
    broll_dir.mkdir(parents=True, exist_ok=True)
    stock_clip = broll_dir / "stock_ai.mp4"
    stock_clip.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 1024)

    job = fixtures["pipeline"].process_video(
        video_id=video_id,
        profile=RenderProfile(name="test_profile", width=1080, height=1920),
        dry_run=True,
        auto_approve_threshold=50.0,
        enable_deadair_pruning=True,
        enable_broll=True,
        broll_assets_dir=str(broll_dir),
    )

    assert job.status == JobStatus.SUCCEEDED
    assert job.current_stage == JobStage.HANDED_OFF

    rendered_cp = job.checkpoints.get(JobStage.RENDERED.value, {})
    data = rendered_cp.get("data", {})
    assert "deadair_pruned" in data
    assert "broll_overlay" in data
    assert job.qa_report.status in ["PASSED", "WARNING"]
