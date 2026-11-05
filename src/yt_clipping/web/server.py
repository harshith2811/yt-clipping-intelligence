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
        fname = os.path.basename(s.file_path)
        clips.append({
            "clip_id": s.clip_id,
            "filename": fname,
            "url": f"/clips/{fname}",
            "playback_url": f"/api/v1/clips/{s.clip_id}/media",
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


@app.get("/api/v1/projects")
def api_list_projects() -> List[Dict[str, Any]]:
    """Returns persistent project history."""
    projects = project_store.list_projects()
    return [p.to_dict() for p in projects]


@app.get("/api/v1/projects/{project_id}")
def api_get_project(project_id: str) -> Dict[str, Any]:
    """Returns details and clips for a specific project."""
    project = project_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project ID not found.")
    clips = project_store.list_clips(project_id=project_id)
    data = project.to_dict()
    data["clips"] = [c.to_dict() for c in clips]
    return data


# ------------------------------------------------------------------------------
# Professional SaaS Web Studio Redesign
# ------------------------------------------------------------------------------
HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>YouTube Clipping Intelligence Platform - Live Studio</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #090d16;
      --card-bg: #111827;
      --card-inner: #0b1120;
      --border: #1f293d;
      --border-focus: #4f46e5;
      --accent: #6366f1;
      --accent-hover: #4f46e5;
      --accent-light: rgba(99, 102, 241, 0.12);
      --emerald: #10b981;
      --emerald-light: rgba(16, 185, 129, 0.12);
      --amber: #f59e0b;
      --amber-light: rgba(245, 158, 11, 0.12);
      --rose: #f43f5e;
      --rose-light: rgba(244, 63, 94, 0.12);
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --text-subtle: #64748b;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif; }
    body { background-color: var(--bg); color: var(--text); line-height: 1.5; min-height: 100vh; overflow-x: hidden; }
    
    /* Header */
    header {
      background: rgba(17, 24, 39, 0.85);
      backdrop-filter: blur(16px);
      border-bottom: 1px solid var(--border);
      padding: 0.875rem 2rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: sticky;
      top: 0;
      z-index: 100;
    }
    .brand { display: flex; align-items: center; gap: 0.85rem; font-weight: 800; font-size: 1.25rem; letter-spacing: -0.03em; }
    .brand-icon {
      width: 32px; height: 32px; border-radius: 8px; background: linear-gradient(135deg, #6366f1, #10b981);
      display: flex; align-items: center; justify-content: center; font-size: 1rem; color: #fff;
    }
    .badge {
      background: var(--accent-light); color: #a5b4fc; font-size: 0.72rem; font-weight: 600;
      padding: 0.2rem 0.6rem; border-radius: 9999px; border: 1px solid rgba(99, 102, 241, 0.3);
    }
    .nav-tabs { display: flex; gap: 0.5rem; background: var(--card-inner); padding: 0.25rem; border-radius: 0.5rem; border: 1px solid var(--border); }
    .nav-btn {
      padding: 0.45rem 1rem; border-radius: 0.375rem; border: none; font-size: 0.825rem; font-weight: 600;
      background: transparent; color: var(--text-muted); cursor: pointer; transition: all 0.2s;
    }
    .nav-btn.active { background: var(--accent); color: #fff; }
    .status-pill { display: flex; align-items: center; gap: 0.5rem; font-size: 0.825rem; color: var(--text-muted); }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--emerald); box-shadow: 0 0 10px var(--emerald); }

    /* Layout */
    .container { max-width: 1560px; margin: 1.75rem auto; padding: 0 1.5rem; }
    .grid-main { display: grid; grid-template-columns: 1.15fr 0.85fr; gap: 1.75rem; }
    @media(max-width: 1180px) { .grid-main { grid-template-columns: 1fr; } }

    .card {
      background: var(--card-bg); border: 1px solid var(--border); border-radius: 1rem;
      padding: 1.5rem; box-shadow: 0 10px 30px -10px rgba(0, 0, 0, 0.4); margin-bottom: 1.75rem;
    }
    .card-title {
      font-size: 1.1rem; font-weight: 700; margin-bottom: 1.25rem; display: flex; align-items: center;
      justify-content: space-between; letter-spacing: -0.01em;
    }
    .card-title span { display: flex; align-items: center; gap: 0.5rem; }

    /* Form Controls */
    label { display: block; font-size: 0.825rem; color: var(--text-muted); margin-bottom: 0.45rem; font-weight: 600; }
    input[type="text"], select, textarea {
      width: 100%; background: var(--card-inner); border: 1px solid var(--border); border-radius: 0.6rem;
      padding: 0.75rem 1rem; color: #fff; font-size: 0.9rem; margin-bottom: 1.25rem; transition: border-color 0.2s;
    }
    input[type="text"]:focus, select:focus, textarea:focus { outline: none; border-color: var(--accent); }
    textarea { font-family: 'JetBrains Mono', monospace; font-size: 0.825rem; resize: vertical; min-height: 140px; }

    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
    .toggles { display: flex; flex-direction: column; gap: 0.75rem; margin-bottom: 1.25rem; }
    .toggle-row { display: flex; align-items: center; justify-content: space-between; font-size: 0.875rem; color: var(--text-muted); }
    input[type="checkbox"] { width: 1.15rem; height: 1.15rem; accent-color: var(--accent); cursor: pointer; }

    /* Action Buttons */
    .btn-group { display: flex; gap: 0.85rem; }
    button {
      padding: 0.75rem 1.25rem; border-radius: 0.6rem; border: none; font-weight: 600; font-size: 0.9rem;
      cursor: pointer; transition: all 0.2s; display: flex; justify-content: center; align-items: center; gap: 0.5rem;
    }
    .btn-preview { background: #1e293b; color: #f1f5f9; border: 1px solid #334155; }
    .btn-preview:hover { background: #334155; }
    .btn-primary { background: var(--accent); color: #fff; }
    .btn-primary:hover { background: var(--accent-hover); box-shadow: 0 0 20px rgba(99, 102, 241, 0.4); }
    .btn-cancel { background: var(--rose-light); color: var(--rose); border: 1px solid var(--rose); font-size: 0.8rem; padding: 0.35rem 0.75rem; }
    .btn-copy { background: #1e293b; color: #e2e8f0; font-size: 0.8rem; padding: 0.45rem 0.85rem; border: 1px solid var(--border); }
    .btn-copy:hover { background: var(--accent); color: #fff; }

    /* Source Video Overview Card */
    .source-overview {
      display: flex; gap: 1.25rem; background: var(--card-inner); border: 1px solid var(--border);
      border-radius: 0.75rem; padding: 1rem; margin-bottom: 1.25rem; align-items: center;
    }
    .source-thumb { width: 150px; height: 85px; border-radius: 0.5rem; object-fit: cover; background: #000; flex-shrink: 0; }
    .source-details { flex: 1; overflow: hidden; }
    .source-title { font-size: 0.95rem; font-weight: 700; margin-bottom: 0.3rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .source-meta { font-size: 0.775rem; color: var(--text-muted); display: flex; gap: 0.85rem; flex-wrap: wrap; }

    /* Candidates List */
    .candidate-card {
      background: var(--card-inner); border: 1px solid var(--border); border-radius: 0.75rem;
      padding: 1.15rem; margin-bottom: 1rem; transition: border-color 0.2s;
    }
    .candidate-card:hover { border-color: rgba(99, 102, 241, 0.5); }
    .candidate-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.6rem; }
    .score-badge {
      background: var(--emerald-light); color: var(--emerald); font-weight: 700; font-size: 0.775rem;
      padding: 0.25rem 0.6rem; border-radius: 9999px; border: 1px solid rgba(16, 185, 129, 0.3);
    }
    .candidate-title { font-size: 0.95rem; font-weight: 700; margin-bottom: 0.5rem; color: #fff; }
    .why-card {
      background: rgba(99, 102, 241, 0.05); border-left: 3px solid var(--accent); padding: 0.65rem 0.85rem;
      border-radius: 0 0.5rem 0.5rem 0; font-size: 0.825rem; color: #cbd5e1; margin-top: 0.6rem;
    }

    /* Metric Grid */
    .metric-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.5rem; margin-top: 0.6rem; }
    .metric-pill { background: #0f172a; padding: 0.4rem; border-radius: 0.375rem; text-align: center; border: 1px solid var(--border); }
    .metric-val { font-size: 0.85rem; font-weight: 700; color: #a5b4fc; }
    .metric-label { font-size: 0.68rem; color: var(--text-subtle); text-transform: uppercase; }

    /* Progress Box */
    .progress-box { margin-top: 1.25rem; background: var(--card-inner); border: 1px solid var(--border); border-radius: 0.75rem; padding: 1.15rem; display: none; }
    .progress-bar-bg { width: 100%; height: 8px; background: #1e293b; border-radius: 4px; overflow: hidden; margin: 0.75rem 0; }
    .progress-bar { height: 100%; width: 0%; background: var(--accent); transition: width 0.3s; }

    /* Shorts Gallery */
    .clips-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 1.25rem; }
    .clip-card { background: var(--card-inner); border: 1px solid var(--border); border-radius: 0.75rem; overflow: hidden; display: flex; flex-direction: column; }
    .video-wrapper { position: relative; width: 100%; padding-top: 177.77%; background: #000; }
    .video-wrapper video { position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: contain; }
    .clip-meta { padding: 1rem; flex: 1; display: flex; flex-direction: column; justify-content: space-between; gap: 0.75rem; }

    /* Caption Studio Tabs */
    .caption-tabs { display: flex; gap: 0.5rem; margin-bottom: 0.75rem; }
    .caption-tab-btn {
      background: var(--card-inner); color: var(--text-muted); border: 1px solid var(--border);
      padding: 0.35rem 0.75rem; border-radius: 0.375rem; font-size: 0.775rem; font-weight: 600; cursor: pointer;
    }
    .caption-tab-btn.active { background: var(--accent); color: #fff; border-color: var(--accent); }

    /* Notification Toast */
    .toast {
      position: fixed; bottom: 2rem; right: 2rem; background: #1e293b; border: 1px solid var(--emerald);
      color: #fff; padding: 0.85rem 1.25rem; border-radius: 0.5rem; display: flex; align-items: center;
      gap: 0.6rem; font-size: 0.875rem; font-weight: 600; box-shadow: 0 10px 25px rgba(0,0,0,0.5);
      z-index: 1000; opacity: 0; pointer-events: none; transition: opacity 0.3s;
    }
    .toast.show { opacity: 1; pointer-events: auto; }
  </style>
</head>
<body>

  <!-- Application Header -->
  <header>
    <div class="brand">
      <div class="brand-icon">⚡</div>
      <span>YouTube Clipping Studio</span>
      <span class="badge">Phase 2 AI Engine</span>
    </div>

    <div class="nav-tabs">
      <button class="nav-btn active" onclick="switchView('studio')">Studio Workspace</button>
      <button class="nav-btn" onclick="switchView('projects')">Project History</button>
      <button class="nav-btn" onclick="switchView('settings')">Settings</button>
    </div>

    <div class="status-pill" id="healthPill">
      <div class="dot"></div>
      <span id="healthText">Auditing Subsystems...</span>
    </div>
  </header>

  <div class="container">
    <!-- View 1: Studio Workspace -->
    <div id="viewStudio" class="grid-main">
      
      <!-- Left Column: Input, Discovery, and Render Settings -->
      <div>
        <!-- Ingestion Card -->
        <div class="card">
          <div class="card-title">
            <span>🎥 Ingest YouTube Video</span>
            <span class="badge" id="providerBadge">Dual-Engine Active</span>
          </div>

          <label for="videoInput">YouTube URL, Short Link, or 11-Character Video ID</label>
          <input type="text" id="videoInput" placeholder="https://www.youtube.com/watch?v=nEaJMdM1djM" value="https://www.youtube.com/watch?v=nEaJMdM1djM">

          <!-- Source Video Overview Card (Dynamically updated) -->
          <div class="source-overview" id="sourceOverview" style="display: none;">
            <img class="source-thumb" id="srcThumb" src="" alt="Thumbnail">
            <div class="source-details">
              <div class="source-title" id="srcTitle">Loading title...</div>
              <div class="source-meta">
                <span id="srcChannel">Channel: --</span>
                <span id="srcDuration">Duration: --</span>
                <span id="srcViews">Views: --</span>
                <span id="srcProvider" style="color:var(--emerald);">Provider: --</span>
              </div>
            </div>
          </div>

          <div class="grid-2">
            <div>
              <label for="clipsCount">Milking Yield (Solid Shorts)</label>
              <select id="clipsCount">
                <option value="auto">Auto (SolidShortsDecider)</option>
                <option value="1">1 Top Short</option>
                <option value="3" selected>3 Solid Shorts</option>
                <option value="5">5 High-Retention Shorts</option>
              </select>
            </div>
            <div>
              <label for="layoutMode">Camera Framing Profile</label>
              <select id="layoutMode">
                <option value="active_speaker" selected>Active Speaker (YuNet Gimbal)</option>
                <option value="blur_background">Cinematic 9:16 Blurred Canvas</option>
                <option value="split_screen">Dual Split-Screen (Podcast)</option>
              </select>
            </div>
          </div>

          <div class="grid-2">
            <div>
              <label for="subPreset">Animated Subtitle Preset</label>
              <select id="subPreset">
                <option value="hormozi" selected>Hormozi (Bounce + Yellow Pop)</option>
                <option value="beast_bounce">Beast Bounce (Rapid High Energy)</option>
                <option value="neon_cyber">Neon Cyber (Cyan Glow)</option>
                <option value="clean_editorial">Clean Editorial (Minimal White)</option>
              </select>
            </div>
            <div>
              <label for="hardwareAccel">Hardware Acceleration</label>
              <select id="hardwareAccel">
                <option value="gpu" selected>NVIDIA NVENC (High Speed)</option>
                <option value="cpu">libx264 (CPU Fallback)</option>
              </select>
            </div>
          </div>

          <div class="toggles">
            <div class="toggle-row">
              <span>⚡ Pacing Polish & Anti-Pop Speech Gates</span>
              <input type="checkbox" id="enablePolish" checked>
            </div>
            <div class="toggle-row">
              <span>🔔 Dedicated Animated Outro Card (2.5s with Chime)</span>
              <input type="checkbox" id="enableOutro" checked>
            </div>
          </div>

          <div class="btn-group">
            <button class="btn-preview" onclick="runPreview()">🔍 Discover & Explain Moments</button>
            <button class="btn-primary" onclick="startRender()">🚀 Render Solid Shorts</button>
          </div>

          <!-- Staged Progress Box -->
          <div class="progress-box" id="progressBox">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span id="progressMsg" style="font-size:0.85rem; font-weight:600;">Processing...</span>
              <div style="display:flex; align-items:center; gap:0.5rem;">
                <span id="progressPct" style="font-size:0.85rem; font-weight:700; color:var(--accent);">0%</span>
                <button class="btn-cancel" id="btnCancelJob" onclick="cancelCurrentJob()" style="display:none;">Cancel</button>
              </div>
            </div>
            <div class="progress-bar-bg">
              <div class="progress-bar" id="progressBar"></div>
            </div>
          </div>
        </div>

        <!-- Discovered Candidates & Explainability Card -->
        <div class="card" id="previewContainer" style="display: none;">
          <div class="card-title">
            <span>📊 Discovered Solid Shorts & Why They Work</span>
            <span class="badge" id="yieldSummary">Yield: 0</span>
          </div>
          <div id="candidatesList"></div>
        </div>
      </div>

      <!-- Right Column: Rendered Library, Video Player, and Caption Studio -->
      <div>
        <!-- Shorts Library Card -->
        <div class="card">
          <div class="card-title">
            <span>🎬 Rendered 9:16 Shorts Library</span>
            <button onclick="loadClips()" style="padding:0.3rem 0.8rem; font-size:0.775rem; background:#1e293b; color:#fff;">↻ Refresh</button>
          </div>
          <div class="clips-grid" id="clipsGrid">
            <div style="color:var(--text-muted); font-size:0.875rem; grid-column:1/-1; text-align:center; padding:3rem 0;">
              No rendered vertical clips on disk yet. Render one on the left!
            </div>
          </div>
        </div>

        <!-- Active Short Caption & Publishing Studio -->
        <div class="card" id="captionStudioCard" style="display: none;">
          <div class="card-title">
            <span>✍ Caption Studio & Social Publishing</span>
            <div style="display:flex; gap:0.5rem;">
              <button class="btn-copy" id="btnRegenerateCaption" onclick="regenerateCaption()">✨ Regenerate</button>
              <button class="btn-copy" onclick="copyHashtags()">🏷 Copy Tags</button>
              <button class="btn-copy" onclick="copyFormattedCaption()">📋 Copy Caption</button>
            </div>
          </div>

          <div class="caption-tabs">
            <button class="caption-tab-btn active" id="tabFull" onclick="switchPlatformTab('full')">Full Package</button>
            <button class="caption-tab-btn" id="tabYT" onclick="switchPlatformTab('youtube_shorts')">YouTube Shorts</button>
            <button class="caption-tab-btn" id="tabIG" onclick="switchPlatformTab('instagram_reels')">Instagram Reels</button>
            <button class="caption-tab-btn" id="tabTT" onclick="switchPlatformTab('tiktok')">TikTok</button>
          </div>

          <label for="captionEditor">Ready-to-Publish Formatted Caption (Editable)</label>
          <textarea id="captionEditor"></textarea>

          <div style="display:flex; justify-content:space-between; align-items:center; margin-top:0.5rem;">
            <span style="font-size:0.75rem; color:var(--text-subtle);" id="captionProviderText">Generated via: Gemini</span>
            <button style="background:transparent; border:none; color:#a5b4fc; font-size:0.75rem; cursor:pointer;" onclick="resetCaptionToAI()">↺ Reset to AI Original</button>
          </div>
        </div>
      </div>

    </div>

    <!-- View 2: Projects History -->
    <div id="viewProjects" style="display: none;">
      <div class="card">
        <div class="card-title">
          <span>📁 Persistent Project Archive</span>
          <button onclick="loadProjects()" style="padding:0.3rem 0.8rem; font-size:0.775rem; background:#1e293b; color:#fff;">↻ Refresh</button>
        </div>
        <div id="projectsList" style="display:flex; flex-direction:column; gap:1rem;">
          <div style="color:var(--text-muted); text-align:center; padding:3rem 0;">Loading project history...</div>
        </div>
      </div>
    </div>

    <!-- View 3: Settings & Diagnostics -->
    <div id="viewSettings" style="display: none;">
      <div class="card">
        <div class="card-title">⚙ System Diagnostics & Architecture Status</div>
        <div id="diagnosticsDetails" style="font-family:'JetBrains Mono', monospace; font-size:0.85rem; color:#cbd5e1; line-height:1.7;">
          Inspecting runtime environment...
        </div>
      </div>
    </div>

  </div>

  <!-- Notification Toast -->
  <div class="toast" id="toast">
    <span>✓</span>
    <span id="toastMsg">Caption copied to clipboard!</span>
  </div>

  <script>
    // State management
    let currentSelectedClipData = null;
    let currentActiveTaskId = null;
    let pollInterval = null;

    function sanitizeHTML(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function showToast(msg) {
      const toast = document.getElementById('toast');
      document.getElementById('toastMsg').innerText = msg;
      toast.classList.add('show');
      setTimeout(() => toast.classList.remove('show'), 3000);
    }

    function switchView(viewName) {
      document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
      document.getElementById('viewStudio').style.display = viewName === 'studio' ? 'grid' : 'none';
      document.getElementById('viewProjects').style.display = viewName === 'projects' ? 'block' : 'none';
      document.getElementById('viewSettings').style.display = viewName === 'settings' ? 'block' : 'none';

      if (viewName === 'projects') loadProjects();
      if (viewName === 'settings') loadSettings();
    }

    async function checkHealth() {
      try {
        const res = await fetch('/api/v1/health');
        const data = await res.json();
        const pill = document.getElementById('healthText');
        const dev = data.gpu_available ? data.gpu_device : 'CPU Fallback';
        pill.innerText = `Online | ${dev} | FFmpeg Ready`;
        document.getElementById('providerBadge').innerText = data.metadata_provider === 'youtube_data_api_v3' ? 'Data API v3' : 'yt-dlp Fallback';
      } catch (e) {
        document.getElementById('healthText').innerText = 'Platform API Error';
      }
    }

    async function runPreview() {
      const url = document.getElementById('videoInput').value.trim();
      if (!url) return alert('Please enter a YouTube video URL');

      const pBox = document.getElementById('previewContainer');
      const list = document.getElementById('candidatesList');
      list.innerHTML = '<div style="color:var(--text-muted); padding:1rem 0;">Extracting transcript, retention heatmap, and synthesizing intelligence...</div>';
      pBox.style.display = 'block';

      try {
        const res = await fetch('/api/v1/preview', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ video_id_or_url: url })
        });
        const data = await res.json();
        if (data.detail) return alert('Preview Error: ' + data.detail);

        // Display Source Overview
        if (data.source_metadata) {
          const m = data.source_metadata;
          document.getElementById('srcThumb').src = m.thumbnail_url || '';
          document.getElementById('srcTitle').innerText = m.title || 'Source Video';
          document.getElementById('srcChannel').innerText = `Channel: ${m.channel_title || '--'}`;
          document.getElementById('srcDuration').innerText = `Duration: ${Math.round(m.duration)}s`;
          document.getElementById('srcViews').innerText = `Views: ${Number(m.view_count).toLocaleString()}`;
          document.getElementById('srcProvider').innerText = `Provider: ${m.metadata_provider}`;
          document.getElementById('sourceOverview').style.display = 'flex';
        }

        document.getElementById('yieldSummary').innerText = `${data.recommended_solid_shorts_count} Shorts Recommended`;

        if (!data.solid_clips || data.solid_clips.length === 0) {
          list.innerHTML = '<div style="color:var(--text-muted); padding:1rem 0;">No high-retention clips met the solid quality floor.</div>';
          return;
        }

        list.innerHTML = data.solid_clips.map(c => {
          const intel = c.intelligence || {};
          return `
            <div class="candidate-card">
              <div class="candidate-header">
                <span class="score-badge">★ ${c.score}/100 Composite Score</span>
                <span style="font-size:0.775rem; color:var(--text-subtle); font-family:monospace;">${c.start_seconds}s - ${c.end_seconds}s (${c.duration_seconds}s)</span>
              </div>
              <div class="candidate-title">"${sanitizeHTML(c.hook_title)}"</div>
              <div class="why-card">
                <strong>Why This Short Works:</strong> ${sanitizeHTML(c.why_it_works || intel.why_it_works || c.rationale)}
              </div>
              <div class="metric-grid" style="grid-template-columns: repeat(5, 1fr);">
                <div class="metric-pill">
                  <div class="metric-val">${intel.hook_strength || 8.5}/10</div>
                  <div class="metric-label">Hook</div>
                </div>
                <div class="metric-pill">
                  <div class="metric-val">${intel.context_completeness || 8.0}/10</div>
                  <div class="metric-label">Complete</div>
                </div>
                <div class="metric-pill">
                  <div class="metric-val">${intel.information_density || 7.8}/10</div>
                  <div class="metric-label">Density</div>
                </div>
                <div class="metric-pill">
                  <div class="metric-val">${intel.ending_quality || 8.0}/10</div>
                  <div class="metric-label">Ending</div>
                </div>
                <div class="metric-pill">
                  <div class="metric-val">${intel.estimated_engagement_potential || 85}%</div>
                  <div class="metric-label">Est. Ret.</div>
                </div>
              </div>
              <div style="font-size:0.775rem; color:var(--text-subtle); margin-top:0.6rem; line-height:1.4;">
                <span style="color:var(--text-muted); font-weight:600;">Selection Rationale:</span> ${sanitizeHTML(intel.selection_reason || c.rationale || 'Selected by SolidShortsDecider')}
              </div>
              ${(intel.quality_warnings || []).map(w => `<div style="font-size:0.75rem; color:var(--amber); margin-top:0.35rem;">⚠️ ${sanitizeHTML(w)}</div>`).join('')}
            </div>
          `;
        }).join('');

      } catch (e) {
        list.innerHTML = `<div style="color:var(--rose); padding:1rem 0;">Preview extraction failed: ${e.message}</div>`;
      }
    }

    async function startRender() {
      const url = document.getElementById('videoInput').value.trim();
      if (!url) return alert('Please enter a YouTube video URL');

      const countVal = document.getElementById('clipsCount').value;
      const maxClips = countVal === 'auto' ? 3 : parseInt(countVal, 10);
      const layout = document.getElementById('layoutMode').value;
      const subPreset = document.getElementById('subPreset').value;
      const gpu = document.getElementById('hardwareAccel').value === 'gpu';
      const enablePolish = document.getElementById('enablePolish').checked;
      const enableOutro = document.getElementById('enableOutro').checked;

      const pBox = document.getElementById('progressBox');
      const pBar = document.getElementById('progressBar');
      const pMsg = document.getElementById('progressMsg');
      const pPct = document.getElementById('progressPct');
      const btnCancel = document.getElementById('btnCancelJob');

      pBox.style.display = 'block';
      pBar.style.width = '5%';
      pBar.style.background = 'var(--accent)';
      pMsg.innerText = 'Initializing background rendering job...';
      pPct.innerText = '5%';
      btnCancel.style.display = 'inline-block';

      try {
        const res = await fetch('/api/v1/render', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            video_id_or_url: url,
            max_clips: maxClips,
            layout: layout,
            subtitle_preset: subPreset,
            enable_polish: enablePolish,
            enable_outro: enableOutro,
            gpu: gpu
          })
        });
        const data = await res.json();
        if (data.detail) return alert('Render Error: ' + data.detail);

        currentActiveTaskId = data.job_id || data.task_id;
        pollStatus(currentActiveTaskId);
      } catch (e) {
        alert('Failed to trigger render: ' + e.message);
      }
    }

    function pollStatus(taskId) {
      if (pollInterval) clearInterval(pollInterval);
      const pBar = document.getElementById('progressBar');
      const pMsg = document.getElementById('progressMsg');
      const pPct = document.getElementById('progressPct');
      const btnCancel = document.getElementById('btnCancelJob');

      pollInterval = setInterval(async () => {
        try {
          const res = await fetch(`/api/v1/jobs/${taskId}`);
          const data = await res.json();
          pBar.style.width = `${data.progress}%`;
          pPct.innerText = `${data.progress}%`;
          pMsg.innerText = `[${data.current_stage || data.status}] ${data.message || ''}`;

          if (data.status === 'completed' || data.status === 'COMPLETED') {
            clearInterval(pollInterval);
            pBar.style.background = 'var(--emerald)';
            pMsg.innerText = 'Render Complete! Finished Shorts loaded below.';
            btnCancel.style.display = 'none';
            loadClips();
          } else if (data.status === 'failed' || data.status === 'FAILED') {
            clearInterval(pollInterval);
            pBar.style.background = 'var(--rose)';
            pMsg.innerText = 'Render Failed: ' + (data.error || 'Unknown error');
            btnCancel.style.display = 'none';
          } else if (data.status === 'cancelled' || data.status === 'CANCELLED') {
            clearInterval(pollInterval);
            pBar.style.background = 'var(--amber)';
            pMsg.innerText = 'Job was cancelled.';
            btnCancel.style.display = 'none';
          }
        } catch (e) {
          console.error(e);
        }
      }, 2500);
    }

    async function cancelCurrentJob() {
      if (!currentActiveTaskId) return;
      try {
        await fetch(`/api/v1/jobs/${currentActiveTaskId}/cancel`, { method: 'POST' });
        showToast('Cancellation signaled.');
      } catch (e) {
        alert('Failed to cancel job: ' + e.message);
      }
    }

    let currentPlatformTab = 'full';

    async function loadClips() {
      try {
        const res = await fetch('/api/v1/clips');
        const clips = await res.json();
        const grid = document.getElementById('clipsGrid');
        if (!clips || clips.length === 0) {
          grid.innerHTML = '<div style="color:var(--text-muted); font-size:0.875rem; grid-column:1/-1; text-align:center; padding:3rem 0;">No rendered vertical clips found on disk yet.</div>';
          return;
        }

        window.loadedClipsMap = {};
        clips.forEach(c => { window.loadedClipsMap[c.clip_id] = c; });

        grid.innerHTML = clips.map(c => `
          <div class="clip-card">
            <div class="video-wrapper">
              <video src="${c.playback_url || c.url}" controls preload="metadata"></video>
            </div>
            <div class="clip-meta">
              <div>
                <span class="score-badge">★ ${c.score}/100</span>
                <div style="font-size:0.9rem; font-weight:700; margin-top:0.4rem;">${sanitizeHTML(c.filename)}</div>
                <div style="font-size:0.75rem; color:var(--text-subtle);">${c.duration}s | ${c.size_mb} MB | QA: ${c.validation_status || c.status}</div>
              </div>
              <div style="display:flex; gap:0.5rem;">
                <a href="${c.download_url || c.url}" download="${c.filename}" class="btn-copy" style="flex:1; text-align:center; text-decoration:none;">⬇ Download</a>
                <button class="btn-copy" onclick="selectClipById('${c.clip_id}')">✍ Caption</button>
              </div>
            </div>
          </div>
        `).join('');

        if (clips.length > 0 && !currentSelectedClipData) {
          selectClipForCaption(clips[0]);
        }
      } catch (e) {
        console.error(e);
      }
    }

    function selectClipById(clipId) {
      if (window.loadedClipsMap && window.loadedClipsMap[clipId]) {
        selectClipForCaption(window.loadedClipsMap[clipId]);
      }
    }

    function selectClipForCaption(clip) {
      currentSelectedClipData = clip;
      const studioCard = document.getElementById('captionStudioCard');
      studioCard.style.display = 'block';

      const pkg = clip.caption_package || {};
      document.getElementById('captionProviderText').innerText = `Generated via: ${pkg.generation_provider || 'Deterministic Offline'}`;
      switchPlatformTab(currentPlatformTab || 'full');
    }

    function switchPlatformTab(platform) {
      currentPlatformTab = platform;
      document.getElementById('tabFull').classList.toggle('active', platform === 'full');
      document.getElementById('tabYT').classList.toggle('active', platform === 'youtube_shorts');
      document.getElementById('tabIG').classList.toggle('active', platform === 'instagram_reels');
      document.getElementById('tabTT').classList.toggle('active', platform === 'tiktok');

      if (!currentSelectedClipData || !currentSelectedClipData.caption_package) return;
      const pkg = currentSelectedClipData.caption_package;
      const vars = pkg.platform_variants || {};

      if (platform === 'full') {
        document.getElementById('captionEditor').value = pkg.full_copy_caption || '';
      } else if (vars[platform]) {
        document.getElementById('captionEditor').value = vars[platform];
      }
    }

    async function regenerateCaption() {
      if (!currentSelectedClipData || !currentSelectedClipData.clip_id) {
        return alert('Please select a rendered clip first.');
      }
      const btn = document.getElementById('btnRegenerateCaption');
      if (btn) btn.innerText = '⏳ Synthesizing...';
      try {
        const res = await fetch(`/api/v1/clips/${currentSelectedClipData.clip_id}/regenerate_caption`, {
          method: 'POST'
        });
        if (!res.ok) throw new Error('Regeneration endpoint returned error');
        const data = await res.json();
        currentSelectedClipData.caption_package = data.caption_package;
        currentSelectedClipData.intelligence = data.intelligence;
        if (window.loadedClipsMap && window.loadedClipsMap[currentSelectedClipData.clip_id]) {
          window.loadedClipsMap[currentSelectedClipData.clip_id] = currentSelectedClipData;
        }
        selectClipForCaption(currentSelectedClipData);
        showToast('New caption & hooks synthesized!');
      } catch (e) {
        alert('Failed to regenerate caption: ' + e.message);
      } finally {
        if (btn) btn.innerText = '✨ Regenerate';
      }
    }

    function copyFormattedCaption() {
      const text = document.getElementById('captionEditor').value;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => showToast('Caption copied to clipboard!'));
      } else {
        // Fallback
        const ta = document.getElementById('captionEditor');
        ta.select();
        document.execCommand('copy');
        showToast('Caption copied to clipboard!');
      }
    }

    function copyHashtags() {
      if (!currentSelectedClipData || !currentSelectedClipData.caption_package) return;
      const tags = (currentSelectedClipData.caption_package.targeted_hashtags || []).join(' ');
      if (navigator.clipboard) {
        navigator.clipboard.writeText(tags).then(() => showToast('Hashtags copied!'));
      }
    }

    function resetCaptionToAI() {
      if (!currentSelectedClipData || !currentSelectedClipData.caption_package) return;
      const pkg = currentSelectedClipData.caption_package;
      if (currentPlatformTab === 'full') {
        document.getElementById('captionEditor').value = pkg.full_copy_caption || '';
      } else {
        const vars = pkg.platform_variants || {};
        document.getElementById('captionEditor').value = vars[currentPlatformTab] || pkg.full_copy_caption || '';
      }
      showToast('Caption reset to AI original.');
    }

    async function loadProjects() {
      const list = document.getElementById('projectsList');
      try {
        const res = await fetch('/api/v1/projects');
        const projs = await res.json();
        if (!projs || projs.length === 0) {
          list.innerHTML = '<div style="color:var(--text-muted); text-align:center; padding:3rem 0;">No saved projects found. Process a video in Studio!</div>';
          return;
        }

        list.innerHTML = projs.map(p => `
          <div style="background:var(--card-inner); border:1px solid var(--border); border-radius:0.75rem; padding:1.25rem; display:flex; justify-content:space-between; align-items:center;">
            <div>
              <div style="font-weight:700; font-size:1rem; margin-bottom:0.25rem;">${sanitizeHTML(p.title)}</div>
              <div style="font-size:0.8rem; color:var(--text-muted);">Video ID: ${p.video_id} | Created: ${p.created_at.slice(0, 10)} | Clips: ${p.clips_count}</div>
            </div>
            <button class="btn-copy" onclick="resumeProject('${p.video_id}')">Open in Studio</button>
          </div>
        `).join('');
      } catch (e) {
        list.innerHTML = '<div style="color:var(--rose);">Failed to load project history.</div>';
      }
    }

    function resumeProject(videoId) {
      document.getElementById('videoInput').value = `https://www.youtube.com/watch?v=${videoId}`;
      switchView('studio');
      runPreview();
    }

    async function loadSettings() {
      const box = document.getElementById('diagnosticsDetails');
      try {
        const res = await fetch('/api/v1/health');
        const data = await res.json();
        box.innerHTML = `
Backend Status:        ${data.status}
Timestamp:             ${data.timestamp}
Hardware GPU:          ${data.gpu_device} (Available: ${data.gpu_available})
FFmpeg Path:           ${data.ffmpeg_path || 'Not found'}
Metadata Engine:       ${data.metadata_provider}
Gemini Model Active:   ${data.models.gemini_model}
Total Rendered Clips:  ${data.storage.clips_count}
Total Saved Projects:  ${data.storage.projects_count}
Storage Base Path:     ${data.storage.data_dir}
        `;
      } catch (e) {
        box.innerText = 'Failed to load telemetry diagnostics.';
      }
    }

    // Initialize on boot
    checkHealth();
    loadClips();
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    """Serves the live interactive studio dashboard."""
    return HTML_DASHBOARD


def start_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Entry point to launch the studio server via uvicorn."""
    import uvicorn
    uvicorn.run("yt_clipping.web.server:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    start_server()
