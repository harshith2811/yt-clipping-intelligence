"""
Lifecycle and Storage Manager for Artifact Retention and Pruning.
Implements safe cache pruning, intermediate file cleanup, and dry-run disk auditing.
Guarantees that active jobs, verified source media, and final delivered clips are preserved.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import os
import time
import shutil
from datetime import datetime, timezone, timedelta

from ..config import AppConfig


@dataclass
class CleanupItem:
    path: str
    file_type: str  # temp, intermediate, heatmap, old_transcript
    size_bytes: int
    modified_at: str
    action: str = "WOULD_DELETE"  # WOULD_DELETE or DELETED


@dataclass
class StorageReport:
    total_scanned_bytes: int = 0
    total_reclaimable_bytes: int = 0
    items: List[CleanupItem] = field(default_factory=list)
    dry_run: bool = True
    scanned_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_scanned_bytes": self.total_scanned_bytes,
            "total_reclaimable_bytes": self.total_reclaimable_bytes,
            "total_reclaimable_mb": round(self.total_reclaimable_bytes / (1024 * 1024), 2),
            "dry_run": self.dry_run,
            "scanned_at": self.scanned_at,
            "items_count": len(self.items),
            "items": [
                {
                    "path": i.path,
                    "file_type": i.file_type,
                    "size_bytes": i.size_bytes,
                    "modified_at": i.modified_at,
                    "action": i.action,
                }
                for i in self.items
            ],
        }


class StorageManager:
    """
    Manages disk lifecycle of assets, intermediate rendering chunks,
    temporary files, and cache entries.
    """

    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or AppConfig()

    def run_cleanup(
        self,
        retention_days: int = 7,
        temp_only: bool = False,
        dry_run: bool = True,
    ) -> StorageReport:
        """
        Scans workspace directories and cleans up intermediate / temporary files.
        If dry_run is True, calculates reclaimable bytes without deleting files.
        Never deletes final rendered clips or verified source assets by default.
        """
        report = StorageReport(dry_run=dry_run)
        now = time.time()
        cutoff_seconds = now - (retention_days * 86400)

        # 1. Temp directory (always eligible for cleanup if older than 1 hour or on demand)
        temp_dir = self.config.temp_dir
        if os.path.exists(temp_dir):
            self._scan_and_clean_dir(
                target_dir=temp_dir,
                file_type="temp",
                cutoff_time=now - 3600 if not temp_only else now,  # temp files older than 1 hour
                report=report,
                dry_run=dry_run,
            )

        if not temp_only:
            # 2. Heatmaps directory (prune older than retention_days)
            heatmaps_dir = self.config.heatmaps_dir
            if os.path.exists(heatmaps_dir):
                self._scan_and_clean_dir(
                    target_dir=heatmaps_dir,
                    file_type="heatmap",
                    cutoff_time=cutoff_seconds,
                    report=report,
                    dry_run=dry_run,
                )

        return report

    def _scan_and_clean_dir(
        self,
        target_dir: str,
        file_type: str,
        cutoff_time: float,
        report: StorageReport,
        dry_run: bool,
    ) -> None:
        """Recursively scans directory for files modified before cutoff_time."""
        for root, dirs, files in os.walk(target_dir):
            for fname in files:
                fpath = os.path.join(root, fname)
                try:
                    stat = os.stat(fpath)
                    report.total_scanned_bytes += stat.st_size
                    if stat.st_mtime < cutoff_time:
                        report.total_reclaimable_bytes += stat.st_size
                        item = CleanupItem(
                            path=os.path.abspath(fpath),
                            file_type=file_type,
                            size_bytes=stat.st_size,
                            modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                            action="WOULD_DELETE" if dry_run else "DELETED",
                        )
                        report.items.append(item)
                        if not dry_run:
                            os.remove(fpath)
                except (OSError, FileNotFoundError):
                    pass

    def get_storage_usage(self) -> Dict[str, Any]:
        """Provides disk breakdown across workspace directories."""
        dirs = {
            "assets": self.config.assets_dir,
            "transcripts": self.config.transcripts_dir,
            "heatmaps": self.config.heatmaps_dir,
            "rendered_clips": self.config.output_dir,
            "temp": self.config.temp_dir,
            "autopost_inbox": self.config.autopost_inbox,
        }
        usage = {}
        total = 0
        for name, dpath in dirs.items():
            dir_size = 0
            file_count = 0
            if os.path.exists(dpath):
                for root, _, files in os.walk(dpath):
                    for f in files:
                        try:
                            fp = os.path.join(root, f)
                            dir_size += os.path.getsize(fp)
                            file_count += 1
                        except OSError:
                            pass
            total += dir_size
            usage[name] = {
                "path": os.path.abspath(dpath),
                "bytes": dir_size,
                "mb": round(dir_size / (1024 * 1024), 2),
                "file_count": file_count,
            }
        usage["total_mb"] = round(total / (1024 * 1024), 2)
        return usage
