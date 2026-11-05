"""
Durable Project and Clip Sidecar Storage Service.
Provides atomic disk persistence, project lifecycle tracking, clip sidecars with full AI intelligence,
automatic reconciliation across restarts, and backward compatibility with data/rendered_clips.
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
import os
import json
import logging
import hashlib
import glob

from ..discovery.video_metadata import EnrichedVideoInfo
from ..scoring.caption_synthesizer import ShortCaptionPackage, ClipIntelligence

logger = logging.getLogger(__name__)


@dataclass
class ClipSidecarRecord:
    """
    Comprehensive persistent sidecar record for an exported vertical Short.
    Saved atomically as clip_<id>.json beside the MP4.
    """
    clip_id: str
    project_id: str
    video_id: str
    file_path: str
    relative_url: str
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    score: float
    candidate_data: Dict[str, Any] = field(default_factory=dict)
    source_metadata: Dict[str, Any] = field(default_factory=dict)
    intelligence: Dict[str, Any] = field(default_factory=dict)
    caption_package: Dict[str, Any] = field(default_factory=dict)
    render_settings: Dict[str, Any] = field(default_factory=dict)
    file_size_bytes: int = 0
    file_hash: str = ""
    render_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    qa_report: Optional[Dict[str, Any]] = None
    status: str = "COMPLETED"
    error_details: Optional[str] = None
    thumbnail_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ClipSidecarRecord:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ProjectRecord:
    """
    Persistent project descriptor tracking source video metadata and exported clips.
    """
    project_id: str
    video_id: str
    title: str
    canonical_url: str
    source_metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    clips_count: int = 0
    status: str = "ACTIVE"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProjectRecord:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class ProjectStore:
    """
    Manages persistent filesystem storage for projects, sidecar JSONs, and media assets.
    Guarantees atomic file writes and crash resilience.
    """

    def __init__(self, base_data_dir: str = "data"):
        self.base_data_dir = os.path.abspath(base_data_dir)
        self.projects_dir = os.path.join(self.base_data_dir, "projects")
        self.rendered_clips_dir = os.path.join(self.base_data_dir, "rendered_clips")
        os.makedirs(self.projects_dir, exist_ok=True)
        os.makedirs(self.rendered_clips_dir, exist_ok=True)

    def get_project_dir(self, project_id: str) -> str:
        clean_name = project_id if project_id.startswith("project_") else f"project_{project_id}"
        pdir = os.path.join(self.projects_dir, clean_name)
        os.makedirs(pdir, exist_ok=True)
        os.makedirs(os.path.join(pdir, "clips"), exist_ok=True)
        return pdir

    def create_or_get_project(
        self,
        video_id: str,
        source_metadata: Optional[EnrichedVideoInfo] = None,
    ) -> ProjectRecord:
        """Finds an existing project for a video_id or instantiates a new one."""
        project_id = f"proj_{video_id}"
        project_path = os.path.join(self.get_project_dir(project_id), "project.json")

        if os.path.exists(project_path):
            try:
                with open(project_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return ProjectRecord.from_dict(data)
            except Exception as e:
                logger.warning(f"Corrupted project file {project_path}: {e}. Rebuilding...")

        title = source_metadata.title if source_metadata else f"Project {video_id}"
        canonical_url = (
            source_metadata.canonical_url
            if source_metadata
            else f"https://www.youtube.com/watch?v={video_id}"
        )
        meta_dict = source_metadata.to_dict() if source_metadata else {"video_id": video_id}

        proj = ProjectRecord(
            project_id=project_id,
            video_id=video_id,
            title=title,
            canonical_url=canonical_url,
            source_metadata=meta_dict,
        )
        self.save_project(proj)
        return proj

    def save_project(self, project: ProjectRecord) -> None:
        """Atomically persists project.json."""
        project.updated_at = datetime.now(timezone.utc).isoformat()
        pdir = self.get_project_dir(project.project_id)
        path = os.path.join(pdir, "project.json")
        self._write_json_atomic(path, project.to_dict())

    def get_project(self, project_id: str) -> Optional[ProjectRecord]:
        """Loads a project record from disk, matching direct or prefixed project directories."""
        clean_id = project_id
        if clean_id.startswith("project_"):
            clean_id = clean_id[8:]
        if clean_id.startswith("proj_"):
            clean_id = clean_id[5:]

        candidate_dirs = [
            os.path.join(self.projects_dir, project_id),
            os.path.join(self.projects_dir, f"project_{project_id}"),
            os.path.join(self.projects_dir, f"project_proj_{clean_id}"),
            os.path.join(self.projects_dir, f"project_{clean_id}"),
            os.path.join(self.projects_dir, f"proj_{clean_id}"),
        ]
        target_dir = next((d for d in candidate_dirs if os.path.isdir(d)), None)
        if not target_dir:
            return None

        path = os.path.join(target_dir, "project.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return ProjectRecord.from_dict(json.load(f))
        except Exception as e:
            logger.error(f"Failed to read project {path}: {e}")
            return None

    def list_projects(self) -> List[ProjectRecord]:
        """Lists all projects ordered by most recent update."""
        projects = []
        for pdir in glob.glob(os.path.join(self.projects_dir, "project_*")):
            proj_file = os.path.join(pdir, "project.json")
            if os.path.exists(proj_file):
                try:
                    with open(proj_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    # Recompute actual clips count
                    clips_dir = os.path.join(pdir, "clips")
                    actual_count = len(glob.glob(os.path.join(clips_dir, "*.json")))
                    data["clips_count"] = actual_count
                    projects.append(ProjectRecord.from_dict(data))
                except Exception as e:
                    logger.warning(f"Error loading project {proj_file}: {e}")

        projects.sort(key=lambda p: p.updated_at, reverse=True)
        return projects

    def save_clip_sidecar(self, sidecar: ClipSidecarRecord) -> str:
        """
        Atomically saves the sidecar JSON file.
        Writes to project clips dir and links/mirrors in rendered_clips_dir.
        """
        pdir = self.get_project_dir(sidecar.project_id)
        base_cid = sidecar.clip_id[5:] if sidecar.clip_id.startswith("clip_") else sidecar.clip_id
        sidecar_path = os.path.join(pdir, "clips", f"clip_{base_cid}.json")
        self._write_json_atomic(sidecar_path, sidecar.to_dict())

        # Also save a mirror sidecar in rendered_clips_dir for direct file lookup
        mirror_name = os.path.splitext(os.path.basename(sidecar.file_path))[0]
        mirror_path = os.path.join(self.rendered_clips_dir, f"{mirror_name}.json")
        try:
            self._write_json_atomic(mirror_path, sidecar.to_dict())
        except Exception:
            pass

        # Update parent project clip count
        proj = self.get_project(sidecar.project_id)
        if proj:
            self.save_project(proj)

        return sidecar_path

    def get_clip_sidecar(self, clip_id: str) -> Optional[ClipSidecarRecord]:
        """Retrieves clip sidecar by clip_id with robust fallback patterns."""
        base_cid = clip_id[5:] if clip_id.startswith("clip_") else clip_id

        # 1. Search in projects directory
        candidate_patterns = [
            os.path.join(self.projects_dir, "*", "clips", f"clip_{base_cid}.json"),
            os.path.join(self.projects_dir, "*", "clips", f"{clip_id}.json"),
            os.path.join(self.projects_dir, "*", "clips", f"clip_{clip_id}.json"),
        ]
        for pattern in candidate_patterns:
            matches = glob.glob(pattern)
            if matches:
                try:
                    with open(matches[0], "r", encoding="utf-8") as f:
                        return ClipSidecarRecord.from_dict(json.load(f))
                except Exception as e:
                    logger.warning(f"Corrupted sidecar {matches[0]}: {e}")

        # 2. Search in rendered_clips directory
        mirror_patterns = [
            os.path.join(self.rendered_clips_dir, f"*{base_cid}*.json"),
            os.path.join(self.rendered_clips_dir, f"*{clip_id}*.json"),
        ]
        for mp in mirror_patterns:
            mirror_matches = glob.glob(mp)
            if mirror_matches:
                try:
                    with open(mirror_matches[0], "r", encoding="utf-8") as f:
                        return ClipSidecarRecord.from_dict(json.load(f))
                except Exception as e:
                    logger.warning(f"Corrupted mirror sidecar {mirror_matches[0]}: {e}")

        return None

    def list_clips(self, project_id: Optional[str] = None) -> List[ClipSidecarRecord]:
        """
        Returns all persisted clips, combining project sidecars and legacy rendered_clips.
        Reconciles missing media and filters duplicates.
        """
        seen_clips = {}

        # 1. Search projects directory
        if project_id:
            proj = self.get_project(project_id)
            if proj:
                pdir = self.get_project_dir(proj.project_id)
                search_paths = [os.path.join(pdir, "clips", "*.json")]
            else:
                clean_id = project_id.replace("project_", "").replace("proj_", "")
                search_paths = [
                    os.path.join(self.projects_dir, f"project_*proj_{clean_id}*", "clips", "*.json"),
                    os.path.join(self.projects_dir, f"project_*{clean_id}*", "clips", "*.json"),
                ]
        else:
            search_paths = [os.path.join(self.projects_dir, "*", "clips", "*.json")]

        sidecar_files = []
        for sp in search_paths:
            sidecar_files.extend(glob.glob(sp))

        for s_file in set(sidecar_files):
            try:
                with open(s_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                record = ClipSidecarRecord.from_dict(data)
                # Check media existence on disk
                if not os.path.exists(record.file_path):
                    # Check if present in rendered_clips_dir
                    alt_path = os.path.join(self.rendered_clips_dir, os.path.basename(record.file_path))
                    if os.path.exists(alt_path):
                        record.file_path = alt_path
                    else:
                        record.status = "MISSING_MEDIA"
                seen_clips[record.clip_id] = record
            except Exception as e:
                logger.warning(f"Error reading sidecar {s_file}: {e}")

        # 2. Scan rendered_clips directory for legacy clips without project sidecar
        if not project_id:
            for mp4_file in glob.glob(os.path.join(self.rendered_clips_dir, "*.mp4")):
                fname = os.path.basename(mp4_file)
                base_name = os.path.splitext(fname)[0]
                cid = base_name.replace("clip_", "")
                if cid not in seen_clips and fname not in [os.path.basename(c.file_path) for c in seen_clips.values()]:
                    # Check for companion JSON
                    json_path = os.path.join(self.rendered_clips_dir, f"{base_name}.json")
                    if os.path.exists(json_path):
                        try:
                            with open(json_path, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            seen_clips[cid] = ClipSidecarRecord.from_dict(data)
                            continue
                        except Exception:
                            pass
                    # Synthesize basic sidecar for legacy unattached clip
                    size = os.path.getsize(mp4_file)
                    seen_clips[cid] = ClipSidecarRecord(
                        clip_id=cid,
                        project_id="legacy",
                        video_id="unknown",
                        file_path=mp4_file,
                        relative_url=f"/clips/{fname}",
                        start_seconds=0.0,
                        end_seconds=0.0,
                        duration_seconds=0.0,
                        score=75.0,
                        file_size_bytes=size,
                        render_timestamp=datetime.fromtimestamp(os.path.getmtime(mp4_file), timezone.utc).isoformat(),
                        status="COMPLETED",
                    )

        # Sort clips by render timestamp descending
        result = list(seen_clips.values())
        result.sort(key=lambda c: c.render_timestamp, reverse=True)
        return result

    def _write_json_atomic(self, path: str, data: Dict[str, Any]) -> None:
        """Writes JSON to a temporary file and atomically replaces destination."""
        tmp_path = f"{path}.tmp.{os.getpid()}"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            raise
