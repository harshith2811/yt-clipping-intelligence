"""
Dual-Mode Autopost Integration Adapter.
Delivers approved clips via Webhook/REST or Watched-Folder JSON manifests.
Enforces hard rights & QA gating, SHA-256 idempotency deduplication, and default dry-run safety.
"""

from typing import Dict, Any, Optional
import os
import json
import hashlib
import uuid
import shutil
from datetime import datetime, timezone
from ..contracts.models import RenderedClip, HighlightCandidate, RightsManifest, QAReport, HandoffReceipt, RightsStatus
from ..contracts.interfaces import HandoffPublisher


class DualModeAutopostPublisher(HandoffPublisher):
    """
    Adapter interfacing with the user's existing external autopost system.
    Guarantees no modifications to external code, enforces idempotency,
    and runs in safe dry-run mode by default.
    """

    def __init__(
        self,
        mode: str = "watched_folder",  # "watched_folder" or "webhook"
        watched_dir: str = "data/autopost_inbox",
        webhook_url: Optional[str] = None,
        auth_token: Optional[str] = None,
        receipts_path: str = "data/handoffs/receipts.json",
    ):
        self.mode = mode
        self.watched_dir = watched_dir
        self.webhook_url = webhook_url
        self.auth_token = auth_token
        self.receipts_path = receipts_path
        self._delivered_keys: Dict[str, HandoffReceipt] = {}

        os.makedirs(os.path.dirname(os.path.abspath(self.receipts_path)), exist_ok=True)
        if self.mode == "watched_folder":
            os.makedirs(self.watched_dir, exist_ok=True)
        self._load_receipts()

    def _load_receipts(self) -> None:
        if os.path.exists(self.receipts_path):
            try:
                with open(self.receipts_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        r = HandoffReceipt.from_dict(item)
                        self._delivered_keys[r.idempotency_key] = r
            except Exception:
                pass

    def _save_receipts(self) -> None:
        temp_path = f"{self.receipts_path}.tmp"
        data = [r.to_dict() for r in self._delivered_keys.values()]
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, self.receipts_path)

    def compute_idempotency_key(
        self, candidate: HighlightCandidate, rights_manifest: RightsManifest
    ) -> str:
        """Computes deterministic SHA-256 key from source video, cut boundaries, and rights ID."""
        raw = f"{candidate.video_id}:{candidate.start_seconds:.3f}:{candidate.end_seconds:.3f}:{rights_manifest.rights_id}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def build_payload(
        self,
        rendered_clip: RenderedClip,
        candidate: HighlightCandidate,
        rights_manifest: RightsManifest,
        qa_report: QAReport,
        idempotency_key: str,
    ) -> Dict[str, Any]:
        """Constructs standardized autopost handoff JSON payload."""
        return {
            "clip_id": rendered_clip.clip_id,
            "asset_path": rendered_clip.file_path,
            "title": candidate.hook_title,
            "description": candidate.suggested_description,
            "tags": ["Shorts", "Highlights", "AI"],
            "source_id": candidate.video_id,
            "source_start_seconds": candidate.start_seconds,
            "source_end_seconds": candidate.end_seconds,
            "duration_seconds": candidate.duration_seconds,
            "rights_record_id": rights_manifest.rights_id,
            "rights_basis": rights_manifest.basis.value,
            "approval_status": candidate.approval_status,
            "qa_status": qa_report.status,
            "qa_checksum": qa_report.checksum_sha256,
            "idempotency_key": idempotency_key,
            "handoff_timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def publish_clip(
        self,
        rendered_clip: RenderedClip,
        candidate: HighlightCandidate,
        rights_manifest: RightsManifest,
        qa_report: QAReport,
        dry_run: bool = True,
    ) -> HandoffReceipt:
        idempotency_key = self.compute_idempotency_key(candidate, rights_manifest)
        now_iso = datetime.now(timezone.utc).isoformat()
        receipt_id = f"rcpt-{uuid.uuid4().hex[:10]}"

        # 1. Idempotency Check: Reject duplicates
        if idempotency_key in self._delivered_keys:
            existing = self._delivered_keys[idempotency_key]
            return HandoffReceipt(
                receipt_id=f"rcpt-dup-{existing.receipt_id}",
                clip_id=rendered_clip.clip_id,
                idempotency_key=idempotency_key,
                status="DUPLICATE_SKIPPED",
                timestamp=now_iso,
                target_mode=self.mode,
                dry_run=dry_run,
                response_payload={"message": "Clip already delivered under idempotency key.", "original_receipt": existing.receipt_id},
            )

        # 2. Hard Rights Gate Check
        if not rights_manifest.is_valid():
            rejected_receipt = HandoffReceipt(
                receipt_id=receipt_id,
                clip_id=rendered_clip.clip_id,
                idempotency_key=idempotency_key,
                status="REJECTED",
                timestamp=now_iso,
                target_mode=self.mode,
                dry_run=dry_run,
                response_payload={"reason": f"Rights check failed. Status: {rights_manifest.status.value}"},
            )
            return rejected_receipt

        # 3. Quality Assurance Check
        if qa_report.status == "FAILED":
            rejected_receipt = HandoffReceipt(
                receipt_id=receipt_id,
                clip_id=rendered_clip.clip_id,
                idempotency_key=idempotency_key,
                status="REJECTED",
                timestamp=now_iso,
                target_mode=self.mode,
                dry_run=dry_run,
                response_payload={"reason": f"QA verification failed. Errors: {qa_report.errors}"},
            )
            return rejected_receipt

        # 3b. Verify artifact exists on disk
        if not os.path.exists(rendered_clip.file_path):
            return HandoffReceipt(
                receipt_id=receipt_id,
                clip_id=rendered_clip.clip_id,
                idempotency_key=idempotency_key,
                status="REJECTED",
                timestamp=now_iso,
                target_mode=self.mode,
                dry_run=dry_run,
                response_payload={"reason": f"Rendered asset file missing on disk: {rendered_clip.file_path}"},
            )

        # 4. Construct Payload
        payload = self.build_payload(rendered_clip, candidate, rights_manifest, qa_report, idempotency_key)

        # 5. Handle Dry-Run Mode (Default)
        if dry_run:
            receipt = HandoffReceipt(
                receipt_id=receipt_id,
                clip_id=rendered_clip.clip_id,
                idempotency_key=idempotency_key,
                status="DRY_RUN_SIMULATED",
                timestamp=now_iso,
                target_mode=self.mode,
                dry_run=True,
                response_payload={"dry_run": True, "payload": payload},
            )
            self._delivered_keys[idempotency_key] = receipt
            self._save_receipts()
            return receipt

        # 6. Live Handoff Execution
        if self.mode == "watched_folder":
            inbox_manifest = os.path.join(self.watched_dir, f"{rendered_clip.clip_id}.autopost.json")
            inbox_media = os.path.join(self.watched_dir, os.path.basename(rendered_clip.file_path))

            # Copy media to watched inbox
            shutil.copy2(rendered_clip.file_path, inbox_media)
            # Write handoff manifest atomically
            temp_manifest = f"{inbox_manifest}.tmp"
            with open(temp_manifest, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(temp_manifest, inbox_manifest)

            receipt = HandoffReceipt(
                receipt_id=receipt_id,
                clip_id=rendered_clip.clip_id,
                idempotency_key=idempotency_key,
                status="DELIVERED",
                timestamp=now_iso,
                target_mode="watched_folder",
                dry_run=False,
                response_payload={"inbox_manifest": inbox_manifest, "inbox_media": inbox_media},
            )
            self._delivered_keys[idempotency_key] = receipt
            self._save_receipts()
            return receipt

        elif self.mode == "webhook":
            import urllib.request
            import urllib.error
            status = "FAILED"
            headers = {"Content-Type": "application/json"}
            if self.auth_token:
                headers["Authorization"] = f"Bearer {self.auth_token}"

            if not self.webhook_url:
                response_payload = {"reason": "Webhook URL is not configured."}
            else:
                req = urllib.request.Request(
                    self.webhook_url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        http_code = resp.getcode()
                        body = resp.read().decode("utf-8", errors="replace")
                        if 200 <= http_code < 300:
                            status = "DELIVERED"
                        response_payload = {
                            "webhook_url": self.webhook_url,
                            "http_status": http_code,
                            "response": body[:500],
                        }
                except urllib.error.HTTPError as he:
                    response_payload = {
                        "webhook_url": self.webhook_url,
                        "http_status": he.code,
                        "error": str(he),
                    }
                except Exception as ex:
                    response_payload = {
                        "webhook_url": self.webhook_url,
                        "error": str(ex),
                    }

            receipt = HandoffReceipt(
                receipt_id=receipt_id,
                clip_id=rendered_clip.clip_id,
                idempotency_key=idempotency_key,
                status=status,
                timestamp=now_iso,
                target_mode="webhook",
                dry_run=False,
                response_payload=response_payload,
            )
            if status == "DELIVERED":
                self._delivered_keys[idempotency_key] = receipt
                self._save_receipts()
            return receipt

        raise ValueError(f"Unknown publisher mode: {self.mode}")
