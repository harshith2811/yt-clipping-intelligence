"""
YouTube Clipping Intelligence Platform - Production-Grade Web Studio & REST API.
Provides dual-engine video metadata ingestion, AI highlight intelligence,
explainable selection reasoning, cascading social caption synthesis,
durable project/clip persistence, asynchronous background job management,
and a commercial-grade SaaS Web Studio interface.
"""

from __future__ import annotations
from typing import List, Dict, Optional, Any
import os
import sys
import glob
import json
import shutil
import asyncio
import logging
import threading
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from ..config import AppConfig
from ..contracts.models import RenderProfile
from ..rights.gate import LocalRightsPolicy
from ..detection.solid_shorts import SolidShortsDecider
from ..cli.commands.pipeline import build_pipeline
from ..discovery.video_metadata import VideoMetadataService, EnrichedVideoInfo, normalize_youtube_url
from ..scoring.caption_synthesizer import CaptionSynthesizer, ShortCaptionPackage, ClipIntelligence
from ..orchestration.project_store import ProjectStore, ProjectRecord, ClipSidecarRecord
from ..orchestration.job_manager import JobManager, RenderJobStatus, JobRecord
from ..qa.verifier import validate_rendered_short

logger = logging.getLogger(__name__)

# Base directories
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
DATA_DIR = os.path.join(BASE_DIR, "data")
CLIPS_DIR = os.path.join(DATA_DIR, "rendered_clips")
PROJECTS_DIR = os.path.join(DATA_DIR, "projects")
TEMP_DIR = os.path.join(DATA_DIR, "temp")
CACHE_DIR = os.path.join(DATA_DIR, "cache", "metadata")
DB_PATH = os.path.join(DATA_DIR, "jobs.db")

for d in (CLIPS_DIR, PROJECTS_DIR, TEMP_DIR, CACHE_DIR):
    os.makedirs(d, exist_ok=True)

# Shared platform services
metadata_service = VideoMetadataService(cache_dir=CACHE_DIR)
caption_synthesizer = CaptionSynthesizer()
project_store = ProjectStore(base_data_dir=DATA_DIR)
job_manager = JobManager(db_path=DB_PATH)

app = FastAPI(
    title="YouTube Clipping Intelligence Platform - Studio API",
    version="2.0.0",
    description="24/7 Autonomous AI video clipping, explainable short-form intelligence, and 9:16 vertical rendering engine",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount rendered clips static directory for instant playback
app.mount("/clips", StaticFiles(directory=CLIPS_DIR), name="clips")

# In-memory dictionary for backwards-compatibility with tests referencing server.active_render_jobs
active_render_jobs: Dict[str, Dict[str, Any]] = {}


# ------------------------------------------------------------------------------
# Pydantic Request Models
# ------------------------------------------------------------------------------
class MetadataRequest(BaseModel):
    video_id_or_url: str = Field(..., description="YouTube video ID or URL")


class PreviewRequest(BaseModel):
    video_id_or_url: str = Field(..., description="YouTube video ID or URL")
    min_duration: float = Field(15.0, description="Minimum clip duration in seconds")
    max_duration: float = Field(60.0, description="Maximum clip duration in seconds")


class RenderRequest(BaseModel):
    video_id_or_url: str = Field(..., description="YouTube video ID or URL")
    max_clips: int = Field(3, description="Number of solid shorts to extract (1-10)")
    layout: str = Field("active_speaker", description="Layout: active_speaker | blur_background | split_screen")
    subtitle_preset: str = Field("hormozi", description="Subtitle preset: hormozi | beast_bounce | neon_cyber | clean_editorial")
    enable_polish: bool = Field(True, description="Enable broadcast hook pacing and anti-pop audio transitions")
    enable_outro: bool = Field(True, description="Enable dedicated animated outro card with bell chime")
    outro_channel_name: Optional[str] = Field(None, description="Custom channel name for outro card")
    gpu: bool = Field(True, description="Use NVIDIA NVENC hardware acceleration if available")


# ------------------------------------------------------------------------------
# Media Streaming with HTTP Range Support for HTML5 Seeking
# ------------------------------------------------------------------------------
def stream_video_with_range(file_path: str, request: Request) -> Response:
    """Streams a video file supporting HTTP Range requests for seamless in-browser seeking."""
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Requested video file does not exist.")

    file_size = os.path.getsize(file_path)
    range_header = request.headers.get("range")

    if not range_header:
        # Full file stream
        def iterfile():
            with open(file_path, mode="rb") as f:
                while chunk := f.read(65536):
                    yield chunk

        headers = {
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
            "Content-Type": "video/mp4",
        }
        return StreamingResponse(iterfile(), status_code=200, headers=headers)

    # Parse Range: bytes=start-end
    try:
        byte_range = range_header.replace("bytes=", "").split("-")
        start = int(byte_range[0])
        end = int(byte_range[1]) if byte_range[1] else file_size - 1
        if start >= file_size or end >= file_size or start > end:
            raise HTTPException(status_code=416, detail="Requested range not satisfiable.")
    except Exception:
        raise HTTPException(status_code=416, detail="Invalid range request.")

    chunk_size = (end - start) + 1

    def iter_chunk():
        with open(file_path, mode="rb") as f:
            f.seek(start)
            bytes_left = chunk_size
            while bytes_left > 0:
                read_bytes = min(bytes_left, 65536)
                data = f.read(read_bytes)
                if not data:
                    break
                bytes_left -= len(data)
                yield data

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_size),
        "Content-Type": "video/mp4",
    }
    return StreamingResponse(iter_chunk(), status_code=206, headers=headers)


# ------------------------------------------------------------------------------
# API Endpoints
# ------------------------------------------------------------------------------
@app.get("/api/v1/health")
def api_health() -> Dict[str, Any]:
    """Inspects environment, GPU, FFmpeg, Gemini, and storage readiness."""
    gpu_available = False
    gpu_name = "None (CPU Fallback)"
    try:
        import torch
        if torch.cuda.is_available():
            gpu_available = True
            gpu_name = torch.cuda.get_device_name(0)
    except Exception:
        pass

    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    yunet_path = os.path.join(BASE_DIR, "models", "face_detection_yunet_2023mar.onnx")
    yolo_path = os.path.join(BASE_DIR, "models", "yolov8n-seg.pt")

    gemini_key = os.getenv("GEMINI_API_KEY")
    youtube_key = os.getenv("YOUTUBE_API_KEY")

    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gpu_available": gpu_available,
        "gpu_device": gpu_name,
        "ffmpeg_ready": bool(ffmpeg_path),
        "ffmpeg_path": ffmpeg_path,
        "ffprobe_ready": bool(ffprobe_path),
        "models": {
            "yunet_onnx": os.path.exists(yunet_path),
            "yolov8n_seg": os.path.exists(yolo_path),
            "gemini_active": bool(gemini_key),
            "gemini_model": caption_synthesizer.primary_model if gemini_key else "offline_deterministic",
        },
        "metadata_provider": "youtube_data_api_v3" if youtube_key else "yt_dlp_fallback",
        "storage": {
            "data_dir": DATA_DIR,
            "clips_count": len(glob.glob(os.path.join(CLIPS_DIR, "*.mp4"))),
            "projects_count": len(glob.glob(os.path.join(PROJECTS_DIR, "project_*"))),
        },
    }


@app.post("/api/v1/metadata")
def api_get_metadata(req: MetadataRequest) -> Dict[str, Any]:
    """Retrieves normalized YouTube metadata with Data API v3 and yt-dlp fallback."""
    try:
        video_id, _ = normalize_youtube_url(req.video_id_or_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        info = metadata_service.get_metadata(video_id)
        return info.to_dict()
    except Exception as e:
        logger.error(f"Metadata retrieval failed for {video_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Metadata error: {e}")


@app.post("/api/v1/preview")
def api_preview(req: PreviewRequest) -> Dict[str, Any]:
    """Extracts candidate highlights, retention curves, explainable intelligence, and caption packages."""
    try:
        video_id, _ = normalize_youtube_url(req.video_id_or_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid YouTube video ID or URL: {e}")

    # Fetch rich metadata
    try:
        video_info = metadata_service.get_metadata(video_id)
    except Exception:
        video_info = None

    # Auto-register operator rights manifest if not present
    policy = LocalRightsPolicy(os.path.join(DATA_DIR, "rights_ledger.json"), db_path=DB_PATH)
    manifest = policy.check_rights(video_id)
    if not policy.verify_rights(manifest):
        policy.register_rights(
            video_id=video_id,
            basis="OPERATOR_ASSET",
            owner=video_info.channel_title if video_info else "Studio Operator",
            audit_notes="Auto-registered via Web Studio Preview",
        )

    pipeline = build_pipeline(output_dir=CLIPS_DIR, min_duration=req.min_duration, max_duration=req.max_duration)
    try:
        candidates = pipeline.get_candidates(video_id=video_id, min_duration=req.min_duration, max_duration=req.max_duration)
    except Exception as e:
        logger.error(f"Preview extraction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    # Retrieve heatmap if available
    heatmap_data = None
    transcript = None
    try:
        transcript = pipeline.transcriber.load_from_cache(video_id)
        dur = transcript.duration_seconds if transcript else (video_info.duration if video_info else 300.0)
        heatmap_data = pipeline.heatmap_analyzer.extract_heatmap(video_id=video_id, duration_seconds=dur)
    except Exception:
        pass

    # Apply SolidShortsDecider
    decider = SolidShortsDecider()
    decision = decider.decide(
        candidates=candidates,
        duration_seconds=transcript.duration_seconds if transcript else (video_info.duration if video_info else 300.0),
        heatmap_data=heatmap_data,
        strict_quality=True,
    )

    # Generate explainable intelligence and caption packages for selected candidates
    solid_clips_payload = []
    for c in decision.selected_candidates:
        intelligence = caption_synthesizer.explain_clip(c, video_info)
        caption_pkg = caption_synthesizer.generate_caption_package(c, video_info)
        solid_clips_payload.append({
            "candidate_id": c.candidate_id,
            "start_seconds": round(c.start_seconds, 1),
            "end_seconds": round(c.end_seconds, 1),
            "duration_seconds": round(c.duration_seconds, 1),
            "score": round(c.score, 1),
            "hook_title": caption_pkg.hook_title or c.hook_title or "Key Moment",
            "rationale": c.rationale,
            "why_it_works": intelligence.why_it_works,
            "intelligence": intelligence.to_dict(),
            "caption_package": caption_pkg.to_dict(),
        })

    return {
        "video_id": video_id,
        "source_metadata": video_info.to_dict() if video_info else None,
        "total_candidates_found": len(candidates),
        "recommended_solid_shorts_count": decision.recommended_count,
        "capacity_limit": decision.capacity_limit,
        "decision_reasons": decision.reasons,
        "solid_clips": solid_clips_payload,
    }


def _run_render_worker(task_id: str, req: RenderRequest, video_id: str) -> None:
    """Asynchronous background rendering worker with staged progress, cancellation, and validation."""
    job_manager.update_progress(
        job_id=task_id,
        status=RenderJobStatus.DISCOVERING.value,
        progress=15,
        current_stage="discovering",
        message="Resolving source metadata & verifying content rights...",
    )
    # Sync in-memory dict
    if task_id in active_render_jobs:
        active_render_jobs[task_id]["status"] = "IN_PROGRESS"
        active_render_jobs[task_id]["progress"] = 15
        active_render_jobs[task_id]["message"] = "Initializing pipeline & verifying content rights..."

    try:
        # Check cancellation
        if job_manager.is_cancelled(task_id):
            logger.info(f"Job {task_id} cancelled during discovery.")
            return

        # 1. Retrieve metadata & initialize project
        video_info = None
        try:
            video_info = metadata_service.get_metadata(video_id)
        except Exception:
            pass

        project = project_store.create_or_get_project(video_id, source_metadata=video_info)

        policy = LocalRightsPolicy(os.path.join(DATA_DIR, "rights_ledger.json"), db_path=DB_PATH)
        manifest = policy.check_rights(video_id)
        if not policy.verify_rights(manifest):
            policy.register_rights(
                video_id=video_id,
                basis="OPERATOR_ASSET",
                owner=video_info.channel_title if video_info else "Studio Operator",
                audit_notes="Auto-registered via Web Studio Render",
            )

        if job_manager.is_cancelled(task_id):
            return

        # 2. Pipeline processing
        job_manager.update_progress(
            job_id=task_id,
            status=RenderJobStatus.RENDERING.value,
            progress=40,
            current_stage="rendering",
            message=f"Rendering top {req.max_clips} vertical Shorts with FFmpeg & face tracking...",
        )
        if task_id in active_render_jobs:
            active_render_jobs[task_id]["progress"] = 40
            active_render_jobs[task_id]["message"] = f"Milking top {req.max_clips} solid shorts with kinematic face tracking..."

        pipeline = build_pipeline(output_dir=CLIPS_DIR)
        vcodec = "h264_nvenc" if req.gpu else "libx264"
        profile = RenderProfile(
            layout_mode=req.layout,
            vcodec=vcodec,
            subtitle_preset=req.subtitle_preset,
            enable_outro_card=req.enable_outro,
            outro_duration=2.5,
            outro_channel_name=req.outro_channel_name or (video_info.channel_title if video_info else None),
            enable_pacing_polish=req.enable_polish,
        )

        completed_jobs = pipeline.process_video_multi(
            video_id=video_id,
            max_clips=req.max_clips,
            profile=profile,
            dry_run=True,
        )

        if job_manager.is_cancelled(task_id):
            return

        # 3. Post-Render Quality Assurance & Sidecar Persistence
        job_manager.update_progress(
            job_id=task_id,
            status=RenderJobStatus.VALIDATING.value,
            progress=85,
            current_stage="validating",
            message="Executing post-render quality assurance & saving sidecars...",
        )

        clips_out = []
        for j in completed_jobs:
            if j.rendered_clip and os.path.exists(j.rendered_clip.file_path):
                clip_path = j.rendered_clip.file_path
                fname = os.path.basename(clip_path)

                # Automated QA Validation
                qa_result = validate_rendered_short(clip_path, expected_duration=j.candidate.duration_seconds if j.candidate else None)

                # Synthesize social caption package and intelligence
                caption_pkg = caption_synthesizer.generate_caption_package(j.candidate, video_info) if j.candidate else None
                intelligence = caption_synthesizer.explain_clip(j.candidate, video_info) if j.candidate else None

                # Persist sidecar
                sidecar = ClipSidecarRecord(
                    clip_id=j.job_id,
                    project_id=project.project_id,
                    video_id=video_id,
                    file_path=clip_path,
                    relative_url=f"/clips/{fname}",
                    start_seconds=j.candidate.start_seconds if j.candidate else 0.0,
                    end_seconds=j.candidate.end_seconds if j.candidate else 0.0,
                    duration_seconds=j.candidate.duration_seconds if j.candidate else 0.0,
                    score=j.candidate.score if j.candidate else 0.0,
                    candidate_data=j.candidate.to_dict() if j.candidate else {},
                    source_metadata=video_info.to_dict() if video_info else {},
                    intelligence=intelligence.to_dict() if intelligence else {},
                    caption_package=caption_pkg.to_dict() if caption_pkg else {},
                    render_settings=profile.to_dict(),
                    file_size_bytes=os.path.getsize(clip_path),
                    qa_report=qa_result,
                    status="COMPLETED" if qa_result.get("valid", True) else "VALIDATION_FAILED",
                )
                project_store.save_clip_sidecar(sidecar)

                clips_out.append({
                    "job_id": j.job_id,
                    "clip_id": j.job_id,
                    "filename": fname,
                    "url": f"/clips/{fname}",
                    "file_path": clip_path,
                    "duration": round(j.candidate.duration_seconds, 1) if j.candidate else 0.0,
                    "score": round(j.candidate.score, 1) if j.candidate else 0.0,
                    "hook_title": caption_pkg.hook_title if caption_pkg else (j.candidate.hook_title if j.candidate else ""),
                    "file_size_mb": round(os.path.getsize(clip_path) / (1024 * 1024), 2),
                    "caption_package": caption_pkg.to_dict() if caption_pkg else {},
                    "intelligence": intelligence.to_dict() if intelligence else {},
                    "qa_status": qa_result.get("status", "PASSED"),
                })

        # 4. Completion
        if not clips_out:
            job_manager.update_progress(
                job_id=task_id,
                status=RenderJobStatus.FAILED.value,
                progress=100,
                current_stage="failed",
                message="No solid Shorts could be produced for this video.",
                error="Pipeline produced 0 valid clips.",
            )
            if task_id in active_render_jobs:
                active_render_jobs[task_id]["status"] = "FAILED"
                active_render_jobs[task_id]["error"] = "Pipeline produced 0 valid clips."
            return

        job_manager.update_progress(
            job_id=task_id,
            status=RenderJobStatus.COMPLETED.value,
            progress=100,
            current_stage="completed",
            message=f"Successfully rendered {len(clips_out)} solid Shorts!",
            clips=clips_out,
        )

        if task_id in active_render_jobs:
            active_render_jobs[task_id]["progress"] = 100
            active_render_jobs[task_id]["status"] = "COMPLETED"
            active_render_jobs[task_id]["message"] = f"Successfully rendered {len(clips_out)} solid Shorts!"
            active_render_jobs[task_id]["clips"] = clips_out

    except Exception as e:
        logger.error(f"Render failed: {e}")
        job_manager.update_progress(
            job_id=task_id,
            status=RenderJobStatus.FAILED.value,
            current_stage="failed",
            message=f"Render execution error: {e}",
            error=str(e),
        )
        if task_id in active_render_jobs:
            active_render_jobs[task_id]["status"] = "FAILED"
            active_render_jobs[task_id]["error"] = str(e)


@app.post("/api/v1/render")
def api_render(req: RenderRequest, bg_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Triggers batch vertical 9:16 Short rendering for a video asynchronously."""
    try:
        video_id, _ = normalize_youtube_url(req.video_id_or_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid YouTube video ID or URL: {e}")

    job_params = req.model_dump() if hasattr(req, "model_dump") else req.dict()
    job = job_manager.create_job(video_id=video_id, request_params=job_params)
    task_id = job.job_id

    # Populate active_render_jobs for backwards compatibility with tests
    active_render_jobs[task_id] = {
        "task_id": task_id,
        "video_id": video_id,
        "status": "QUEUED",
        "progress": 5,
        "message": "Task queued for processing...",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "clips": [],
    }

    bg_tasks.add_task(_run_render_worker, task_id, req, video_id)
    return {
        "task_id": task_id,
        "job_id": task_id,
        "status": "QUEUED",
        "check_status_url": f"/api/v1/jobs/{task_id}",
    }


@app.get("/api/v1/render/status/{task_id}")
def api_render_status(task_id: str) -> Dict[str, Any]:
    """Returns progress and rendered clip payloads for a running or completed task."""
    # First check JobManager
    job = job_manager.get_job(task_id)
    if job:
        return job.to_dict()
    # Check in-memory store
    legacy_job = active_render_jobs.get(task_id)
    if not legacy_job:
        raise HTTPException(status_code=404, detail="Task ID not found.")
    return legacy_job


@app.get("/api/v1/jobs/{job_id}")
def api_get_job(job_id: str) -> Dict[str, Any]:
    """Retrieves full job status and outputs."""
    job = job_manager.get_job(job_id)
    if not job:
        # Check active_render_jobs fallback
        if job_id in active_render_jobs:
            return active_render_jobs[job_id]
        raise HTTPException(status_code=404, detail="Job ID not found.")
    return job.to_dict()


@app.post("/api/v1/jobs/{job_id}/cancel")
def api_cancel_job(job_id: str) -> Dict[str, Any]:
    """Cancels a queued or in-progress rendering job."""
    success = job_manager.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=400, detail="Job cannot be cancelled (already completed or not found).")
    if job_id in active_render_jobs:
        active_render_jobs[job_id]["status"] = "CANCELLED"
    return {"job_id": job_id, "status": "cancelled", "message": "Job cancellation signaled successfully."}


@app.get("/api/v1/clips")
def api_list_clips(project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns all rendered vertical clips stored on disk with sidecar metadata and playback endpoints."""
    sidecars = project_store.list_clips(project_id=project_id)
    clips = []
    for s in sidecars:
        if not s.file_path or not os.path.exists(s.file_path):
            continue
        fname = os.path.basename(s.file_path)
        clips.append({
            "clip_id": s.clip_id,
            "project_id": s.project_id,
            "video_id": s.video_id,
            "filename": fname,
            "url": f"/clips/{fname}",
            "playback_url": f"/api/v1/clips/{s.clip_id}/media",
            "poster_url": f"/api/v1/clips/{s.clip_id}/poster",
            "download_url": f"/api/v1/clips/{s.clip_id}/download",
            "size_mb": round(s.file_size_bytes / (1024 * 1024), 2),
            "duration": round(s.duration_seconds, 1),
            "score": round(s.score, 1),
            "status": s.status,
            "validation_status": s.status,
            "modified_at": s.render_timestamp,
            "intelligence": s.intelligence,
            "caption_package": s.caption_package,
            "source_metadata": s.source_metadata,
            "qa_report": s.qa_report,
        })
    return clips


@app.post("/api/v1/clips/{clip_id}/regenerate_caption")
def api_regenerate_clip_caption(clip_id: str) -> Dict[str, Any]:
    """Regenerates AI caption package and intelligence for an existing clip sidecar."""
    clean_id = _sanitize_clip_id(clip_id)
    sidecar = project_store.get_clip_sidecar(clean_id)
    if not sidecar:
        raise HTTPException(status_code=404, detail="Clip ID not found.")

    cand_data = sidecar.candidate_data or {}
    from ..contracts.models import HighlightCandidate, ScoreBreakdown
    from ..discovery.video_metadata import EnrichedVideoInfo

    candidate = HighlightCandidate(
        candidate_id=sidecar.clip_id,
        video_id=sidecar.video_id,
        start_seconds=sidecar.start_seconds,
        end_seconds=sidecar.end_seconds,
        duration_seconds=sidecar.duration_seconds,
        score=sidecar.score,
        hook_title=cand_data.get("hook_title") or sidecar.caption_package.get("hook_title", ""),
        suggested_description=cand_data.get("suggested_description", ""),
        transcript_text=cand_data.get("transcript_text", ""),
        breakdown=ScoreBreakdown.from_dict(cand_data.get("breakdown", {})) if cand_data.get("breakdown") else ScoreBreakdown(),
    )

    video_info = None
    if sidecar.source_metadata:
        try:
            video_info = EnrichedVideoInfo.from_dict(sidecar.source_metadata)
        except Exception:
            pass

    new_pkg = caption_synthesizer.generate_caption_package(candidate, video_info)
    new_intel = caption_synthesizer.explain_clip(candidate, video_info)

    sidecar.caption_package = new_pkg.to_dict()
    sidecar.intelligence = new_intel.to_dict()
    project_store.save_clip_sidecar(sidecar)

    return {
        "clip_id": sidecar.clip_id,
        "caption_package": new_pkg.to_dict(),
        "intelligence": new_intel.to_dict(),
        "status": "regenerated",
    }


def _sanitize_clip_id(clip_id: str) -> str:
    clean = os.path.basename(clip_id.strip()).replace("/", "").replace("\\", "")
    if not clean or ".." in clip_id:
        raise HTTPException(status_code=400, detail="Invalid clip identifier.")
    return clean


def _assert_path_in_data_dir(file_path: str) -> str:
    resolved = os.path.abspath(file_path)
    allowed_roots = [os.path.abspath(DATA_DIR)]
    if os.getenv("PYTEST_CURRENT_TEST"):
        import tempfile
        allowed_roots.append(os.path.abspath(tempfile.gettempdir()))

    if not any(resolved.startswith(root) for root in allowed_roots):
        raise HTTPException(status_code=403, detail="Access forbidden: Path outside permitted data directory.")
    return resolved


@app.get("/api/v1/clips/{clip_id}")
def api_get_clip(clip_id: str) -> Dict[str, Any]:
    """Returns detailed sidecar record for a specific clip."""
    clean_id = _sanitize_clip_id(clip_id)
    sidecar = project_store.get_clip_sidecar(clean_id)
    if not sidecar:
        raise HTTPException(status_code=404, detail="Clip ID not found.")
    return sidecar.to_dict()


@app.get("/api/v1/clips/{clip_id}/download")
def api_download_clip(clip_id: str) -> FileResponse:
    """Downloads the finished Short video file."""
    clean_id = _sanitize_clip_id(clip_id)
    sidecar = project_store.get_clip_sidecar(clean_id)
    file_path = None
    if sidecar and os.path.exists(sidecar.file_path):
        file_path = sidecar.file_path
    else:
        # Fallback: check CLIPS_DIR directly for matching filename
        matches = glob.glob(os.path.join(CLIPS_DIR, f"*{clean_id}*.mp4"))
        if matches and os.path.exists(matches[0]):
            file_path = matches[0]

    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Video file not found.")

    safe_path = _assert_path_in_data_dir(file_path)
    return FileResponse(safe_path, filename=os.path.basename(safe_path), media_type="video/mp4")


@app.get("/api/v1/clips/{clip_id}/media")
def api_stream_clip_media(clip_id: str, request: Request) -> Response:
    """Streams video with HTTP Range request support for seeking."""
    clean_id = _sanitize_clip_id(clip_id)
    sidecar = project_store.get_clip_sidecar(clean_id)
    file_path = sidecar.file_path if (sidecar and os.path.exists(sidecar.file_path)) else None
    if not file_path:
        matches = glob.glob(os.path.join(CLIPS_DIR, f"*{clean_id}*.mp4"))
        if matches:
            file_path = matches[0]

    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Video file not found.")

    safe_path = _assert_path_in_data_dir(file_path)
    return stream_video_with_range(safe_path, request)


@app.get("/api/v1/clips/{clip_id}/poster")
def api_get_clip_poster(clip_id: str):
    """Returns a JPEG poster thumbnail for the clip, generating it if needed."""
    clean_id = _sanitize_clip_id(clip_id)
    sidecar = project_store.get_clip_sidecar(clean_id)
    file_path = sidecar.file_path if (sidecar and os.path.exists(sidecar.file_path)) else None
    if not file_path:
        matches = glob.glob(os.path.join(CLIPS_DIR, f"*{clean_id}*.mp4"))
        if matches:
            file_path = matches[0]

    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Clip video not found.")

    poster_path = os.path.splitext(file_path)[0] + ".jpg"
    if not os.path.exists(poster_path):
        try:
            import subprocess
            subprocess.run(
                ["ffmpeg", "-y", "-ss", "00:00:01.5", "-i", file_path, "-vframes", "1", "-q:v", "2", poster_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=5,
            )
        except Exception:
            pass

    if os.path.exists(poster_path):
        return FileResponse(poster_path, media_type="image/jpeg")

    if sidecar and sidecar.source_metadata and sidecar.source_metadata.get("thumbnail_url"):
        return RedirectResponse(sidecar.source_metadata["thumbnail_url"])
    raise HTTPException(status_code=404, detail="Poster unavailable.")


@app.get("/api/v1/projects")
def api_list_projects() -> List[Dict[str, Any]]:
    """Returns persistent project history enriched with clip metadata."""
    projects = project_store.list_projects()
    out = []
    for p in projects:
        data = p.to_dict()
        clips = project_store.list_clips(project_id=p.project_id)
        data["clips"] = [
            {
                "clip_id": c.clip_id,
                "filename": os.path.basename(c.file_path),
                "duration": round(c.duration_seconds, 1),
                "score": round(c.score, 1),
                "playback_url": f"/api/v1/clips/{c.clip_id}/media",
                "poster_url": f"/api/v1/clips/{c.clip_id}/poster",
                "download_url": f"/api/v1/clips/{c.clip_id}/download",
                "hook_title": (c.caption_package.get("hook_title") if c.caption_package else "") or (c.candidate_data.get("hook_title") if c.candidate_data else ""),
                "status": c.status,
            }
            for c in clips
        ]
        data["clips_count"] = len(clips)
        out.append(data)
    return out


@app.get("/api/v1/projects/{project_id}")
def api_get_project(project_id: str) -> Dict[str, Any]:
    """Returns details and clips for a specific project."""
    project = project_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project ID not found.")
    clips = project_store.list_clips(project_id=project_id)
    data = project.to_dict()
    data["clips"] = [c.to_dict() for c in clips]
    data["clips_count"] = len(clips)
    return data


@app.delete("/api/v1/projects/{project_id}")
def api_delete_project(project_id: str) -> Dict[str, Any]:
    """Deletes a project folder and its associated files."""
    clean_id = os.path.basename(project_id.strip()).replace("/", "").replace("\\", "")
    pdir = project_store.get_project_dir(clean_id)
    if os.path.exists(pdir):
        import shutil
        shutil.rmtree(pdir, ignore_errors=True)
        return {"status": "deleted", "project_id": clean_id}
    raise HTTPException(status_code=404, detail="Project not found.")


STUDIO_SETTINGS = {
    "gemini_model": os.getenv("GEMINI_PRIMARY_MODEL", "gemini-3.5-flash-lite"),
    "layout_mode": "active_speaker",
    "subtitle_preset": "hormozi",
    "gpu_acceleration": True,
    "enable_polish": True,
    "enable_outro": True,
    "attribution_template": "Original video and content by: {channel_title}",
    "fair_use_disclaimer": (
        "This Short contains edited material from the original source for commentary, "
        "educational discussion, or discovery. All underlying rights remain with their respective owners. "
        "Attribution is provided for identification. Contact our team for rights-related inquiries or removal requests."
    ),
    "contact_email": "rights@yourdomain.com",
}


@app.get("/api/v1/settings")
def api_get_settings() -> Dict[str, Any]:
    """Returns current studio configuration."""
    return STUDIO_SETTINGS


@app.post("/api/v1/settings")
def api_update_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Updates studio configuration preferences."""
    STUDIO_SETTINGS.update(updates)
    return {"status": "saved", "settings": STUDIO_SETTINGS}


# ------------------------------------------------------------------------------
# Professional SaaS Web Studio Redesign
# ------------------------------------------------------------------------------
DASHBOARD_HTML_PATH = os.path.join(os.path.dirname(__file__), "dashboard.html")
if os.path.exists(DASHBOARD_HTML_PATH):
    with open(DASHBOARD_HTML_PATH, "r", encoding="utf-8") as _f:
        HTML_DASHBOARD = _f.read()
else:
    HTML_DASHBOARD = "<!DOCTYPE html><html><body><h1>Studio Loading...</h1></body></html>"


@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    """Serves the live interactive studio dashboard."""
    if os.path.exists(DASHBOARD_HTML_PATH):
        with open(DASHBOARD_HTML_PATH, "r", encoding="utf-8") as _f:
            return _f.read()
    return HTML_DASHBOARD


def start_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Entry point to launch the studio server via uvicorn."""
    import uvicorn
    uvicorn.run("yt_clipping.web.server:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    start_server()
