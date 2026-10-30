"""
Tests for RightsGate policy enforcement.
Ensures unauthorized or expired content is strictly blocked prior to media ingestion.
"""

import pytest
import os
import json
from src.yt_clipping.contracts.models import RightsManifest, RightsBasis, RightsStatus
from src.yt_clipping.contracts.interfaces import RightsPolicyViolationError
from src.yt_clipping.rights.gate import LocalRightsPolicy


def test_rights_gate_unregistered_video_blocks_processing(tmp_path):
    ledger = str(tmp_path / "ledger.json")
    policy = LocalRightsPolicy(ledger)

    # Unregistered video defaults to PENDING_REVIEW
    manifest = policy.check_rights("unregistered_vid_123")
    assert manifest.status == RightsStatus.PENDING_REVIEW
    assert policy.verify_rights(manifest) is False

    with pytest.raises(RightsPolicyViolationError) as exc_info:
        policy.assert_can_process("unregistered_vid_123")
    assert "PENDING_REVIEW" in str(exc_info.value)


def test_rights_gate_registered_verified_passes(tmp_path):
    ledger = str(tmp_path / "ledger.json")
    policy = LocalRightsPolicy(ledger)

    manifest = RightsManifest(
        rights_id="r-owned-1",
        video_id="owned_vid_456",
        basis=RightsBasis.OWNED,
        status=RightsStatus.VERIFIED,
        owner_name="Primary Operator",
    )
    policy.register_rights(manifest)

    checked = policy.check_rights("owned_vid_456")
    assert checked.status == RightsStatus.VERIFIED
    assert policy.verify_rights(checked) is True

    # Assert does not raise
    authorized = policy.assert_can_process("owned_vid_456")
    assert authorized.video_id == "owned_vid_456"


def test_rights_gate_expired_manifest_blocks(tmp_path):
    ledger = str(tmp_path / "ledger.json")
    policy = LocalRightsPolicy(ledger)

    manifest = RightsManifest(
        rights_id="r-expired-1",
        video_id="expired_vid_789",
        basis=RightsBasis.EXPLICIT_PERMISSION,
        status=RightsStatus.VERIFIED,
        owner_name="Licensed Creator",
        valid_until="2021-01-01T00:00:00Z",  # Expired in past
    )
    policy.register_rights(manifest)

    checked = policy.check_rights("expired_vid_789")
    assert policy.verify_rights(checked) is False

    with pytest.raises(RightsPolicyViolationError):
        policy.assert_can_process("expired_vid_789")
