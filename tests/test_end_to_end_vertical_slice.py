"""
End-to-End Vertical Slice Integration Test.
Proves that an authorized video input flows from RightsGate through Transcription,
Candidate Selection, Scoring, Rendering, QA Verification, and Autopost Handoff.
"""

import pytest
import os
import json
from src.yt_clipping.contracts.models import (
    RightsManifest,
    RightsBasis,
    RightsStatus,
    RenderProfile,
    JobStage,
    JobStatus,
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
from src.yt_clipping.orchestration.pipeline import ClippingPipeline


def test_complete_end_to_end_vertical_slice(tmp_path):
    # Setup test workspace directories
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

    # 1. Initialize core services
    rights_policy = LocalRightsPolicy(ledger_path)
    asset_provider = LocalAssetProvider(assets_dir)
    transcriber = LocalTranscriber(transcripts_dir)
    detector = ContextAwareSegmenter()
    scorer = ExplainableScorecardScorer()
    renderer = FFmpegRenderer()
    verifier = MediaQualityVerifier()
    publisher = DualModeAutopostPublisher(mode="watched_folder", watched_dir=inbox_dir, receipts_path=receipts_path)
    journal = JobJournal(db_path)

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
        output_dir=output_dir,
    )

    # 2. Register authorized video fixture in RightsGate
    video_id = "authorized_slice_fixture_01"
    manifest = RightsManifest(
        rights_id="rights-fixture-01",
        video_id=video_id,
        basis=RightsBasis.OPERATOR_ASSET,
        status=RightsStatus.VERIFIED,
        owner_name="Operator Internal Archive",
        audit_notes="Synthetic fixture approved for automated testing.",
    )
    rights_policy.register_rights(manifest)

    # 3. Supply synthetic source media asset
    fixture_media_path = os.path.join(assets_dir, f"{video_id}.mp4")
    # Write valid MP4 header
    with open(fixture_media_path, "wb") as f:
        f.write(b'\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2mp41' + (b'\x00' * 8192))
    asset_provider.register_asset_path(video_id, fixture_media_path)

    # 4. Execute Full Pipeline (Dry-run handoff by default)
    profile = RenderProfile(name="test_vertical_9_16", width=1080, height=1920)
    job = pipeline.process_video(
        video_id=video_id,
        profile=profile,
        dry_run=True,
        auto_approve_threshold=60.0,
    )

    # 5. Verify all stages completed successfully
    assert job.status == JobStatus.SUCCEEDED, f"Job failed: status={job.status}, stage={job.current_stage}, error={job.error_message}, checkpoints={job.checkpoints}"
    assert job.current_stage == JobStage.HANDED_OFF

    # Checkpoints recorded in SQLite journal
    assert JobStage.RIGHTS_CHECKED.value in job.checkpoints
    assert JobStage.ASSET_INGESTED.value in job.checkpoints
    assert JobStage.TRANSCRIBED.value in job.checkpoints
    assert JobStage.SEGMENTED.value in job.checkpoints
    assert JobStage.SCORED.value in job.checkpoints
    assert JobStage.REVIEWED.value in job.checkpoints
    assert JobStage.RENDERED.value in job.checkpoints
    assert JobStage.QA_VERIFIED.value in job.checkpoints
    assert JobStage.HANDED_OFF.value in job.checkpoints

    # Highlight Candidate verified
    assert job.candidate is not None
    assert job.candidate.score > 0.0
    assert job.candidate.approval_status == "APPROVED"
    assert job.candidate.duration_seconds >= 15.0

    # Rendered Clip verified
    assert job.rendered_clip is not None
    assert os.path.exists(job.rendered_clip.file_path)
    assert os.path.exists(job.rendered_clip.manifest_path)
    assert len(job.rendered_clip.file_hash) == 64

    # QA Report verified
    assert job.qa_report is not None
    assert job.qa_report.status in ["PASSED", "WARNING"]

    # Autopost Handoff Receipt verified
    assert job.handoff_receipt is not None
    assert job.handoff_receipt.status == "DRY_RUN_SIMULATED"
    assert len(job.handoff_receipt.idempotency_key) == 64

    # Check journal persistence
    stored_job = journal.get_job(job.job_id)
    assert stored_job is not None
    assert stored_job.status == JobStatus.SUCCEEDED
