"""
Rights Policy Enforcement Gate.
Strictly verifies that any source asset has explicit rights before entering media retrieval,
transcription, rendering, or publishing pipelines.
Backed by SQLite transactional persistence to survive restarts, with JSON ledger support.
"""

from typing import Dict, Optional, List
import json
import os
import sqlite3
from datetime import datetime, timezone
from ..contracts.models import RightsManifest, RightsStatus, RightsBasis
from ..contracts.interfaces import RightsPolicy, RightsPolicyViolationError
from ..orchestration.db import DatabaseManager


class LocalRightsPolicy(RightsPolicy):
    """
    Durable ledger of authorized video rights records.
    Persists grants to SQLite database with JSON fallback for legacy interoperability.
    """

    def __init__(self, ledger_path: Optional[str] = None, db_path: Optional[str] = None):
        self.ledger_path = ledger_path
        if db_path is None:
            if ledger_path:
                db_path = os.path.splitext(ledger_path)[0] + ".db"
            else:
                db_path = "data/jobs.db"
        self.db = DatabaseManager(db_path)
        self._manifests: Dict[str, RightsManifest] = {}

        # 1. Migrate / load from legacy ledger_path if present
        if ledger_path and os.path.exists(ledger_path):
            self._import_from_json(ledger_path)

        # 2. Load from SQLite
        self._load_from_db()

    def _import_from_json(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    manifest = RightsManifest.from_dict(item)
                    self._upsert_db(manifest)
        except Exception:
            pass

    def _load_from_db(self) -> None:
        conn = self.db.get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT rights_id, video_id, basis, status, owner_name, license_url, proof_reference, valid_until, verified_at, audit_notes
                FROM rights_ledger
                """
            )
            for row in cursor.fetchall():
                manifest = RightsManifest(
                    rights_id=row[0],
                    video_id=row[1],
                    basis=RightsBasis(row[2]),
                    status=RightsStatus(row[3]),
                    owner_name=row[4],
                    license_url=row[5] or "",
                    proof_reference=row[6] or "",
                    valid_until=row[7],
                    verified_at=row[8],
                    audit_notes=row[9] or "",
                )
                self._manifests[manifest.video_id] = manifest
        finally:
            conn.close()

    def _upsert_db(self, m: RightsManifest) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO rights_ledger (
                        rights_id, video_id, basis, status, owner_name, license_url, proof_reference, valid_until, verified_at, audit_notes, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(video_id) DO UPDATE SET
                        rights_id=excluded.rights_id,
                        basis=excluded.basis,
                        status=excluded.status,
                        owner_name=excluded.owner_name,
                        license_url=excluded.license_url,
                        proof_reference=excluded.proof_reference,
                        valid_until=excluded.valid_until,
                        verified_at=excluded.verified_at,
                        audit_notes=excluded.audit_notes,
                        updated_at=excluded.updated_at
                    """,
                    (
                        m.rights_id,
                        m.video_id,
                        m.basis.value,
                        m.status.value,
                        m.owner_name,
                        m.license_url,
                        m.proof_reference,
                        m.valid_until,
                        m.verified_at,
                        m.audit_notes,
                        now_iso,
                        now_iso,
                    ),
                )
        finally:
            conn.close()

    def _export_to_json(self) -> None:
        if not self.ledger_path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.ledger_path)), exist_ok=True)
        data = [m.to_dict() for m in self._manifests.values()]
        temp_path = f"{self.ledger_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, self.ledger_path)

    def register_rights(self, manifest: RightsManifest) -> None:
        """Registers and durably persists a rights manifest for a video."""
        self._manifests[manifest.video_id] = manifest
        self._upsert_db(manifest)
        self._export_to_json()

    def check_rights(self, video_id: str) -> RightsManifest:
        """
        Retrieves the rights manifest for a video from database.
        If no manifest exists, returns a default PENDING_REVIEW manifest.
        """
        if video_id in self._manifests:
            return self._manifests[video_id]

        # Check DB directly in case another process inserted it
        conn = self.db.get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT rights_id, video_id, basis, status, owner_name, license_url, proof_reference, valid_until, verified_at, audit_notes
                FROM rights_ledger WHERE video_id = ?
                """,
                (video_id,),
            )
            row = cursor.fetchone()
            if row:
                manifest = RightsManifest(
                    rights_id=row[0],
                    video_id=row[1],
                    basis=RightsBasis(row[2]),
                    status=RightsStatus(row[3]),
                    owner_name=row[4],
                    license_url=row[5] or "",
                    proof_reference=row[6] or "",
                    valid_until=row[7],
                    verified_at=row[8],
                    audit_notes=row[9] or "",
                )
                self._manifests[video_id] = manifest
                return manifest
        finally:
            conn.close()

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

    def list_all_manifests(self) -> List[RightsManifest]:
        """Returns all persistent rights records."""
        self._load_from_db()
        return list(self._manifests.values())
