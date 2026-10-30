"""
Tests for downstream autopost adapter: idempotency, dry-run safety, and policy blocking.
"""

import pytest
import os
import json
from src.yt_clipping.contracts.models import (
    RenderedClip,
    HighlightCandidate,
    ScoreBreakdown,
    RightsManifest,
    RightsBasis,
    RightsStatus,
    QAReport,
)
from src.yt_clipping.publisher.adapter import DualModeAutopostPublisher


def test_publisher_idempotency_and_dry_run(tmp_path):
    inbox = str(tmp_path / "inbox")
    receipts = str(tmp_path / "receipts.json")
    publisher = DualModeAutopostPublisher(mode="watched_folder", watched_dir=inbox, receipts_path=receipts)

    cand = HighlightCandidate(
        candidate_id="cand1",
        video_id="vid_autopost_1",
        start_seconds=10.0,
        end_seconds=40.0,
        duration_seconds=30.0,
        score=88.0,
        breakdown=ScoreBreakdown(),
        hook_title="Viral Autopost Clip",
    )
    rights = RightsManifest(
        rights_id="r1",
        video_id="vid_autopost_1",
        basis=RightsBasis.OWNED,
        status=RightsStatus.VERIFIED,
        owner_name="Owner",
    )
    clip_file = str(tmp_path / "clip.mp4")
    with open(clip_file, "wb") as f:
        f.write(b"sample video bytes")

    clip = RenderedClip(
        clip_id="clip1",
        job_id="job1",
        candidate_id="cand1",
        file_path=clip_file,
        file_hash="dummy_hash",
        duration_seconds=30.0,
        width=1080,
        height=1920,
        manifest_path="manifest.json",
        rendered_at="2026-10-29T12:00:00Z",
    )
    qa = QAReport(
        qa_id="qa1",
        clip_id="clip1",
        status="PASSED",
        video_stream_ok=True,
        audio_stream_ok=True,
        duration_ok=True,
        actual_duration=30.0,
        expected_duration=30.0,
        aspect_ratio_ok=True,
        actual_aspect_ratio="1080:1920",
        file_size_bytes=1000,
    )

    # First submission in dry_run mode
    r1 = publisher.publish_clip(clip, cand, rights, qa, dry_run=True)
    assert r1.status == "DRY_RUN_SIMULATED"
    assert r1.dry_run is True

    # Immediate second submission with identical candidate and rights -> DUPLICATE_SKIPPED
    r2 = publisher.publish_clip(clip, cand, rights, qa, dry_run=True)
    assert r2.status == "DUPLICATE_SKIPPED"
    assert r2.idempotency_key == r1.idempotency_key


def test_publisher_rejects_unauthorized_rights(tmp_path):
    publisher = DualModeAutopostPublisher(mode="watched_folder", watched_dir=str(tmp_path / "inbox"), receipts_path=str(tmp_path / "receipts.json"))
    cand = HighlightCandidate(candidate_id="c1", video_id="v_unauth", start_seconds=0.0, end_seconds=30.0, duration_seconds=30.0, score=70.0, breakdown=ScoreBreakdown(), hook_title="Unauth")
    rights_unauth = RightsManifest(rights_id="r_unauth", video_id="v_unauth", basis=RightsBasis.OPERATOR_ASSET, status=RightsStatus.PENDING_REVIEW, owner_name="Unknown")
    clip = RenderedClip(clip_id="c1", job_id="j1", candidate_id="c1", file_path="clip.mp4", file_hash="", duration_seconds=30.0, width=1080, height=1920, manifest_path="", rendered_at="")
    qa = QAReport(qa_id="q1", clip_id="c1", status="PASSED", video_stream_ok=True, audio_stream_ok=True, duration_ok=True, actual_duration=30.0, expected_duration=30.0, aspect_ratio_ok=True, actual_aspect_ratio="1080:1920", file_size_bytes=1000)

    receipt = publisher.publish_clip(clip, cand, rights_unauth, qa)
    assert receipt.status == "REJECTED"
    assert "Rights check failed" in receipt.response_payload["reason"]


def test_publisher_rejects_failed_qa(tmp_path):
    publisher = DualModeAutopostPublisher(mode="watched_folder", watched_dir=str(tmp_path / "inbox"), receipts_path=str(tmp_path / "receipts.json"))
    cand = HighlightCandidate(candidate_id="c2", video_id="v_qa_fail", start_seconds=0.0, end_seconds=30.0, duration_seconds=30.0, score=70.0, breakdown=ScoreBreakdown(), hook_title="QA Fail")
    rights = RightsManifest(rights_id="r_ok", video_id="v_qa_fail", basis=RightsBasis.OWNED, status=RightsStatus.VERIFIED, owner_name="Owner")
    clip = RenderedClip(clip_id="c2", job_id="j2", candidate_id="c2", file_path="clip.mp4", file_hash="", duration_seconds=30.0, width=1080, height=1920, manifest_path="", rendered_at="")
    qa_failed = QAReport(qa_id="q2", clip_id="c2", status="FAILED", video_stream_ok=False, audio_stream_ok=False, duration_ok=False, actual_duration=0.0, expected_duration=30.0, aspect_ratio_ok=False, actual_aspect_ratio="unknown", file_size_bytes=0, errors=["Media corrupt"])

    receipt = publisher.publish_clip(clip, cand, rights, qa_failed)
    assert receipt.status == "REJECTED"
    assert "QA verification failed" in receipt.response_payload["reason"]


def test_publisher_live_watched_folder_delivery(tmp_path):
    inbox = str(tmp_path / "inbox")
    receipts = str(tmp_path / "receipts.json")
    publisher = DualModeAutopostPublisher(mode="watched_folder", watched_dir=inbox, receipts_path=receipts)

    cand = HighlightCandidate(candidate_id="c_live", video_id="v_live", start_seconds=0.0, end_seconds=30.0, duration_seconds=30.0, score=85.0, breakdown=ScoreBreakdown(), hook_title="Live")
    rights = RightsManifest(rights_id="r_live", video_id="v_live", basis=RightsBasis.OWNED, status=RightsStatus.VERIFIED, owner_name="Owner")
    media_file = str(tmp_path / "rendered_clip.mp4")
    with open(media_file, "wb") as f:
        f.write(b"video data bytes")

    clip = RenderedClip(clip_id="c_live", job_id="j_live", candidate_id="c_live", file_path=media_file, file_hash="hash123", duration_seconds=30.0, width=1080, height=1920, manifest_path="", rendered_at="")
    qa = QAReport(qa_id="q_live", clip_id="c_live", status="PASSED", video_stream_ok=True, audio_stream_ok=True, duration_ok=True, actual_duration=30.0, expected_duration=30.0, aspect_ratio_ok=True, actual_aspect_ratio="1080:1920", file_size_bytes=100)

    # Live delivery
    receipt = publisher.publish_clip(clip, cand, rights, qa, dry_run=False)
    assert receipt.status == "DELIVERED"
    assert receipt.dry_run is False

    # Check files in watched inbox
    inbox_media = os.path.join(inbox, "rendered_clip.mp4")
    inbox_manifest = os.path.join(inbox, "c_live.autopost.json")
    assert os.path.exists(inbox_media)
    assert os.path.exists(inbox_manifest)
    with open(inbox_manifest, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["clip_id"] == "c_live"
        assert data["rights_record_id"] == "r_live"


def test_publisher_rejects_missing_file_on_disk(tmp_path):
    inbox = str(tmp_path / "inbox")
    receipts = str(tmp_path / "receipts.json")
    publisher = DualModeAutopostPublisher(mode="watched_folder", watched_dir=inbox, receipts_path=receipts)

    cand = HighlightCandidate(candidate_id="c_missing", video_id="v_missing", start_seconds=0.0, end_seconds=30.0, duration_seconds=30.0, score=85.0, breakdown=ScoreBreakdown(), hook_title="Missing")
    rights = RightsManifest(rights_id="r_ok", video_id="v_missing", basis=RightsBasis.OWNED, status=RightsStatus.VERIFIED, owner_name="Owner")
    clip = RenderedClip(clip_id="c_missing", job_id="j_missing", candidate_id="c_missing", file_path=str(tmp_path / "does_not_exist.mp4"), file_hash="", duration_seconds=30.0, width=1080, height=1920, manifest_path="", rendered_at="")
    qa = QAReport(qa_id="q_ok", clip_id="c_missing", status="PASSED", video_stream_ok=True, audio_stream_ok=True, duration_ok=True, actual_duration=30.0, expected_duration=30.0, aspect_ratio_ok=True, actual_aspect_ratio="1080:1920", file_size_bytes=100)

    receipt = publisher.publish_clip(clip, cand, rights, qa, dry_run=False)
    assert receipt.status == "REJECTED"
    assert "missing on disk" in receipt.response_payload["reason"]


def test_publisher_webhook_dry_run_and_unconfigured(tmp_path):
    receipts = str(tmp_path / "receipts.json")
    publisher = DualModeAutopostPublisher(mode="webhook", webhook_url=None, receipts_path=receipts)

    media_file = str(tmp_path / "clip.mp4")
    with open(media_file, "wb") as f:
        f.write(b"content")

    cand = HighlightCandidate(candidate_id="c_wh", video_id="v_wh", start_seconds=0.0, end_seconds=30.0, duration_seconds=30.0, score=85.0, breakdown=ScoreBreakdown(), hook_title="WH")
    rights = RightsManifest(rights_id="r_wh", video_id="v_wh", basis=RightsBasis.OWNED, status=RightsStatus.VERIFIED, owner_name="Owner")
    clip = RenderedClip(clip_id="c_wh", job_id="j_wh", candidate_id="c_wh", file_path=media_file, file_hash="hash", duration_seconds=30.0, width=1080, height=1920, manifest_path="", rendered_at="")
    qa = QAReport(qa_id="q_wh", clip_id="c_wh", status="PASSED", video_stream_ok=True, audio_stream_ok=True, duration_ok=True, actual_duration=30.0, expected_duration=30.0, aspect_ratio_ok=True, actual_aspect_ratio="1080:1920", file_size_bytes=100)

    # Dry run with webhook mode
    r_dry = publisher.publish_clip(clip, cand, rights, qa, dry_run=True)
    assert r_dry.status == "DRY_RUN_SIMULATED"
    assert r_dry.target_mode == "webhook"

    # Live with unconfigured webhook url fails gracefully
    cand2 = HighlightCandidate(candidate_id="c_wh2", video_id="v_wh2", start_seconds=5.0, end_seconds=35.0, duration_seconds=30.0, score=85.0, breakdown=ScoreBreakdown(), hook_title="WH2")
    rights2 = RightsManifest(rights_id="r_wh2", video_id="v_wh2", basis=RightsBasis.OWNED, status=RightsStatus.VERIFIED, owner_name="Owner")
    clip2 = RenderedClip(clip_id="c_wh2", job_id="j_wh2", candidate_id="c_wh2", file_path=media_file, file_hash="hash2", duration_seconds=30.0, width=1080, height=1920, manifest_path="", rendered_at="")
    r_live = publisher.publish_clip(clip2, cand2, rights2, qa, dry_run=False)
    assert r_live.status == "FAILED"
    assert "not configured" in r_live.response_payload["reason"]

