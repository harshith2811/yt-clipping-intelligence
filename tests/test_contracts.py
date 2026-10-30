"""
Tests for typed data contracts and model serialization.
"""

import pytest
from src.yt_clipping.contracts.models import (
    RightsBasis,
    RightsStatus,
    JobStage,
    JobStatus,
    CreatorSource,
    VideoCandidate,
    MetricSnapshot,
    RightsManifest,
    WordTimestamp,
    TranscriptSegment,
    Transcript,
    ScoreBreakdown,
    HighlightCandidate,
    RenderProfile,
    QAReport,
    RenderedClip,
    HandoffReceipt,
    ClipJob,
)


def test_creator_source_serialization():
    creator = CreatorSource(
        creator_id="c1",
        name="Tech Creator",
        channel_id="UC12345",
        channel_url="https://youtube.com/@techcreator",
        baseline_views=25000.0,
    )
    d = creator.to_dict()
    assert d["creator_id"] == "c1"
    assert d["baseline_views"] == 25000.0

    restored = CreatorSource.from_dict(d)
    assert restored == creator


def test_rights_manifest_validity():
    manifest_valid = RightsManifest(
        rights_id="r1",
        video_id="v1",
        basis=RightsBasis.OWNED,
        status=RightsStatus.VERIFIED,
        owner_name="Operator Channel",
        valid_until="2099-01-01T00:00:00Z",
    )
    assert manifest_valid.is_valid() is True

    manifest_expired = RightsManifest(
        rights_id="r2",
        video_id="v2",
        basis=RightsBasis.EXPLICIT_PERMISSION,
        status=RightsStatus.VERIFIED,
        owner_name="Partner",
        valid_until="2020-01-01T00:00:00Z",
    )
    assert manifest_expired.is_valid() is False

    manifest_unverified = RightsManifest(
        rights_id="r3",
        video_id="v3",
        basis=RightsBasis.CREATIVE_COMMONS,
        status=RightsStatus.PENDING_REVIEW,
        owner_name="Third Party",
    )
    assert manifest_unverified.is_valid() is False


def test_transcript_serialization():
    words = [
        WordTimestamp(word="Hello", start=0.0, end=0.5, confidence=0.99),
        WordTimestamp(word="world", start=0.6, end=1.0, confidence=0.95),
    ]
    seg = TranscriptSegment(segment_id=1, start=0.0, end=1.0, text="Hello world", words=words)
    transcript = Transcript(
        video_id="v100",
        language="en",
        duration_seconds=60.0,
        text="Hello world",
        segments=[seg],
        provider="faster-whisper",
    )

    d = transcript.to_dict()
    restored = Transcript.from_dict(d)
    assert restored.video_id == "v100"
    assert len(restored.segments) == 1
    assert restored.segments[0].words[0].word == "Hello"


def test_clip_job_checkpoints():
    job = ClipJob(
        job_id="job-1",
        video_id="v1",
        current_stage=JobStage.DISCOVERED,
        status=JobStatus.IN_PROGRESS,
    )
    job.record_checkpoint(JobStage.RIGHTS_CHECKED, {"verified": True})
    assert JobStage.RIGHTS_CHECKED.value in job.checkpoints
    assert job.current_stage == JobStage.RIGHTS_CHECKED

    key = job.compute_idempotency_key()
    assert len(key) == 64  # SHA-256 hex length
