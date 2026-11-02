"""
OmniPost Social Media Publishing Adapter (FEATURE-08 / INTEGRATION).
Connects yt-clipping to the OmniPost Social Media Automation & Publishing Engine (port 3300)
for direct multi-channel distribution: YouTube Shorts, Instagram Reels, Facebook Reels, and LinkedIn.
"""

from typing import Dict, Any, Optional, List, Union
import os
import json
import uuid
import logging
from datetime import datetime, timezone
import requests

from ..contracts.models import (
    RenderedClip,
    HighlightCandidate,
    RightsManifest,
    QAReport,
    HandoffReceipt,
    RightsStatus,
    compute_canonical_idempotency_key,
)
from ..contracts.interfaces import HandoffPublisher
from ..orchestration.db import DatabaseManager

logger = logging.getLogger("yt_clipping.publisher.omnipost")


class OmniPostPublisher(HandoffPublisher):
    """
    Direct social media publishing adapter integrating with OmniPost server.
    Uploads vertical video MP4s and triggers immediate or scheduled publishing
    to YouTube Shorts, Instagram Reels, Facebook, and LinkedIn.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:3300",
        api_key: Optional[str] = None,
        default_platforms: Optional[List[str]] = None,
        db_path: str = "data/jobs.db",
        timeout: int = 120,
    ):
        self.base_url = (os.environ.get("OMNIPOST_BASE_URL") or base_url).rstrip("/")
        self.api_key = (
            api_key
            or os.environ.get("OMNIPOST_API_KEY")
            or os.environ.get("AUTOMATION_SECRET_KEY")
            or os.environ.get("CHAMBERS_ADMIN_SECRET_KEY")
            or ""
        )
        self.default_platforms = default_platforms or ["youtube", "instagram"]
        self.db = DatabaseManager(db_path)
        self.timeout = timeout

    def compute_idempotency_key(
        self, candidate: HighlightCandidate, rights_manifest: RightsManifest
    ) -> str:
        return compute_canonical_idempotency_key(
            video_id=candidate.video_id,
            start_seconds=candidate.start_seconds,
            end_seconds=candidate.end_seconds,
            rights_id=rights_manifest.rights_id,
        )

    def preflight_check(self) -> Dict[str, Any]:
        """Checks OmniPost server status and returns active/ready channels."""
        url = f"{self.base_url}/api/engine/preflight"
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            return {"status": "unhealthy", "code": resp.status_code, "body": resp.text}
        except Exception as e:
            logger.warning(f"OmniPost preflight check failed (server offline or unreachable): {e}")
            return {"status": "offline", "error": str(e)}

    def publish_clip(
        self,
        rendered_clip: RenderedClip,
        candidate: HighlightCandidate,
        rights_manifest: RightsManifest,
        qa_report: QAReport,
        dry_run: bool = False,
        platforms: Optional[List[str]] = None,
        scheduled_time: Optional[str] = None,
    ) -> HandoffReceipt:
        """
        Gated publishing execution: enforces rights clearance and QA verification
        before delivering video asset to OmniPost.
        """
        idempotency_key = self.compute_idempotency_key(candidate, rights_manifest)
        now_iso = datetime.now(timezone.utc).isoformat()
        target_platforms = platforms or self.default_platforms

        # 1. Enforce Rights Gate
        if not rights_manifest.is_valid():
            return HandoffReceipt(
                receipt_id=f"rcpt-omnipost-rejected-{uuid.uuid4().hex[:10]}",
                clip_id=rendered_clip.clip_id,
                idempotency_key=idempotency_key,
                status="REJECTED",
                timestamp=now_iso,
                target_mode="omnipost",
                dry_run=dry_run,
                response_payload={"error": f"Rights not cleared: {rights_manifest.status.value}"},
            )

        # 2. Enforce QA Gate
        if qa_report.status != "PASSED":
            return HandoffReceipt(
                receipt_id=f"rcpt-omnipost-rejected-{uuid.uuid4().hex[:10]}",
                clip_id=rendered_clip.clip_id,
                idempotency_key=idempotency_key,
                status="REJECTED",
                timestamp=now_iso,
                target_mode="omnipost",
                dry_run=dry_run,
                response_payload={"error": "QA verification failed", "errors": qa_report.errors},
            )

        # 3. Check Idempotency Ledger
        existing_receipt = self._get_receipt(idempotency_key)
        if existing_receipt and existing_receipt.status == "DELIVERED":
            logger.info(f"Duplicate delivery skipped for key: {idempotency_key}")
            return HandoffReceipt(
                receipt_id=f"rcpt-omnipost-dup-{uuid.uuid4().hex[:10]}",
                clip_id=rendered_clip.clip_id,
                idempotency_key=idempotency_key,
                status="DUPLICATE_SKIPPED",
                timestamp=now_iso,
                target_mode="omnipost",
                dry_run=dry_run,
                response_payload={"original_receipt_id": existing_receipt.receipt_id},
            )

        # 4. Dry-run Mode
        if dry_run:
            receipt = HandoffReceipt(
                receipt_id=f"rcpt-omnipost-dry-{uuid.uuid4().hex[:10]}",
                clip_id=rendered_clip.clip_id,
                idempotency_key=idempotency_key,
                status="DRY_RUN_SIMULATED",
                timestamp=now_iso,
                target_mode="omnipost",
                dry_run=True,
                response_payload={
                    "simulated": True,
                    "target_platforms": target_platforms,
                    "title": candidate.hook_title,
                    "file_path": rendered_clip.file_path,
                },
            )
            self._persist_receipt(receipt)
            return receipt

        # 5. Live OmniPost Delivery
        title = candidate.hook_title or f"Short #{candidate.video_id}"
        caption_body = candidate.suggested_description or ""
        hashtags = "#shorts #viral #fyp"
        full_caption = f"{caption_body}\n\n{hashtags}".strip()

        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        upload_url = f"{self.base_url}/api/upload"

        try:
            if not os.path.exists(rendered_clip.file_path):
                raise FileNotFoundError(f"Rendered clip file not found: {rendered_clip.file_path}")

            with open(rendered_clip.file_path, "rb") as vf:
                files = {"file": (os.path.basename(rendered_clip.file_path), vf, "video/mp4")}
                data = {
                    "title": title,
                    "caption": full_caption,
                    "platforms": ",".join(target_platforms),
                    "mediaType": "video",
                    "status": "Published" if not scheduled_time else "Scheduled",
                }
                if scheduled_time:
                    data["scheduledDateTime"] = scheduled_time

                resp = requests.post(
                    upload_url,
                    headers=headers,
                    data=data,
                    files=files,
                    timeout=self.timeout,
                )

            if resp.status_code in (200, 201):
                resp_json = resp.json()
                receipt = HandoffReceipt(
                    receipt_id=f"rcpt-omnipost-{uuid.uuid4().hex[:10]}",
                    clip_id=rendered_clip.clip_id,
                    idempotency_key=idempotency_key,
                    status="DELIVERED",
                    timestamp=now_iso,
                    target_mode="omnipost",
                    dry_run=False,
                    response_payload=resp_json,
                )
                self._persist_receipt(receipt)
                return receipt
            else:
                err_text = resp.text[:500]
                logger.error(f"OmniPost returned error status {resp.status_code}: {err_text}")
                receipt = HandoffReceipt(
                    receipt_id=f"rcpt-omnipost-err-{uuid.uuid4().hex[:10]}",
                    clip_id=rendered_clip.clip_id,
                    idempotency_key=idempotency_key,
                    status="FAILED",
                    timestamp=now_iso,
                    target_mode="omnipost",
                    dry_run=False,
                    response_payload={"status_code": resp.status_code, "error": err_text},
                )
                self._persist_receipt(receipt)
                return receipt

        except Exception as exc:
            logger.error(f"Failed delivering clip to OmniPost: {exc}")
            receipt = HandoffReceipt(
                receipt_id=f"rcpt-omnipost-err-{uuid.uuid4().hex[:10]}",
                clip_id=rendered_clip.clip_id,
                idempotency_key=idempotency_key,
                status="FAILED",
                timestamp=now_iso,
                target_mode="omnipost",
                dry_run=False,
                response_payload={"exception": str(exc)},
            )
            self._persist_receipt(receipt)
            return receipt

    # Alias for convenience
    publish = publish_clip

    def _persist_receipt(self, receipt: HandoffReceipt) -> None:
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO publishing_receipts (
                        receipt_id, clip_id, idempotency_key, status, timestamp, target_mode, dry_run, response_payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(receipt_id) DO UPDATE SET
                        status=excluded.status,
                        response_payload_json=excluded.response_payload_json
                    """,
                    (
                        receipt.receipt_id,
                        receipt.clip_id,
                        receipt.idempotency_key,
                        receipt.status,
                        receipt.timestamp,
                        receipt.target_mode,
                        1 if receipt.dry_run else 0,
                        json.dumps(receipt.response_payload),
                    ),
                )
        finally:
            conn.close()

    def _get_receipt(self, idempotency_key: str) -> Optional[HandoffReceipt]:
        conn = self.db.get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT receipt_id, clip_id, idempotency_key, status, timestamp, target_mode, dry_run, response_payload_json
                FROM publishing_receipts WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return HandoffReceipt(
                receipt_id=row[0],
                clip_id=row[1],
                idempotency_key=row[2],
                status=row[3],
                timestamp=row[4],
                target_mode=row[5],
                dry_run=bool(row[6]),
                response_payload=json.loads(row[7]) if row[7] else {},
            )
        finally:
            conn.close()
