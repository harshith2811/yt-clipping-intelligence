"""
Native Model Context Protocol (MCP) JSON-RPC 2.0 Stdio Server.
Enables AI agent orchestration and desktop LLMs to invoke clipping tools
over line-delimited JSON-RPC stdio transport.
"""

from typing import Dict, Any, Optional, List, TextIO, Tuple
import sys
import os
import json
import logging
import traceback
import hashlib
from datetime import datetime, timezone

from ..ingestion.asset_provider import extract_youtube_video_id, LocalAssetProvider
from ..rights.gate import LocalRightsPolicy
from ..discovery.attribution_engine import AttributionEngine, CreatorPolicy
from ..discovery.heatmap import HeatmapAnalyzer
from ..discovery.channel_watcher import resolve_channel_identifier
from ..discovery.pinger_daemon import PingerDaemon
from ..transcription.transcriber import LocalTranscriber
from ..detection.segmenter import ContextAwareSegmenter, suppress_overlapping_candidates
from ..scoring.scorecard import ExplainableScorecardScorer
from ..orchestration.state_machine import JobJournal
from ..orchestration.queue import JobQueue
from ..contracts.models import RenderProfile, HighlightCandidate, JobStatus, Transcript, ScoreBreakdown

logger = logging.getLogger("yt_clipping.mcp")


class MCPServer:
    """
    Standard-compliant MCP JSON-RPC 2.0 stdio server.
    Exposes pipeline subsystems as discrete callable tools for AI agents.
    """

    PROTOCOL_VERSION = "2024-11-05"
    SERVER_NAME = "yt-clipping-intelligence"
    SERVER_VERSION = "1.0.0"

    TOOL_DEFINITIONS = [
        {
            "name": "discover_channel_uploads",
            "description": "Discover recent video uploads from a YouTube creator channel via zero-quota RSS Atom feed parser and monitored channel registry.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "YouTube Channel ID (e.g. UC...), handle (e.g. @hubermanlab), or channel URL",
                    },
                    "max_videos": {
                        "type": "integer",
                        "description": "Maximum number of recent uploads to return (default: 10)",
                        "default": 10,
                    },
                },
                "required": ["channel_id"],
            },
        },
        {
            "name": "verify_source_rights",
            "description": "Verify clipping authorization and legal copyright policy for a video against the transactional SQLite rights ledger and creator attribution engine.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "video_id": {
                        "type": "string",
                        "description": "YouTube 11-character video ID or full YouTube URL",
                    },
                    "policy_type": {
                        "type": "string",
                        "description": "Clipping rights policy filter: 'creator' (creator affiliate/permission), 'legal' (strict ledger grant), 'cc_by' (Creative Commons)",
                        "default": "creator",
                        "enum": ["creator", "legal", "cc_by"],
                    },
                },
                "required": ["video_id"],
            },
        },
        {
            "name": "analyze_replay_heatmap",
            "description": "Analyze YouTube 'Most Replayed' retention curve and extract topological peaks and viral audience engagement moments.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "video_id": {
                        "type": "string",
                        "description": "YouTube 11-character video ID",
                    },
                },
                "required": ["video_id"],
            },
        },
        {
            "name": "evaluate_highlight_candidates",
            "description": "Detect and score high-virality short-form highlight candidates for a video using local explainable heuristic intelligence or cloud multimodal Gemini Flash.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "video_id": {
                        "type": "string",
                        "description": "YouTube 11-character video ID",
                    },
                    "engine": {
                        "type": "string",
                        "description": "Evaluation intelligence engine: 'heuristic' (fast local scorecard with heatmap signals) or 'gemini' (Gemini Flash multimodal cloud provider)",
                        "default": "heuristic",
                        "enum": ["heuristic", "gemini"],
                    },
                },
                "required": ["video_id"],
            },
        },
        {
            "name": "render_vertical_clip",
            "description": "Render a vertical 9:16 short clip from source video with kinetic word-level subtitles, reframing filtergraphs, and optional stacked multi-speaker layout.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "video_id": {
                        "type": "string",
                        "description": "YouTube 11-character video ID",
                    },
                    "start_sec": {
                        "type": "number",
                        "description": "Clip start timestamp in seconds",
                    },
                    "end_sec": {
                        "type": "number",
                        "description": "Clip end timestamp in seconds",
                    },
                    "layout": {
                        "type": "string",
                        "description": "Visual layout format: 'stacked' / 'split_screen', 'blur_background', 'crop_center', 'active_speaker'",
                        "default": "stacked",
                        "enum": ["stacked", "split_screen", "blur_background", "crop_center", "active_speaker"],
                    },
                    "preset": {
                        "type": "string",
                        "description": "Kinetic subtitle aesthetic preset: 'hormozi', 'beast_bounce', 'neon_cyber', 'karaoke_gold', 'bold_social', 'podcast'",
                        "default": "hormozi",
                        "enum": ["hormozi", "beast_bounce", "neon_cyber", "karaoke_gold", "bold_social", "podcast"],
                    },
                },
                "required": ["video_id", "start_sec", "end_sec"],
            },
        },
        {
            "name": "inspect_job_status",
            "description": "Inspect the durable state, execution progress, checkpoints, and QA status of a clipping pipeline job in SQLite.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Canonical job ID (e.g. 'job-xyz-123') or 'all'/'queue' for general queue metrics",
                    },
                },
                "required": ["job_id"],
            },
        },
    ]

    def __init__(
        self,
        db_path: str = "data/jobs.db",
        assets_dir: str = "data/assets",
        transcripts_dir: str = "data/transcripts",
        output_dir: str = "data/rendered_clips",
        cache_dir: str = "data/heatmaps",
        ledger_path: str = "data/rights_ledger.json",
        log_level: str = "INFO",
        stdin: Optional[TextIO] = None,
        stdout: Optional[TextIO] = None,
        stderr: Optional[TextIO] = None,
    ):
        self.db_path = db_path
        self.assets_dir = assets_dir
        self.transcripts_dir = transcripts_dir
        self.output_dir = output_dir
        self.cache_dir = cache_dir
        self.ledger_path = ledger_path
        self.log_level = log_level.upper()

        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.stderr = stderr or sys.stderr

        self.is_initialized = False

        self._configure_logging()
        self._configure_streams()

    def _configure_logging(self) -> None:
        """Configures logging strictly to stderr to prevent polluting the stdio JSON-RPC stream."""
        level = getattr(logging, self.log_level, logging.INFO)
        logging.basicConfig(
            stream=self.stderr,
            level=level,
            format="%(asctime)s [%(levelname)s] [mcp] %(message)s",
            force=True,
        )

    def _configure_streams(self) -> None:
        """Configures UTF-8 encoding for standard I/O streams on Windows."""
        for stream in (self.stdin, self.stdout, self.stderr):
            if hasattr(stream, "reconfigure"):
                try:
                    stream.reconfigure(encoding="utf-8")
                except Exception:
                    pass

    def run_stdio(self) -> None:
        """Main JSON-RPC line-delimited message loop over stdio."""
        logger.info(f"Starting {self.SERVER_NAME} v{self.SERVER_VERSION} MCP stdio server")
        while True:
            try:
                line = self.stdin.readline()
                if not line:
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                response = self.handle_message(stripped)
                if response is not None:
                    self.stdout.write(response + "\n")
                    self.stdout.flush()
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt received, exiting MCP server.")
                break
            except Exception as e:
                logger.error(f"Unhandled error in MCP framing loop: {e}\n{traceback.format_exc()}")
                err_resp = self._make_jsonrpc_error(None, -32603, f"Internal Error: {str(e)}")
                self.stdout.write(json.dumps(err_resp, ensure_ascii=False) + "\n")
                self.stdout.flush()

    run = run_stdio

    def handle_message(self, message_str: str) -> Optional[str]:
        """Parses a single JSON-RPC frame and returns a serialized JSON-RPC response, or None."""
        try:
            req = json.loads(message_str)
        except Exception:
            err = self._make_jsonrpc_error(None, -32700, "Parse error: Invalid JSON")
            return json.dumps(err, ensure_ascii=False)

        if not isinstance(req, dict):
            err = self._make_jsonrpc_error(None, -32600, "Invalid Request: Expected JSON object")
            return json.dumps(err, ensure_ascii=False)

        req_id = req.get("id")
        method = req.get("method")

        # Notification handling (no ID)
        if req_id is None:
            if method == "notifications/initialized":
                self.is_initialized = True
                logger.info("MCP client initialized notification received.")
            return None

        # Validate method for requests with ID
        if "method" not in req or not isinstance(method, str):
            err = self._make_jsonrpc_error(req_id, -32600, "Invalid Request: 'method' must be a string")
            return json.dumps(err, ensure_ascii=False)

        # Extract and sanitize params
        params = req.get("params")
        if not isinstance(params, dict):
            params = {}

        # Dispatch method
        if method == "initialize":
            resp = self._handle_initialize(req_id, params)
        elif method == "ping":
            resp = self._handle_ping(req_id)
        elif method == "tools/list":
            resp = self._handle_tools_list(req_id)
        elif method == "tools/call":
            resp = self._handle_tools_call(req_id, params)
        else:
            resp = self._make_jsonrpc_error(req_id, -32601, f"Method not found: {method}")

        return json.dumps(resp, ensure_ascii=False)

    def _handle_initialize(self, req_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handles MCP initialize handshake."""
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": self.PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {},
                },
                "serverInfo": {
                    "name": self.SERVER_NAME,
                    "version": self.SERVER_VERSION,
                },
            },
        }

    def _handle_ping(self, req_id: Any) -> Dict[str, Any]:
        """Handles MCP ping."""
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {},
        }

    def _handle_tools_list(self, req_id: Any) -> Dict[str, Any]:
        """Returns the catalog of 6 pipeline tools."""
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": self.TOOL_DEFINITIONS,
            },
        }

    def _handle_tools_call(self, req_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatches tool execution."""
        tool_name = params.get("name") if isinstance(params, dict) else None
        arguments = params.get("arguments", {}) if isinstance(params, dict) else {}
        if not isinstance(arguments, dict):
            arguments = {}

        if not tool_name:
            return self._make_jsonrpc_error(req_id, -32602, "Invalid params: Missing tool 'name'")

        tool_def = next((t for t in self.TOOL_DEFINITIONS if t["name"] == tool_name), None)
        if not tool_def:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error: Unknown tool '{tool_name}'"}],
                    "isError": True,
                },
            }

        # Check required properties
        required_props = tool_def["inputSchema"].get("required", [])
        for prop in required_props:
            if prop not in arguments or arguments[prop] is None:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error: Missing required argument '{prop}'"}],
                        "isError": True,
                    },
                }

        try:
            if tool_name == "discover_channel_uploads":
                content, is_error = self._tool_discover_channel_uploads(arguments)
            elif tool_name == "verify_source_rights":
                content, is_error = self._tool_verify_source_rights(arguments)
            elif tool_name == "analyze_replay_heatmap":
                content, is_error = self._tool_analyze_replay_heatmap(arguments)
            elif tool_name == "evaluate_highlight_candidates":
                content, is_error = self._tool_evaluate_highlight_candidates(arguments)
            elif tool_name == "render_vertical_clip":
                content, is_error = self._tool_render_vertical_clip(arguments)
            elif tool_name == "inspect_job_status":
                content, is_error = self._tool_inspect_job_status(arguments)
            else:
                content = f"Error: Unhandled tool '{tool_name}'"
                is_error = True
        except Exception as e:
            logger.error(f"Exception during tool '{tool_name}' execution: {e}\n{traceback.format_exc()}")
            content = f"Error executing tool '{tool_name}': {str(e)}"
            is_error = True

        text_output = content if isinstance(content, str) else json.dumps(content, indent=2, ensure_ascii=False, default=str)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": text_output,
                    }
                ],
                "isError": is_error,
            },
        }

    # ---------------- Tool Implementations ----------------

    def _tool_discover_channel_uploads(self, args: Dict[str, Any]) -> Tuple[Any, bool]:
        """Tool 1: discover_channel_uploads."""
        channel_id_raw = args.get("channel_id", "")
        max_videos = int(args.get("max_videos", 10))

        cid, handle, name = resolve_channel_identifier(channel_id_raw)
        videos: List[Dict[str, Any]] = []

        daemon = PingerDaemon(db_path=self.db_path)
        try:
            xml_data, _, _, _ = daemon.fetch_channel_feed(cid)
            if xml_data:
                parsed = daemon.parse_atom_feed(xml_data)
                for p in parsed[:max_videos]:
                    videos.append(
                        {
                            "video_id": p.get("video_id"),
                            "title": p.get("title"),
                            "published_at": p.get("published_at"),
                            "url": p.get("url"),
                            "channel_id": cid,
                            "channel_name": name,
                        }
                    )
        except Exception as e:
            logger.warning(f"Live Atom feed fetch failed for {cid} ({e}), checking database cache")

        # Database fallback if feed fetch yielded no videos
        if not videos:
            try:
                conn = daemon.db.get_connection()
                try:
                    cur = conn.execute(
                        "SELECT video_id, title, published_at, hourly_velocity FROM discovered_uploads WHERE channel_id = ? ORDER BY published_at DESC LIMIT ?",
                        (cid, max_videos),
                    )
                    for r in cur.fetchall():
                        videos.append(
                            {
                                "video_id": r[0],
                                "title": r[1],
                                "published_at": r[2],
                                "url": f"https://www.youtube.com/watch?v={r[0]}",
                                "channel_id": cid,
                                "channel_name": name,
                            }
                        )
                finally:
                    conn.close()
            except Exception:
                pass

        payload = {
            "status": "success",
            "channel_id": cid,
            "channel_name": name,
            "handle": handle,
            "video_count": len(videos),
            "videos": videos,
        }
        return payload, False

    @staticmethod
    def _clean_video_id(raw_id: str) -> str:
        raw = raw_id.strip()
        if "youtube.com" in raw or "youtu.be" in raw:
            try:
                return extract_youtube_video_id(raw)
            except Exception:
                return raw
        return raw

    def _tool_verify_source_rights(self, args: Dict[str, Any]) -> Tuple[Any, bool]:
        """Tool 2: verify_source_rights."""
        raw_id = args.get("video_id", "")
        policy_type = args.get("policy_type", "creator")
        video_id = self._clean_video_id(raw_id)

        policy = LocalRightsPolicy(self.ledger_path, db_path=self.db_path)
        manifest = policy.check_rights(video_id)
        can_process = policy.verify_rights(manifest)

        attribution_eng = AttributionEngine(db_path=self.db_path)
        creator_policy = attribution_eng.get_creator_policy(channel_id=manifest.owner_name or video_id)

        is_safe = can_process or (policy_type == "creator" and creator_policy != CreatorPolicy.STRICT_COPYRIGHT)

        payload = {
            "status": "success",
            "video_id": video_id,
            "can_process": bool(can_process),
            "rights_status": manifest.status.value,
            "rights_basis": manifest.basis.value,
            "owner_name": manifest.owner_name,
            "creator_policy": creator_policy.value,
            "is_safe_to_clip": bool(is_safe),
            "audit_notes": manifest.audit_notes,
            "attribution_required": True,
        }
        return payload, False

    def _tool_analyze_replay_heatmap(self, args: Dict[str, Any]) -> Tuple[Any, bool]:
        """Tool 3: analyze_replay_heatmap."""
        raw_id = args.get("video_id", "")
        video_id = self._clean_video_id(raw_id)

        analyzer = HeatmapAnalyzer(cache_dir=self.cache_dir)
        heatmap = analyzer.extract_heatmap(video_id)

        peaks_payload = [p.to_dict() for p in heatmap.peaks]
        global_peak_payload = heatmap.global_peak.to_dict() if heatmap.global_peak else None

        payload = {
            "status": "success",
            "video_id": video_id,
            "source": heatmap.source,
            "total_points": len(heatmap.points),
            "peak_count": len(heatmap.peaks),
            "global_peak": global_peak_payload,
            "peaks": peaks_payload,
        }
        return payload, False

    def _tool_evaluate_highlight_candidates(self, args: Dict[str, Any]) -> Tuple[Any, bool]:
        """Tool 4: evaluate_highlight_candidates."""
        raw_id = args.get("video_id", "")
        engine = args.get("engine", "heuristic").lower()
        video_id = self._clean_video_id(raw_id)
        logger.info(f"video_id='{video_id}', checking transcripts in {self.transcripts_dir}: {os.listdir(self.transcripts_dir) if os.path.exists(self.transcripts_dir) else 'NOT FOUND'}")

        transcriber = LocalTranscriber(cache_dir=self.transcripts_dir)
        transcript = transcriber.load_from_cache(video_id)
        if not transcript:
            for fname in [f"{video_id}.json", f"{video_id}.transcript.json"]:
                p = os.path.join(self.transcripts_dir, fname)
                if os.path.exists(p):
                    try:
                        with open(p, "r", encoding="utf-8") as f:
                            transcript = Transcript.from_dict(json.load(f))
                        break
                    except Exception as e:
                        logger.error(f"Error loading transcript from {p}: {e}")

        if not transcript:
            return (
                f"Error: Transcript not found for video '{video_id}'. Please ensure transcription exists in '{self.transcripts_dir}'.",
                True,
            )

        if engine == "gemini":
            try:
                from ..scoring.gemini_provider import GeminiHighlightDiscoveryProvider
                gemini_prov = GeminiHighlightDiscoveryProvider()
                candidates = gemini_prov.detect_candidates(transcript=transcript, max_candidates=5)
                candidates_payload = [
                    {
                        "candidate_id": c.candidate_id,
                        "start_seconds": c.start_seconds,
                        "end_seconds": c.end_seconds,
                        "duration_seconds": c.duration_seconds,
                        "score": c.score,
                        "hook_title": c.hook_title,
                        "suggested_description": c.suggested_description,
                        "transcript_text": c.transcript_text,
                        "breakdown": c.breakdown.to_dict() if hasattr(getattr(c, "breakdown", None), "to_dict") else getattr(c, "breakdown", {}),
                    }
                    for c in candidates
                ]
                return {
                    "status": "success",
                    "video_id": video_id,
                    "engine_used": "gemini",
                    "candidate_count": len(candidates_payload),
                    "candidates": candidates_payload,
                }, False
            except Exception as e:
                logger.warning(f"Gemini evaluation unavailable ({e}), falling back to heuristic engine")
                engine = "heuristic"

        # Heuristic engine
        analyzer = HeatmapAnalyzer(cache_dir=self.cache_dir)
        heatmap = analyzer.extract_heatmap(video_id)

        segmenter = ContextAwareSegmenter(default_min_duration=15.0, default_max_duration=60.0)
        candidates = segmenter.detect_candidates(transcript=transcript, heatmap=heatmap)

        scorer = ExplainableScorecardScorer()
        scored_candidates = [
            scorer.score_candidate(cand, transcript=transcript, heatmap=heatmap)
            for cand in candidates
        ]

        suppressed = suppress_overlapping_candidates(scored_candidates)
        candidates_payload = [
            {
                "candidate_id": c.candidate_id,
                "start_seconds": c.start_seconds,
                "end_seconds": c.end_seconds,
                "duration_seconds": c.duration_seconds,
                "score": c.score,
                "hook_title": c.hook_title or f"Highlight from {c.start_seconds:.0f}s to {c.end_seconds:.0f}s",
                "suggested_description": c.suggested_description or "",
                "transcript_text": c.transcript_text or "",
                "breakdown": c.breakdown.to_dict() if hasattr(c.breakdown, "to_dict") else getattr(c, "breakdown", {}),
            }
            for c in suppressed
        ]

        payload = {
            "status": "success",
            "video_id": video_id,
            "engine_used": "heuristic",
            "candidate_count": len(candidates_payload),
            "candidates": candidates_payload,
        }
        return payload, False

    def _tool_render_vertical_clip(self, args: Dict[str, Any]) -> Tuple[Any, bool]:
        """Tool 5: render_vertical_clip."""
        raw_id = args.get("video_id", "")
        start_sec = float(args.get("start_sec", 0.0))
        end_sec = float(args.get("end_sec", 0.0))
        layout = args.get("layout", "stacked")
        preset = args.get("preset", "hormozi")

        if layout == "stacked":
            layout = "split_screen"

        video_id = self._clean_video_id(raw_id)

        if end_sec <= start_sec:
            return f"Error: end_sec ({end_sec}) must be strictly greater than start_sec ({start_sec})", True

        source_path = None
        for ext in [".mp4", ".mkv", ".webm", ".mov"]:
            candidate_path = os.path.join(self.assets_dir, f"{video_id}{ext}")
            if os.path.exists(candidate_path):
                source_path = os.path.abspath(candidate_path)
                break

        if not source_path or not os.path.exists(source_path):
            return f"Error: Source asset for video '{video_id}' not found in '{self.assets_dir}'. Ingest asset first.", True

        os.makedirs(self.output_dir, exist_ok=True)
        clip_id = f"clip-mcp-{video_id}-{int(start_sec)}_{int(end_sec)}"
        profile = RenderProfile(
            name="mcp_render",
            layout_mode=layout,
            subtitle_preset=preset,
            width=1080,
            height=1920,
        )

        from ..contracts.models import ScoreBreakdown
        candidate = HighlightCandidate(
            candidate_id=clip_id,
            video_id=video_id,
            start_seconds=start_sec,
            end_seconds=end_sec,
            duration_seconds=end_sec - start_sec,
            score=85.0,
            breakdown=ScoreBreakdown(hook_score=8.5, moment_score=8.5),
            hook_title=f"Highlight from {int(start_sec)}s to {int(end_sec)}s",
        )

        from ..rendering.renderer import FFmpegRenderer
        renderer = FFmpegRenderer()
        transcriber = LocalTranscriber(cache_dir=self.transcripts_dir)
        transcript = transcriber.load_from_cache(video_id)

        try:
            rendered = renderer.render_clip(
                source_path=source_path,
                candidate=candidate,
                profile=profile,
                output_dir=self.output_dir,
                transcript=transcript,
            )
            file_size = os.path.getsize(rendered.file_path) if os.path.exists(rendered.file_path) else 0
            payload = {
                "status": "success",
                "video_id": video_id,
                "clip_id": rendered.clip_id,
                "output_file": rendered.file_path,
                "duration_seconds": round(end_sec - start_sec, 2),
                "width": profile.width,
                "height": profile.height,
                "file_size_bytes": file_size,
                "sha256": rendered.file_hash,
                "layout_applied": layout,
                "subtitle_preset_applied": preset,
            }
            return payload, False
        except Exception as e:
            logger.error(f"Render failed: {e}\n{traceback.format_exc()}")
            return f"Error rendering clip: {str(e)}", True

    def _tool_inspect_job_status(self, args: Dict[str, Any]) -> Tuple[Any, bool]:
        """Tool 6: inspect_job_status."""
        job_id = args.get("job_id", "").strip()

        if job_id.lower() in ("all", "queue", "stats"):
            queue = JobQueue(db_path=self.db_path)
            status_data = queue.get_status()
            payload = {
                "status": "success",
                "job_id": job_id,
                "queue_telemetry": status_data,
            }
            return payload, False

        journal = JobJournal(db_path=self.db_path)
        job = journal.get_job(job_id)
        if not job:
            return f"Error: Job '{job_id}' not found in SQLite database '{self.db_path}'.", True

        payload = {
            "status": "success",
            "job_id": job.job_id,
            "video_id": job.video_id,
            "current_stage": job.current_stage.value,
            "status_value": job.status.value,
            "retry_count": job.retry_count,
            "max_retries": job.max_retries,
            "checkpoints": job.checkpoints,
            "error_message": job.error_message,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        }
        return payload, False

    def _make_jsonrpc_error(self, req_id: Any, code: int, message: str) -> Dict[str, Any]:
        """Helper to format JSON-RPC 2.0 error response."""
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": code,
                "message": message,
            },
        }
