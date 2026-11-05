# Phase 2 REST API Reference

The YouTube Clipping Intelligence Studio provides a RESTful API for video metadata resolution, highlight discovery with explainable intelligence, asynchronous batch rendering, job lifecycle management, persistent project exploration, and in-browser media range streaming.

Base URL: `http://localhost:8000/api/v1`

---

## 1. Metadata & Discovery

### POST `/metadata`
Retrieves normalized metadata for any valid YouTube URL or bare 11-character video ID. Uses YouTube Data API v3 with automatic fallback to yt-dlp.

#### Request Body
```json
{
  "video_id_or_url": "https://www.youtube.com/watch?v=nEaJMdM1djM"
}
```

#### Response (`200 OK`)
```json
{
  "video_id": "nEaJMdM1djM",
  "title": "Did the AI bubble just pop?",
  "description": "Comprehensive analysis of modern compute scaling...",
  "channel_title": "Lex Fridman",
  "channel_handle": "@lexfridman",
  "channel_id": "UCSHZKyawb77ixDdsGog4iWA",
  "view_count": 842010,
  "like_count": 32100,
  "comment_count": 1840,
  "published_at": "2026-02-15T18:00:00Z",
  "duration": 3412.0,
  "category": "Science & Technology",
  "tags": ["ai", "neural networks", "compute"],
  "thumbnail_url": "https://i.ytimg.com/vi/nEaJMdM1djM/maxresdefault.jpg",
  "canonical_url": "https://www.youtube.com/watch?v=nEaJMdM1djM",
  "metadata_provider": "youtube_data_api_v3",
  "fetched_at": "2026-11-05T22:30:00Z",
  "extraction_status": "success"
}
```

---

### POST `/preview`
Extracts candidate highlights, retention curve hotspots, SolidShortsDecider yield recommendation, grounded "Why This Short Works" intelligence assessments, and social caption packages without rendering video.

#### Request Body
```json
{
  "video_id_or_url": "https://www.youtube.com/watch?v=nEaJMdM1djM",
  "min_duration": 15.0,
  "max_duration": 60.0
}
```

#### Response (`200 OK`)
```json
{
  "video_id": "nEaJMdM1djM",
  "source_metadata": { ... },
  "total_candidates_found": 12,
  "recommended_solid_shorts_count": 3,
  "capacity_limit": 4,
  "decision_reasons": [
    "Duration (3412s) allows up to 4 solid shorts.",
    "Accepted 3 candidates above strict quality floor (72.0)."
  ],
  "solid_clips": [
    {
      "candidate_id": "cand_1",
      "start_seconds": 124.5,
      "end_seconds": 164.0,
      "duration_seconds": 39.5,
      "score": 88.5,
      "hook_title": "The Collapse of AI Training Costs",
      "rationale": "Strong opening hook with standalone narrative value.",
      "why_it_works": "Captures viewer interest immediately with a strong premise (9.0/10 hook score)...",
      "intelligence": {
        "hook_strength": 9.0,
        "context_completeness": 8.5,
        "narrative_quality": 8.2,
        "information_density": 8.0,
        "ending_quality": 8.4,
        "estimated_engagement_potential": 88.0,
        "selection_reason": "Selected from 124.5s to 164.0s with composite score 88.5/100...",
        "quality_warnings": []
      },
      "caption_package": {
        "hook_title": "The Collapse of AI Training Costs",
        "hook_opening": "When you look at the fundamental economics...",
        "core_summary": "Frontier models are becoming exponentially cheaper to run...",
        "creator_credit": "Original video and content by: @lexfridman (Lex Fridman)...",
        "thank_you_note": "Thank you to Lex Fridman for producing this content!",
        "legal_disclaimer": "This Short contains edited material from the original source...",
        "targeted_hashtags": ["#AI", "#TechTrends", "#Compute", "#Shorts", "#Highlights", "#Trending"],
        "platform_variants": {
          "youtube_shorts": "...",
          "instagram_reels": "...",
          "tiktok": "..."
        },
        "full_copy_caption": "...",
        "why_it_works": "...",
        "generation_provider": "gemini-3.5-flash-lite",
        "generation_status": "primary_model"
      }
    }
  ]
}
```

---

## 2. Rendering & Jobs

### POST `/render`
Submits an asynchronous background rendering job. Returns immediately with a unique job ID.

#### Request Body
```json
{
  "video_id_or_url": "https://www.youtube.com/watch?v=nEaJMdM1djM",
  "max_clips": 3,
  "layout": "active_speaker",
  "subtitle_preset": "hormozi",
  "enable_polish": true,
  "enable_outro": true,
  "outro_channel_name": null,
  "gpu": true
}
```

#### Response (`200 OK`)
```json
{
  "task_id": "job-nEaJMdM1djM-ab12cd",
  "job_id": "job-nEaJMdM1djM-ab12cd",
  "status": "QUEUED",
  "check_status_url": "/api/v1/jobs/job-nEaJMdM1djM-ab12cd"
}
```

---

### GET `/jobs/{job_id}`
Returns current progress, staged execution state, diagnostic error (if any), and rendered clip artifacts.

#### Response (`200 OK`)
```json
{
  "job_id": "job-nEaJMdM1djM-ab12cd",
  "project_id": "proj_nEaJMdM1djM",
  "video_id": "nEaJMdM1djM",
  "status": "completed",
  "progress": 100,
  "current_stage": "completed",
  "message": "Successfully rendered 3 solid Shorts!",
  "created_at": "2026-11-05T22:31:00Z",
  "started_at": "2026-11-05T22:31:02Z",
  "completed_at": "2026-11-05T22:31:45Z",
  "error": null,
  "clips": [
    {
      "clip_id": "job-nEaJMdM1djM-ab12cd-clip1",
      "filename": "clip_nEaJMdM1djM_1.mp4",
      "url": "/clips/clip_nEaJMdM1djM_1.mp4",
      "file_path": "data/rendered_clips/clip_nEaJMdM1djM_1.mp4",
      "duration": 39.5,
      "score": 88.5,
      "hook_title": "The Collapse of AI Training Costs",
      "file_size_mb": 14.25,
      "qa_status": "PASSED"
    }
  ]
}
```

---

### POST `/jobs/{job_id}/cancel`
Signals immediate cooperative cancellation of an active rendering worker.

#### Response (`200 OK`)
```json
{
  "job_id": "job-nEaJMdM1djM-ab12cd",
  "status": "cancelled",
  "message": "Job cancellation signaled successfully."
}
```

---

## 3. Persistent Clips & Projects

### GET `/clips`
Returns all rendered clips stored on disk, merged from persistent project sidecars and legacy media.

#### Response Item Fields
- `clip_id`: Unique identifier for the clip.
- `project_id`: Parent project identifier.
- `filename`: Local filename on disk.
- `url`: Direct relative link.
- `playback_url`: Range-streaming media endpoint (`/api/v1/clips/{clip_id}/media`).
- `download_url`: Attachment download endpoint (`/api/v1/clips/{clip_id}/download`).
- `file_path`: Absolute path on the host.
- `start_seconds` / `end_seconds` / `duration`: Timing boundaries.
- `score`: Ranking score (0-100).
- `hook_title`: Engaging clip title.
- `caption_package`: Structured multi-platform social caption package.
- `intelligence`: 10-dimension explainability metrics.
- `validation_status`: QA verification status (`PASSED`, `WARNING`, `FAILED`, `MISSING_MEDIA`).
- `created_at`: Timestamp string.

### GET `/clips/{clip_id}`
Returns full sidecar metadata for a specific clip ID.

### POST `/clips/{clip_id}/regenerate_caption`
Regenerates the AI caption package for an existing clip using configured Gemini cascading models (or deterministic offline fallback).

#### Request Body (Optional)
```json
{
  "focus_topic": "AI compute scalability",
  "audience": "Developers & founders"
}
```

#### Response (`200 OK`)
```json
{
  "clip_id": "clip_nEaJMdM1djM_1",
  "status": "success",
  "caption_package": {
    "hook_title": "The Collapse of AI Training Costs",
    "hook_opening": "...",
    "core_summary": "...",
    "creator_credit": "Original video and content by: Lex Fridman",
    "thank_you_note": "...",
    "legal_disclaimer": "...",
    "targeted_hashtags": ["#AI", "#Tech", "..."],
    "platform_variants": { ... },
    "full_copy_caption": "...",
    "why_it_works": "...",
    "copyright_awareness": {
      "original_source_url": "https://www.youtube.com/watch?v=nEaJMdM1djM",
      "creator_identity": "Lex Fridman",
      "creator_handle": null,
      "permission_status": "unverified_fair_use_commentary",
      "license_status": "standard_youtube",
      "attribution_info": "Original video and content by: Lex Fridman",
      "transformation_performed": "Algorithmic clipping, active-speaker reframing, Hormozi subtitles, and critical context summary.",
      "removal_request_info": "Content will be promptly removed upon request by the copyright owner.",
      "disclaimer": "..."
    },
    "generation_provider": "gemini-3.5-flash-lite",
    "generation_status": "primary_model"
  }
}
```

### GET `/clips/{clip_id}/download`
Downloads the rendered MP4 file as an attachment.

### GET `/clips/{clip_id}/media`
Streams video with full HTTP Range request support (`206 Partial Content`) for browser `<video>` timeline seeking.

### GET `/projects`
Lists all persistent projects ordered by most recent update.

### GET `/projects/{project_id}`
Retrieves project details, source metadata, and associated clips.

---

## 4. Diagnostics

### GET `/health`
Returns environment health, CUDA GPU detection, FFmpeg readiness, Gemini model name, and storage metrics without exposing API credentials.
