"""
Tests for Publishing Workflow & Human Governance.
Verifies explicit human approval requirement, dedicated YouTube publishing,
scheduling, retry of failed publishing jobs, and publishing history logs.
"""

import pytest
import os
import json
from unittest.mock import patch, MagicMock

from yt_clipping.publisher.omnipost import OmniPostPublisher
from yt_clipping.contracts.models import (
    RenderedClip,
    HighlightCandidate,
    RightsManifest,
    QAReport,
    RightsBasis,
    RightsStatus,
    ScoreBreakdown,
)
from yt_clipping.auth.google_oauth import DedicatedYouTubeAuth


@pytest.fixture
def test_setup(tmp_path):
    clip_file = tmp_path / "test_clip.mp4"
    clip_file.write_bytes(b"dummy mp4 video bytes")
    manifest_file = tmp_path / "test_clip.manifest.json"
    manifest_file.write_text("{}", encoding="utf-8")

    clip = RenderedClip(
        clip_id="clip_pub_01",
        job_id="job_pub_01",
        candidate_id="cand_pub_01",
        file_path=str(clip_file),
        file_hash="hash_pub_01",
        duration_seconds=30.0,
        width=1080,
        height=1920,
        manifest_path=str(manifest_file),
        rendered_at="2026-11-02T19:00:00Z",
    )

    candidate = HighlightCandidate(
        candidate_id="cand_pub_01",
        video_id="vid_pub_01",
        start_seconds=10.0,
        end_seconds=40.0,
        duration_seconds=30.0,
        score=92.0,
        breakdown=ScoreBreakdown(hook_score=9.0, moment_score=9.0, coherence_score=9.0, pacing_score=9.5),
        hook_title="Top Secret Strategy",
        suggested_description="You will not believe this! #shorts",
    )

    rights = RightsManifest(
        rights_id="rm_pub_01",
        video_id="vid_pub_01",
        basis=RightsBasis.OWNED,
        status=RightsStatus.VERIFIED,
        owner_name="Test Owner",
    )

    qa = QAReport(
        qa_id="qa_pub_01",
        clip_id="clip_pub_01",
        status="PASSED",
        video_stream_ok=True,
        audio_stream_ok=True,
        duration_ok=True,
        actual_duration=30.0,
        expected_duration=30.0,
        aspect_ratio_ok=True,
        actual_aspect_ratio="9:16",
        file_size_bytes=1024,
        checksum_sha256="abc",
    )

    db_file = tmp_path / "jobs.db"
    auth = DedicatedYouTubeAuth(
        credentials_file=str(tmp_path / "creds.json"),
        env_mode="development",
    )
    pub = OmniPostPublisher(db_path=str(db_file), youtube_auth=auth)

    return pub, clip, candidate, rights, qa


def test_publishing_requires_explicit_user_approval(test_setup):
    pub, clip, candidate, rights, qa = test_setup

    # Attempting to publish without explicit user approval is REJECTED
    receipt = pub.publish(
        clip, candidate, rights, qa,
        approved_by_user=False,
    )
    assert receipt.status == "REJECTED"
    assert "Explicit human approval required" in receipt.response_payload["error"]


def test_dedicated_youtube_channel_publishing(test_setup):
    pub, clip, candidate, rights, qa = test_setup

    receipt = pub.publish(
        clip, candidate, rights, qa,
        approved_by_user=True,
        publish_target="youtube_dedicated",
        title_override="Custom Human Approved Title",
        description_override="Custom Description",
        tags=["ai", "shorts"],
    )

    assert receipt.status == "DELIVERED"
    assert receipt.target_mode == "youtube_dedicated"
    assert "video_id" in receipt.response_payload
    assert receipt.response_payload["title"] == "Custom Human Approved Title"


def test_scheduled_publishing(test_setup):
    pub, clip, candidate, rights, qa = test_setup
    scheduled_iso = "2026-12-01T15:00:00Z"

    receipt = pub.publish(
        clip, candidate, rights, qa,
        approved_by_user=True,
        publish_target="youtube_dedicated",
        scheduled_time=scheduled_iso,
    )

    assert receipt.status == "SCHEDULED"
    assert receipt.response_payload["scheduled_time"] == scheduled_iso


def test_publishing_history_and_retry(test_setup):
    pub, clip, candidate, rights, qa = test_setup

    # 1. Deliver one job
    pub.publish(
        clip, candidate, rights, qa,
        approved_by_user=True,
        publish_target="youtube_dedicated",
    )

    # 2. Check history
    history = pub.list_publishing_history(limit=10)
    assert len(history) >= 1
    assert history[0]["clip_id"] == "clip_pub_01"

    # 3. Simulate a failed receipt in the ledger
    mock_failed_receipt_id = "rcpt-test-fail-123"
    from yt_clipping.contracts.models import HandoffReceipt
    failed_receipt = HandoffReceipt(
        receipt_id=mock_failed_receipt_id,
        clip_id="clip_pub_01",
        idempotency_key="idemp_fail_123",
        status="FAILED",
        timestamp="2026-11-09T10:00:00Z",
        target_mode="youtube_dedicated",
        dry_run=False,
        response_payload={
            "error": "Temporary network drop",
            "file_path": clip.file_path,
            "title": "Failed Title",
        },
    )
    pub._persist_receipt(failed_receipt)

    # 4. Retry failed job safely
    retried = pub.retry_failed_job(mock_failed_receipt_id)
    assert retried.status == "DELIVERED"
    assert retried.response_payload.get("retry_count") == 1


def test_publishing_with_channel_and_thumbnail(test_setup, tmp_path):
    pub, clip, candidate, rights, qa = test_setup
    thumb_file = tmp_path / "custom_cover.jpg"
    thumb_file.write_bytes(b"dummy thumbnail bytes")

    receipt = pub.publish(
        clip, candidate, rights, qa,
        approved_by_user=True,
        publish_target="youtube_dedicated",
        channel_id="UC_AUTOMATION_DEST",
        thumbnail_path=str(thumb_file),
        scheduled_time="2026-12-31T23:59:59Z",
    )

    assert receipt.status == "SCHEDULED"
    assert receipt.response_payload["channel_id"] == "UC_AUTOMATION_DEST"
    assert receipt.response_payload["thumbnail_set"] is True
    assert receipt.response_payload["thumbnail_path"] == str(thumb_file)


def test_retry_locates_media_via_glob(test_setup, tmp_path):
    pub, clip, candidate, rights, qa = test_setup
    from yt_clipping.contracts.models import HandoffReceipt

    # Place clip into rendered_clips with standard prefix
    clips_dir = os.path.join("data", "rendered_clips")
    os.makedirs(clips_dir, exist_ok=True)
    moved_clip = os.path.join(clips_dir, "clip_test_glob_find_123.mp4")
    with open(moved_clip, "wb") as f:
        f.write(b"valid clip video data")

    fail_rcpt = HandoffReceipt(
        receipt_id="rcpt-test-glob-01",
        clip_id="find_123",
        idempotency_key="idemp_glob_01",
        status="FAILED",
        timestamp="2026-11-09T10:00:00Z",
        target_mode="youtube_dedicated",
        dry_run=False,
        response_payload={
            "error": "Timeout",
            "file_path": "non_existent_original_path.mp4",
            "title": "Recovered Clip",
        },
    )
    pub._persist_receipt(fail_rcpt)

    retried = pub.retry_failed_job("rcpt-test-glob-01")
    assert retried.status == "DELIVERED"
    assert retried.response_payload.get("retry_count") == 1
