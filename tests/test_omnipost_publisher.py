"""
Tests for OmniPost Social Media Publishing Adapter & Direct Integration.
Verifies preflight checks, rights/QA gating, idempotency preservation, and mock delivery.
"""

import pytest
import os
import json
from unittest.mock import patch, MagicMock

from yt_clipping.publisher.omnipost import OmniPostPublisher
from yt_clipping.publisher.adapter import DualModeAutopostPublisher
from yt_clipping.contracts.models import (
    RenderedClip,
    HighlightCandidate,
    RightsManifest,
    QAReport,
    RightsBasis,
    RightsStatus,
    ScoreBreakdown,
)


@pytest.fixture
def mock_candidate():
    return HighlightCandidate(
        candidate_id="cand_omni_01",
        video_id="test_vid_omni",
        start_seconds=10.0,
        end_seconds=40.0,
        duration_seconds=30.0,
        score=85.0,
        breakdown=ScoreBreakdown(hook_score=8.5, moment_score=8.0, coherence_score=9.0, pacing_score=8.5),
        hook_title="Super Viral Short Hook",
        suggested_description="Check out this awesome viral breakdown! #shorts",
    )


@pytest.fixture
def mock_rights_cleared():
    return RightsManifest(
        rights_id="rm_omni_01",
        video_id="test_vid_omni",
        basis=RightsBasis.OWNED,
        status=RightsStatus.VERIFIED,
        owner_name="Test Creator",
        audit_notes="Fully owned creator content",
    )


@pytest.fixture
def mock_rights_rejected():
    return RightsManifest(
        rights_id="rm_omni_rej",
        video_id="test_vid_omni",
        basis=RightsBasis.CREATIVE_COMMONS,
        status=RightsStatus.REJECTED,
        owner_name="Unknown",
        audit_notes="Takedown notice",
    )


@pytest.fixture
def mock_qa_passed():
    return QAReport(
        qa_id="qa_omni_01",
        clip_id="clip_omni_01",
        status="PASSED",
        video_stream_ok=True,
        audio_stream_ok=True,
        duration_ok=True,
        actual_duration=30.0,
        expected_duration=30.0,
        aspect_ratio_ok=True,
        actual_aspect_ratio="9:16",
        file_size_bytes=1024,
        checksum_sha256="abc123sha",
        errors=[],
        warnings=[],
    )


@pytest.fixture
def mock_qa_failed():
    return QAReport(
        qa_id="qa_omni_fail",
        clip_id="clip_omni_01",
        status="FAILED",
        video_stream_ok=False,
        audio_stream_ok=True,
        duration_ok=False,
        actual_duration=30.0,
        expected_duration=30.0,
        aspect_ratio_ok=True,
        actual_aspect_ratio="9:16",
        file_size_bytes=1024,
        checksum_sha256="",
        errors=["Black frames detected for 5.2s"],
        warnings=[],
    )


@pytest.fixture
def mock_rendered_clip(tmp_path):
    clip_file = tmp_path / "test_clip.mp4"
    clip_file.write_bytes(b"dummy mp4 video bytes")
    manifest_file = tmp_path / "test_clip.manifest.json"
    manifest_file.write_text("{}", encoding="utf-8")
    return RenderedClip(
        clip_id="clip_omni_01",
        job_id="job_omni_01",
        candidate_id="cand_omni_01",
        file_path=str(clip_file),
        file_hash="abc123hash",
        duration_seconds=30.0,
        width=1080,
        height=1920,
        manifest_path=str(manifest_file),
        rendered_at="2026-11-02T19:00:00Z",
    )


def test_omnipost_preflight_success():
    pub = OmniPostPublisher(base_url="http://localhost:3300", api_key="secret123")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"readyToPublish": ["youtube", "instagram"]}

    with patch("requests.get", return_value=mock_resp) as mock_get:
        res = pub.preflight_check()
        assert res["readyToPublish"] == ["youtube", "instagram"]
        mock_get.assert_called_once_with(
            "http://localhost:3300/api/engine/preflight",
            headers={
                "Accept": "application/json",
                "x-api-key": "secret123",
                "x-admin-key": "secret123",
                "Authorization": "Bearer secret123",
            },
            timeout=10,
        )


def test_omnipost_preflight_offline():
    pub = OmniPostPublisher(base_url="http://localhost:3300")
    with patch("requests.get", side_effect=Exception("Connection refused")):
        res = pub.preflight_check()
        assert res["status"] == "offline"


def test_omnipost_gated_rights_failure(tmp_path, mock_rendered_clip, mock_candidate, mock_rights_rejected, mock_qa_passed):
    db_file = tmp_path / "test_jobs.db"
    pub = OmniPostPublisher(db_path=str(db_file))
    receipt = pub.publish(mock_rendered_clip, mock_candidate, mock_rights_rejected, mock_qa_passed)
    assert receipt.status == "REJECTED"
    assert "Rights not cleared" in receipt.response_payload["error"]


def test_omnipost_gated_qa_failure(tmp_path, mock_rendered_clip, mock_candidate, mock_rights_cleared, mock_qa_failed):
    db_file = tmp_path / "test_jobs.db"
    pub = OmniPostPublisher(db_path=str(db_file))
    receipt = pub.publish(mock_rendered_clip, mock_candidate, mock_rights_cleared, mock_qa_failed)
    assert receipt.status == "REJECTED"
    assert "QA verification failed" in receipt.response_payload["error"]


def test_omnipost_dry_run_simulation(tmp_path, mock_rendered_clip, mock_candidate, mock_rights_cleared, mock_qa_passed):
    db_file = tmp_path / "test_jobs.db"
    pub = OmniPostPublisher(db_path=str(db_file))
    receipt = pub.publish(mock_rendered_clip, mock_candidate, mock_rights_cleared, mock_qa_passed, dry_run=True)
    assert receipt.status == "DRY_RUN_SIMULATED"
    assert receipt.dry_run is True
    assert receipt.response_payload["simulated"] is True


def test_omnipost_live_delivery_and_duplicate_suppression(tmp_path, mock_rendered_clip, mock_candidate, mock_rights_cleared, mock_qa_passed):
    db_file = tmp_path / "test_jobs.db"
    pub = OmniPostPublisher(db_path=str(db_file))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"success": True, "contentId": "W-123456", "publicMediaUrl": "http://cdn/1.mp4"}

    with patch("requests.post", return_value=mock_resp) as mock_post:
        # First delivery: Success
        receipt1 = pub.publish(mock_rendered_clip, mock_candidate, mock_rights_cleared, mock_qa_passed, dry_run=False)
        assert receipt1.status == "DELIVERED"
        assert receipt1.response_payload["contentId"] == "W-123456"
        assert mock_post.called

        # Second delivery with same candidate boundaries & rights: Duplicate skipped
        receipt2 = pub.publish(mock_rendered_clip, mock_candidate, mock_rights_cleared, mock_qa_passed, dry_run=False)
        assert receipt2.status == "DUPLICATE_SKIPPED"
        assert receipt2.response_payload["original_receipt_id"] == receipt1.receipt_id


def test_dual_mode_adapter_omnipost_integration(tmp_path, mock_rendered_clip, mock_candidate, mock_rights_cleared, mock_qa_passed):
    db_file = tmp_path / "test_jobs.db"
    adapter = DualModeAutopostPublisher(
        mode="omnipost",
        webhook_url="http://localhost:3300",
        auth_token="token_omni",
        db_path=str(db_file),
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"success": True, "contentId": "W-888999"}

    with patch("requests.post", return_value=mock_resp):
        receipt = adapter.publish(mock_rendered_clip, mock_candidate, mock_rights_cleared, mock_qa_passed, dry_run=False)
        assert receipt.status == "DELIVERED"
        assert receipt.target_mode == "omnipost"
