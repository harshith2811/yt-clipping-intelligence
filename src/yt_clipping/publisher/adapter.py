"""
Dual-Mode Autopost Integration Adapter & Resilient Webhook Dispatcher.
Delivers approved clips via Webhook/REST or Watched-Folder JSON manifests.
Enforces hard rights & QA gating, canonical SHA-256 idempotency,
concurrent worker transactional SQLite safety, bounded retry backoff, and Dead-Letter Queue (DLQ).
"""

from typing import Dict, Any, Optional, List
import os
import json
import uuid
import shutil
import sqlite3
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

from ..contracts.models import (
    RenderedClip,
    HighlightCandidate,
    RightsManifest,
    QAReport,
    HandoffReceipt,
    compute_canonical_idempotency_key,
)
from ..contracts.interfaces import HandoffPublisher
from ..orchestration.db import DatabaseManager


class DualModeAutopostPublisher(HandoffPublisher):
    """
    Adapter interfacing with the user's existing external autopost system.
    Guarantees no modifications to external code, enforces transactional idempotency,
    and runs in safe dry-run mode by default.
    """

    def __init__(
        self,
        mode: str = "watched_folder",  # "watched_folder" or "webhook"
        watched_dir: str = "data/autopost_inbox",
        webhook_url: Optional[str] = None,
        auth_token: Optional[str] = None,
        receipts_path: str = "data/handoffs/receipts.json",
        db_path: Optional[str] = None,
        max_retries: int = 3,
        base_backoff_seconds: float = 0.5,
    ):
        self.mode = mode
        self.watched_dir = watched_dir
        self.webhook_url = webhook_url
        self.auth_token = auth_token
        self.receipts_path = receipts_path
        if db_path is None:
            if receipts_path != "data/handoffs/receipts.json":
                db_path = os.path.splitext(receipts_path)[0] + ".db"
            else:
                db_path = "data/jobs.db"
        self.db = DatabaseManager(db_path)
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds

        os.makedirs(os.path.dirname(os.path.abspath(self.receipts_path)), exist_ok=True)
        if self.mode == "watched_folder":
            os.makedirs(self.watched_dir, exist_ok=True)

        # Migrate existing JSON receipts if any
        self._import_legacy_receipts()

    def _import_legacy_receipts(self) -> None:
        if os.path.exists(self.receipts_path):
            try:
                with open(self.receipts_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        r = HandoffReceipt.from_dict(item)
                        self._persist_receipt_to_db(r)
            except Exception:
                pass

    def compute_idempotency_key(
        self, candidate: HighlightCandidate, rights_manifest: RightsManifest
    ) -> str:
        """Computes deterministic canonical SHA-256 key from candidate boundaries and rights ID."""
        return compute_canonical_idempotency_key(
            video_id=candidate.video_id,
            start_seconds=candidate.start_seconds,
            end_seconds=candidate.end_seconds,
            rights_id=rights_manifest.rights_id,
        )

    def get_receipt_by_idempotency_key(self, idempotency_key: str) -> Optional[HandoffReceipt]:
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
            if row:
                payload = json.loads(row[7]) if row[7] else {}
                return HandoffReceipt(
                    receipt_id=row[0],
                    clip_id=row[1],
                    idempotency_key=row[2],
                    status=row[3],
                    timestamp=row[4],
                    target_mode=row[5],
                    dry_run=bool(row[6]),
                    response_payload=payload,
                )
            return None
        finally:
            conn.close()

    def _persist_receipt_to_db(self, receipt: HandoffReceipt) -> bool:
        """
        Inserts receipt into SQLite database atomically.
        Returns True if inserted, False if duplicate idempotency key exists.
        """
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO publishing_receipts (
                        receipt_id, clip_id, idempotency_key, status, timestamp, target_mode, dry_run, response_payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
            self._sync_json_export()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def _sync_json_export(self) -> None:
        """Exports receipts to JSON for legacy tool compatibility without being authoritative."""
        if not self.receipts_path:
            return
        conn = self.db.get_connection()
        try:
            cursor = conn.execute("SELECT receipt_id, clip_id, idempotency_key, status, timestamp, target_mode, dry_run, response_payload_json FROM publishing_receipts ORDER BY timestamp DESC LIMIT 200")
            receipts = []
            for row in cursor.fetchall():
                payload = json.loads(row[7]) if row[7] else {}
                receipts.append(
                    HandoffReceipt(
                        receipt_id=row[0],
                        clip_id=row[1],
                        idempotency_key=row[2],
                        status=row[3],
                        timestamp=row[4],
                        target_mode=row[5],
                        dry_run=bool(row[6]),
                        response_payload=payload,
                    ).to_dict()
                )
            temp_path = f"{self.receipts_path}.tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(receipts, f, indent=2)
            os.replace(temp_path, self.receipts_path)
        except Exception:
            pass
        finally:
            conn.close()

    def build_payload(
        self,
        rendered_clip: RenderedClip,
        candidate: HighlightCandidate,
        rights_manifest: RightsManifest,
        qa_report: QAReport,
        idempotency_key: str,
    ) -> Dict[str, Any]:
        ai_meta = getattr(candidate, "ai_metadata", {}) or {}
        tags = ai_meta.get("hashtags", ["Shorts", "Highlights", "AI"])
        return {
            "clip_id": rendered_clip.clip_id,
            "asset_path": rendered_clip.file_path,
            "title": candidate.hook_title,
            "description": candidate.suggested_description,
            "caption": ai_meta.get("caption", ""),
            "hooks": ai_meta.get("hooks", []),
            "tags": tags,
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

    def _record_dlq(self, clip_id: str, payload: Dict[str, Any], target_url: str, error: str) -> None:
        """Stores un-deliverable webhook payloads in Dead-Letter Queue."""
        conn = self.db.get_connection()
        now_iso = datetime.now(timezone.utc).isoformat()
        item_id = f"dlq-{uuid.uuid4().hex[:10]}"
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO webhook_dlq (
                        item_id, clip_id, payload_json, target_url, attempt_count, max_attempts, next_retry_at, last_error, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id,
                        clip_id,
                        json.dumps(payload),
                        target_url,
                        self.max_retries,
                        self.max_retries,
                        None,
                        error,
                        "EXHAUSTED",
                        now_iso,
                        now_iso,
                    ),
                )
        except Exception:
            pass
        finally:
            conn.close()

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

        # 1. Idempotency Check in durable SQLite storage
        existing = self.get_receipt_by_idempotency_key(idempotency_key)
        if existing:
            return HandoffReceipt(
                receipt_id=f"rcpt-dup-{existing.receipt_id}",
                clip_id=rendered_clip.clip_id,
                idempotency_key=idempotency_key,
                status="DUPLICATE_SKIPPED",
                timestamp=now_iso,
                target_mode=self.mode,
                dry_run=dry_run,
                response_payload={
                    "message": "Clip already delivered under idempotency key.",
                    "original_receipt": existing.receipt_id,
                    "original_status": existing.status,
                },
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

        # 4. Construct standardized payload
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
            if not self._persist_receipt_to_db(receipt):
                # Race condition: another thread/process inserted the same key
                existing = self.get_receipt_by_idempotency_key(idempotency_key)
                return HandoffReceipt(
                    receipt_id=f"rcpt-dup-{existing.receipt_id if existing else receipt_id}",
                    clip_id=rendered_clip.clip_id,
                    idempotency_key=idempotency_key,
                    status="DUPLICATE_SKIPPED",
                    timestamp=now_iso,
                    target_mode=self.mode,
                    dry_run=dry_run,
                    response_payload={"message": "Concurrent duplicate skipped."},
                )
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
            self._persist_receipt_to_db(receipt)
            return receipt

        elif self.mode == "webhook":
            if not self.webhook_url:
                receipt = HandoffReceipt(
                    receipt_id=receipt_id,
                    clip_id=rendered_clip.clip_id,
                    idempotency_key=idempotency_key,
                    status="FAILED",
                    timestamp=now_iso,
                    target_mode="webhook",
                    dry_run=False,
                    response_payload={"reason": "Webhook URL is not configured."},
                )
                self._record_dlq(rendered_clip.clip_id, payload, "", "Webhook URL not configured.")
                return receipt

            headers = {
                "Content-Type": "application/json",
                "X-Idempotency-Key": idempotency_key,
                "User-Agent": "Antigravity-YT-Clipping/1.0",
            }
            if self.auth_token:
                headers["Authorization"] = f"Bearer {self.auth_token}"

            status = "FAILED"
            response_payload = {}
            last_error = ""

            # Exponential backoff retry loop
            for attempt in range(1, self.max_retries + 1):
                try:
                    req = urllib.request.Request(
                        self.webhook_url,
                        data=json.dumps(payload).encode("utf-8"),
                        headers=headers,
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        http_code = resp.getcode()
                        body = resp.read().decode("utf-8", errors="replace")
                        if 200 <= http_code < 300:
                            status = "DELIVERED"
                            response_payload = {
                                "webhook_url": self.webhook_url,
                                "http_status": http_code,
                                "response": body[:500],
                                "attempts": attempt,
                            }
                            break
                        else:
                            last_error = f"HTTP {http_code}: {body[:200]}"
                except urllib.error.HTTPError as he:
                    last_error = f"HTTPError {he.code}: {he.reason}"
                    if 400 <= he.code < 500 and he.code != 429:
                        # Client error (e.g. 400, 401, 403, 404): non-retryable
                        break
                except Exception as ex:
                    last_error = f"RequestError: {str(ex)}"

                if attempt < self.max_retries:
                    backoff = self.base_backoff_seconds * (2 ** (attempt - 1))
                    time.sleep(backoff)

            if status != "DELIVERED":
                response_payload = {
                    "webhook_url": self.webhook_url,
                    "error": last_error,
                    "attempts": self.max_retries,
                }
                # Register failed payload in Dead Letter Queue
                self._record_dlq(rendered_clip.clip_id, payload, self.webhook_url, last_error)

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
                self._persist_receipt_to_db(receipt)
            return receipt

        raise ValueError(f"Unknown publisher mode: {self.mode}")

    def list_dlq_items(self) -> List[Dict[str, Any]]:
        """Retrieves dead-letter queue records for operator inspection."""
        conn = self.db.get_connection()
        try:
            cursor = conn.execute("SELECT item_id, clip_id, target_url, attempt_count, last_error, status, created_at FROM webhook_dlq ORDER BY created_at DESC LIMIT 50")
            items = []
            for row in cursor.fetchall():
                items.append({
                    "item_id": row[0],
                    "clip_id": row[1],
                    "target_url": row[2],
                    "attempt_count": row[3],
                    "last_error": row[4],
                    "status": row[5],
                    "created_at": row[6],
                })
            return items
        finally:
            conn.close()

    def retry_dlq_item(self, item_id: str) -> bool:
        """Attempts immediate re-delivery for a dead-letter queue item."""
        conn = self.db.get_connection()
        try:
            cursor = conn.execute(
                "SELECT payload_json, target_url, attempt_count FROM webhook_dlq WHERE item_id = ?",
                (item_id,),
            )
            row = cursor.fetchone()
            if not row:
                return False

            payload_json, target_url, attempt_count = row
            headers = {"Content-Type": "application/json", "User-Agent": "Antigravity-Publisher/1.0"}
            if self.auth_token:
                headers["Authorization"] = f"Bearer {self.auth_token}"

            req = urllib.request.Request(
                target_url,
                data=payload_json.encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                if 200 <= resp.getcode() < 300:
                    with conn:
                        conn.execute(
                            "UPDATE webhook_dlq SET status = 'RESOLVED', updated_at = ? WHERE item_id = ?",
                            (datetime.now(timezone.utc).isoformat(), item_id),
                        )
                    return True
        except Exception as e:
            with conn:
                conn.execute(
                    "UPDATE webhook_dlq SET attempt_count = attempt_count + 1, last_error = ?, updated_at = ? WHERE item_id = ?",
                    (str(e), datetime.now(timezone.utc).isoformat(), item_id),
                )
        finally:
            conn.close()
        return False
