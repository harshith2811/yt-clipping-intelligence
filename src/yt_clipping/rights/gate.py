"""
Rights Policy Enforcement Gate.
Strictly verifies that any source asset has explicit rights before entering media retrieval,
transcription, rendering, or publishing pipelines.
"""

from typing import Dict, Optional, List
import json
import os
from datetime import datetime, timezone
from ..contracts.models import RightsManifest, RightsStatus, RightsBasis
from ..contracts.interfaces import RightsPolicy, RightsPolicyViolationError


class LocalRightsPolicy(RightsPolicy):
    """
    Local file-backed ledger of authorized video rights records.
    Provides persistent storage and policy enforcement.
    """

    def __init__(self, ledger_path: Optional[str] = None):
        self.ledger_path = ledger_path
        self._manifests: Dict[str, RightsManifest] = {}
        if ledger_path and os.path.exists(ledger_path):
            self._load_ledger()

    def _load_ledger(self) -> None:
        try:
            with open(self.ledger_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    manifest = RightsManifest.from_dict(item)
                    self._manifests[manifest.video_id] = manifest
        except Exception as e:
            # Fallback or empty ledger if corrupted
            pass

    def _persist_ledger(self) -> None:
        if not self.ledger_path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.ledger_path)), exist_ok=True)
        data = [m.to_dict() for m in self._manifests.values()]
        temp_path = f"{self.ledger_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, self.ledger_path)

    def register_rights(self, manifest: RightsManifest) -> None:
        """Registers a rights manifest for a video."""
        self._manifests[manifest.video_id] = manifest
        self._persist_ledger()

    def check_rights(self, video_id: str) -> RightsManifest:
        """
        Retrieves the rights manifest for a video.
        If no manifest exists, returns a default PENDING_REVIEW manifest.
        """
        if video_id in self._manifests:
            return self._manifests[video_id]

        # Default unverified record
        unverified = RightsManifest(
            rights_id=f"rights-pending-{video_id}",
            video_id=video_id,
            basis=RightsBasis.OPERATOR_ASSET,
            status=RightsStatus.PENDING_REVIEW,
            owner_name="Unknown",
            audit_notes="No verified rights record on file. Processing blocked.",
        )
        return unverified

    def verify_rights(self, manifest: RightsManifest) -> bool:
        """
        Returns True if the manifest is VERIFIED and unexpired.
        Returns False if PENDING_REVIEW, REJECTED, REVOKED, or expired.
        """
        if manifest.status != RightsStatus.VERIFIED:
            return False

        if manifest.valid_until:
            try:
                dt = datetime.fromisoformat(manifest.valid_until.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                if now > dt:
                    return False
            except ValueError:
                return False

        return True

    def assert_can_process(self, video_id: str) -> RightsManifest:
        """
        Raises RightsPolicyViolationError if the video lacks verified rights.
        Returns the valid RightsManifest if authorized.
        """
        manifest = self.check_rights(video_id)
        if not self.verify_rights(manifest):
            raise RightsPolicyViolationError(
                f"Rights Policy Violation: Video '{video_id}' has rights status '{manifest.status.value}'. "
                f"Must be 'VERIFIED' to download, render, or publish. Notes: {manifest.audit_notes}"
            )
        return manifest
