"""
YouTube Clipping Intelligence Platform - Live Studio Web Dashboard & REST API.
Provides interactive clip previewing, 9:16 vertical rendering, live playback,
channel monitoring, and system diagnostic telemetry.
"""

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

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from ..config import AppConfig
from ..contracts.models import RenderProfile
from ..ingestion.asset_provider import extract_youtube_video_id
from ..orchestration.state_machine import JobJournal
from ..rights.gate import LocalRightsPolicy
from ..detection.solid_shorts import SolidShortsDecider
from ..cli.commands.pipeline import build_pipeline

logger = logging.getLogger(__name__)

# Base directories
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
DATA_DIR = os.path.join(BASE_DIR, "data")
CLIPS_DIR = os.path.join(DATA_DIR, "rendered_clips")
TEMP_DIR = os.path.join(DATA_DIR, "temp")
os.makedirs(CLIPS_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

app = FastAPI(
    title="YouTube Clipping Intelligence Platform - Studio API",
    version="1.0.0",
    description="24/7 Autonomous AI video clipping, heatmap analysis, and 9:16 vertical rendering engine",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount rendered clips static directory for instant in-browser video playback
app.mount("/clips", StaticFiles(directory=CLIPS_DIR), name="clips")


# ------------------------------------------------------------------------------
# Pydantic Request Models
# ------------------------------------------------------------------------------
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


# In-memory status store for running web render jobs
active_render_jobs: Dict[str, Dict[str, Any]] = {}


# ------------------------------------------------------------------------------
# API Endpoints
# ------------------------------------------------------------------------------
@app.get("/api/v1/health")
def api_health() -> Dict[str, Any]:
    """Inspects environment, GPU, FFmpeg, and model weights readiness."""
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
    yunet_path = os.path.join(BASE_DIR, "models", "face_detection_yunet_2023mar.onnx")
    yolo_path = os.path.join(BASE_DIR, "models", "yolov8n-seg.pt")

    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gpu_available": gpu_available,
        "gpu_device": gpu_name,
        "ffmpeg_ready": bool(ffmpeg_path),
        "ffmpeg_path": ffmpeg_path,
        "models": {
            "yunet_onnx": os.path.exists(yunet_path),
            "yolov8n_seg": os.path.exists(yolo_path),
            "gemini_active": bool(os.getenv("GEMINI_API_KEY")),
        },
        "storage": {
            "data_dir": DATA_DIR,
            "clips_count": len(glob.glob(os.path.join(CLIPS_DIR, "*.mp4"))),
        },
    }


@app.post("/api/v1/preview")
def api_preview(req: PreviewRequest) -> Dict[str, Any]:
    """Extracts candidate highlights, retention curves, and applies SolidShortsDecider without rendering."""
    try:
        video_id = extract_youtube_video_id(req.video_id_or_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid YouTube video ID or URL: {e}")
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube video ID or URL.")

    # Auto-register operator rights manifest if not present
    policy = LocalRightsPolicy(os.path.join(DATA_DIR, "rights_ledger.json"), db_path=os.path.join(DATA_DIR, "jobs.db"))
    manifest = policy.check_rights(video_id)
    if not policy.verify_rights(manifest):
        policy.register_rights(
            video_id=video_id,
            basis="OPERATOR_ASSET",
            owner="Studio Operator",
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
    try:
        transcript = pipeline.transcriber.load_from_cache(video_id)
        dur = transcript.duration_seconds if transcript else 0.0
        heatmap_data = pipeline.heatmap_analyzer.extract_heatmap(video_id=video_id, duration_seconds=dur)
    except Exception:
        pass

    # Apply SolidShortsDecider
    decider = SolidShortsDecider()
    decision = decider.decide(
        candidates=candidates,
        duration_seconds=transcript.duration_seconds if transcript else 300.0,
        heatmap_data=heatmap_data,
        strict_quality=True,
    )

    return {
        "video_id": video_id,
        "total_candidates_found": len(candidates),
        "recommended_solid_shorts_count": decision.recommended_count,
        "capacity_limit": decision.capacity_limit,
        "decision_reasons": decision.reasons,
        "solid_clips": [
            {
                "candidate_id": c.candidate_id,
                "start_seconds": round(c.start_seconds, 1),
                "end_seconds": round(c.end_seconds, 1),
                "duration_seconds": round(c.duration_seconds, 1),
                "score": round(c.score, 1),
                "hook_title": c.hook_title or "Viral Highlight",
                "rationale": c.rationale,
            }
            for c in decision.selected_candidates
        ],
    }


def _run_render_worker(task_id: str, req: RenderRequest, video_id: str) -> None:
    active_render_jobs[task_id]["status"] = "IN_PROGRESS"
    active_render_jobs[task_id]["progress"] = 15
    active_render_jobs[task_id]["message"] = "Initializing pipeline & verifying content rights..."

    try:
        policy = LocalRightsPolicy(os.path.join(DATA_DIR, "rights_ledger.json"), db_path=os.path.join(DATA_DIR, "jobs.db"))
        manifest = policy.check_rights(video_id)
        if not policy.verify_rights(manifest):
            policy.register_rights(
                video_id=video_id,
                basis="OPERATOR_ASSET",
                owner="Studio Operator",
                audit_notes="Auto-registered via Web Studio Render",
            )

        pipeline = build_pipeline(output_dir=CLIPS_DIR)
        vcodec = "h264_nvenc" if req.gpu else "libx264"
        profile = RenderProfile(
            layout_mode=req.layout,
            vcodec=vcodec,
            subtitle_preset=req.subtitle_preset,
            enable_outro_card=req.enable_outro,
            outro_duration=2.5,
            outro_channel_name=req.outro_channel_name,
            enable_pacing_polish=req.enable_polish,
        )

        active_render_jobs[task_id]["progress"] = 40
        active_render_jobs[task_id]["message"] = f"Milking top {req.max_clips} solid shorts with kinematic face tracking..."

        completed_jobs = pipeline.process_video_multi(
            video_id=video_id,
            max_clips=req.max_clips,
            profile=profile,
            dry_run=True,
        )

        active_render_jobs[task_id]["progress"] = 100
        active_render_jobs[task_id]["status"] = "COMPLETED"
        active_render_jobs[task_id]["message"] = f"Successfully rendered {len(completed_jobs)} solid Shorts!"

        clips_out = []
        for j in completed_jobs:
            if j.rendered_clip:
                fname = os.path.basename(j.rendered_clip.file_path)
                clips_out.append({
                    "job_id": j.job_id,
                    "filename": fname,
                    "url": f"/clips/{fname}",
                    "file_path": j.rendered_clip.file_path,
                    "duration": round(j.candidate.duration_seconds, 1) if j.candidate else 0.0,
                    "score": round(j.candidate.score, 1) if j.candidate else 0.0,
                    "hook_title": j.candidate.hook_title if j.candidate else "",
                    "file_size_mb": round(os.path.getsize(j.rendered_clip.file_path) / (1024 * 1024), 2) if os.path.exists(j.rendered_clip.file_path) else 0,
                })
        active_render_jobs[task_id]["clips"] = clips_out

    except Exception as e:
        logger.error(f"Render failed: {e}")
        active_render_jobs[task_id]["status"] = "FAILED"
        active_render_jobs[task_id]["error"] = str(e)


@app.post("/api/v1/render")
def api_render(req: RenderRequest, bg_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Triggers batch vertical 9:16 Short rendering for a video."""
    try:
        video_id = extract_youtube_video_id(req.video_id_or_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid YouTube video ID or URL: {e}")
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube video ID or URL.")

    task_id = f"task-{video_id}-{datetime.now().strftime('%H%M%S')}"
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
    return {"task_id": task_id, "status": "QUEUED", "check_status_url": f"/api/v1/render/status/{task_id}"}


@app.get("/api/v1/render/status/{task_id}")
def api_render_status(task_id: str) -> Dict[str, Any]:
    """Returns progress and rendered clip payloads for a running or completed task."""
    job = active_render_jobs.get(task_id)
    if not job:
        raise HTTPException(status_code=404, detail="Task ID not found.")
    return job


@app.get("/api/v1/clips")
def api_list_clips() -> List[Dict[str, Any]]:
    """Returns all rendered vertical clips currently stored on disk."""
    clips = []
    for p in sorted(glob.glob(os.path.join(CLIPS_DIR, "*.mp4")), key=os.path.getmtime, reverse=True):
        fname = os.path.basename(p)
        stat = os.stat(p)
        clips.append({
            "filename": fname,
            "url": f"/clips/{fname}",
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        })
    return clips


# ------------------------------------------------------------------------------
# Built-In Live Studio Web UI
# ------------------------------------------------------------------------------
HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>YouTube Clipping Intelligence Platform - Live Studio</title>
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: #151c2c;
      --border: #232d42;
      --accent: #6366f1;
      --accent-hover: #4f46e5;
      --emerald: #10b981;
      --amber: #f59e0b;
      --rose: #f43f5e;
      --text: #f8fafc;
      --text-muted: #94a3b8;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
    body { background-color: var(--bg); color: var(--text); line-height: 1.5; min-height: 100vh; }
    header { background: rgba(21, 28, 44, 0.8); backdrop-filter: blur(12px); border-bottom: 1px solid var(--border); padding: 1rem 2rem; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 50; }
    .brand { display: flex; align-items: center; gap: 0.75rem; font-weight: 700; font-size: 1.25rem; letter-spacing: -0.025em; }
    .badge { background: rgba(99, 102, 241, 0.2); color: #818cf8; font-size: 0.75rem; padding: 0.2rem 0.6rem; border-radius: 9999px; border: 1px solid rgba(99, 102, 241, 0.4); }
    .status-pill { display: flex; align-items: center; gap: 0.5rem; font-size: 0.85rem; color: var(--text-muted); }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--emerald); box-shadow: 0 0 10px var(--emerald); }
    
    .container { max-width: 1400px; margin: 2rem auto; padding: 0 1.5rem; display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; }
    @media(max-width: 1024px) { .container { grid-template-columns: 1fr; } }

    .card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 1rem; padding: 1.5rem; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3); }
    .card-title { font-size: 1.15rem; font-weight: 600; margin-bottom: 1rem; display: flex; align-items: center; gap: 0.5rem; }
    
    label { display: block; font-size: 0.85rem; color: var(--text-muted); margin-bottom: 0.4rem; font-weight: 500; }
    input[type="text"], select { width: 100%; background: #0f172a; border: 1px solid var(--border); border-radius: 0.5rem; padding: 0.75rem 1rem; color: #fff; font-size: 0.95rem; margin-bottom: 1.25rem; transition: border-color 0.2s; }
    input[type="text"]:focus, select:focus { outline: none; border-color: var(--accent); }
    
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
    .toggles { display: flex; flex-direction: column; gap: 0.75rem; margin-bottom: 1.5rem; }
    .toggle-row { display: flex; align-items: center; justify-content: space-between; font-size: 0.9rem; }
    input[type="checkbox"] { width: 1.15rem; height: 1.15rem; accent-color: var(--accent); cursor: pointer; }

    .btn-group { display: flex; gap: 1rem; }
    button { flex: 1; padding: 0.85rem 1.25rem; border-radius: 0.5rem; border: none; font-weight: 600; font-size: 0.95rem; cursor: pointer; transition: all 0.2s; display: flex; justify-content: center; align-items: center; gap: 0.5rem; }
    .btn-preview { background: #1e293b; color: #f1f5f9; border: 1px solid #334155; }
    .btn-preview:hover { background: #334155; }
    .btn-primary { background: var(--accent); color: #fff; }
    .btn-primary:hover { background: var(--accent-hover); box-shadow: 0 0 15px rgba(99, 102, 241, 0.4); }
    
    /* Progress and Output */
    .progress-box { margin-top: 1.5rem; background: #0f172a; border: 1px solid var(--border); border-radius: 0.5rem; padding: 1rem; display: none; }
    .progress-bar-bg { width: 100%; height: 8px; background: #1e293b; border-radius: 4px; overflow: hidden; margin: 0.5rem 0; }
    .progress-bar { height: 100%; width: 0%; background: var(--accent); transition: width 0.3s; }
    
    /* Clips View */
    .clips-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1.25rem; max-height: 800px; overflow-y: auto; padding-right: 0.5rem; }
    .clip-card { background: #0f172a; border: 1px solid var(--border); border-radius: 0.75rem; overflow: hidden; display: flex; flex-direction: column; }
    .video-wrapper { position: relative; width: 100%; padding-top: 177.77%; background: #000; }
    .video-wrapper video { position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: contain; }
    .clip-meta { padding: 1rem; flex: 1; display: flex; flex-direction: column; justify-content: space-between; }
    .clip-score { display: inline-block; background: rgba(16, 185, 129, 0.2); color: var(--emerald); font-weight: 700; font-size: 0.75rem; padding: 0.2rem 0.5rem; border-radius: 4px; margin-bottom: 0.5rem; }
    .clip-title { font-size: 0.9rem; font-weight: 600; line-height: 1.3; margin-bottom: 0.75rem; }
    .btn-download { background: #1e293b; border: 1px solid var(--border); color: #fff; padding: 0.5rem; border-radius: 4px; text-decoration: none; text-align: center; font-size: 0.8rem; font-weight: 600; display: block; }
    .btn-download:hover { background: var(--accent); border-color: var(--accent); }
    
    /* Audit Log */
    .audit-list { font-size: 0.85rem; color: var(--text-muted); list-style: none; display: flex; flex-direction: column; gap: 0.4rem; max-height: 250px; overflow-y: auto; background: #0f172a; padding: 0.75rem; border-radius: 0.5rem; margin-top: 1rem; }
    .audit-list li { border-left: 2px solid var(--accent); padding-left: 0.5rem; }
  </style>
</head>
<body>

  <header>
    <div class="brand">
      <span>⚡ YouTube Clipping Studio</span>
      <span class="badge">Live 24/7 Engine</span>
    </div>
    <div class="status-pill" id="healthPill">
      <div class="dot"></div>
      <span id="healthText">Auditing GPU & System...</span>
    </div>
  </header>

  <div class="container">
    <!-- Left: Studio Controls -->
    <div class="card">
      <div class="card-title">🎥 Studio Clip Controller</div>
      
      <label for="videoInput">YouTube Video URL or 11-Character ID</label>
      <input type="text" id="videoInput" placeholder="https://www.youtube.com/watch?v=nEaJMdM1djM" value="https://www.youtube.com/watch?v=nEaJMdM1djM">

      <div class="grid-2">
        <div>
          <label for="clipsCount">Milking Yield (Solid Shorts)</label>
          <select id="clipsCount">
            <option value="auto">Auto (SolidShortsDecider)</option>
            <option value="1">1 Top Clip</option>
            <option value="3" selected>3 Solid Shorts</option>
            <option value="5">5 Viral Clips</option>
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
          <label for="subPreset">Animated Subtitle Aesthetic</label>
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
        <button class="btn-preview" onclick="runPreview()">🔍 Preview Moments</button>
        <button class="btn-primary" onclick="startRender()">🚀 Render Solid Shorts</button>
      </div>

      <div class="progress-box" id="progressBox">
        <div style="display:flex; justify-content:space-between; font-size:0.85rem;">
          <span id="progressMsg">Processing...</span>
          <span id="progressPct">0%</span>
        </div>
        <div class="progress-bar-bg">
          <div class="progress-bar" id="progressBar"></div>
        </div>
      </div>

      <div id="previewResults" style="display:none; margin-top:1.5rem;">
        <div class="card-title" style="font-size:1rem;">📊 Discovered Viral Moments</div>
        <ul class="audit-list" id="auditList"></ul>
      </div>
    </div>

    <!-- Right: Rendered Library & Player -->
    <div class="card">
      <div class="card-title" style="justify-content:space-between;">
        <span>🎬 Rendered 9:16 Shorts Library</span>
        <button onclick="loadClips()" style="flex:0; padding:0.3rem 0.8rem; font-size:0.8rem; background:#1e293b; color:#fff;">↻ Refresh</button>
      </div>
      <div class="clips-grid" id="clipsGrid">
        <div style="color:var(--text-muted); font-size:0.9rem; grid-column: 1/-1; text-align:center; padding:3rem 0;">
          Loading ready-to-publish vertical clips...
        </div>
      </div>
    </div>
  </div>

  <script>
    async function checkHealth() {
      try {
        const res = await fetch('/api/v1/health');
        const data = await res.json();
        const pill = document.getElementById('healthText');
        if (data.gpu_available) {
          pill.innerText = `CUDA GPU Ready (${data.gpu_device}) | Models Pre-baked`;
        } else {
          pill.innerText = `CPU Mode Ready | FFmpeg Active`;
        }
      } catch (e) {
        document.getElementById('healthText').innerText = 'Platform API Error';
      }
    }

    async function loadClips() {
      try {
        const res = await fetch('/api/v1/clips');
        const clips = await res.json();
        const grid = document.getElementById('clipsGrid');
        if (!clips || clips.length === 0) {
          grid.innerHTML = '<div style="color:var(--text-muted); font-size:0.9rem; grid-column:1/-1; text-align:center; padding:3rem 0;">No rendered clips found on disk yet. Render one on the left!</div>';
          return;
        }
        grid.innerHTML = clips.map(c => `
          <div class="clip-card">
            <div class="video-wrapper">
              <video src="${c.url}" controls preload="metadata"></video>
            </div>
            <div class="clip-meta">
              <div>
                <span class="clip-score">9:16 Vertical Short</span>
                <div class="clip-title">${c.filename}</div>
              </div>
              <a href="${c.url}" download="${c.filename}" class="btn-download">⬇ Download (${c.size_mb} MB)</a>
            </div>
          </div>
        `).join('');
      } catch (e) {
        console.error(e);
      }
    }

    async function runPreview() {
      const url = document.getElementById('videoInput').value.trim();
      if (!url) return alert('Please enter a YouTube video URL');
      
      const pBox = document.getElementById('previewResults');
      const list = document.getElementById('auditList');
      list.innerHTML = '<li>Analyzing transcript, retention heatmap, and acoustic peaks...</li>';
      pBox.style.display = 'block';

      try {
        const res = await fetch('/api/v1/preview', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ video_id_or_url: url })
        });
        const data = await res.json();
        if (data.detail) return alert('Preview Error: ' + data.detail);

        list.innerHTML = [
          `<li><strong>Audience Yield:</strong> SolidShortsDecider chose <strong>${data.recommended_solid_shorts_count} solid clips</strong> from ${data.total_candidates_found} candidates.</li>`,
          ...data.solid_clips.map(c => `<li><strong>${c.candidate_id} (${c.score}/100):</strong> [${c.start_seconds}s - ${c.end_seconds}s] - <em>"${c.hook_title}"</em></li>`),
          ...data.decision_reasons.map(r => `<li style="color:#64748b;">${r}</li>`)
        ].join('');
      } catch (e) {
        list.innerHTML = `<li style="color:var(--rose);">Failed to extract preview: ${e.message}</li>`;
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

      pBox.style.display = 'block';
      pBar.style.width = '10%';
      pMsg.innerText = 'Dispatching render request to GPU worker...';
      pPct.innerText = '10%';

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

        const taskId = data.task_id;
        pollStatus(taskId);
      } catch (e) {
        alert('Failed to trigger render: ' + e.message);
      }
    }

    async function pollStatus(taskId) {
      const pBar = document.getElementById('progressBar');
      const pMsg = document.getElementById('progressMsg');
      const pPct = document.getElementById('progressPct');

      const interval = setInterval(async () => {
        try {
          const res = await fetch(`/api/v1/render/status/${taskId}`);
          const data = await res.json();
          pBar.style.width = `${data.progress}%`;
          pPct.innerText = `${data.progress}%`;
          pMsg.innerText = data.message;

          if (data.status === 'COMPLETED') {
            clearInterval(interval);
            pBar.style.background = 'var(--emerald)';
            pMsg.innerText = 'Render Complete! Loaded into library.';
            loadClips();
          } else if (data.status === 'FAILED') {
            clearInterval(interval);
            pBar.style.background = 'var(--rose)';
            pMsg.innerText = 'Render Failed: ' + (data.error || 'Unknown error');
          }
        } catch (e) {
          console.error(e);
        }
      }, 3000);
    }

    // Initialize
    checkHealth();
    loadClips();
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    """Serves the interactive live studio dashboard."""
    return HTML_DASHBOARD


def start_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Entry point to launch the studio server via uvicorn."""
    import uvicorn
    uvicorn.run("yt_clipping.web.server:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    start_server()
