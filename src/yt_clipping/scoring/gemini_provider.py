"""
Cloud Multimodal Highlight Discovery Provider using Google Gemini Flash.
Implements HighlightDetector and HighlightScorer contracts with zero VRAM overhead
and seamless automatic degradation to local heuristic intelligence.
"""

from __future__ import annotations
from typing import List, Optional, Dict, Any, Union
import os
import re
import math
import json
import uuid
import time
import urllib.request
import urllib.error
import socket
import logging

from ..contracts.interfaces import HighlightDetector, HighlightScorer
from ..contracts.models import (
    HighlightCandidate,
    ScoreBreakdown,
    Transcript,
    HeatmapData,
)
from ..detection.segmenter import ContextAwareSegmenter
from .scorecard import ExplainableScorecardScorer

logger = logging.getLogger(__name__)

# Canonical contract alias
CandidateClip = HighlightCandidate

# Case-insensitive markdown code fence regex for JSON extraction
FENCE_REGEX = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)



PROMPT_TEMPLATE = """
You are a master short-form video editor for TikTok, YouTube Shorts, and Instagram Reels.
Your task is to analyze the following video metadata and transcript to identify the top {max_clips} viral highlight moments.

### Constraints:
- Duration: Each highlight MUST be between {min_duration:.1f} and {max_duration:.1f} seconds long (duration = end_seconds - start_seconds).
- Sentence Boundaries: Highlights MUST begin cleanly at the start of a complete sentence and MUST end cleanly at the end of a sentence.
- NO Dangling Connectors: Do NOT start clips with "and", "or", "but", "so", "because", "uh", "um", "like".
- NO Sponsor Reads: Reject any segments containing promo codes, merch plugs, sponsorships, or affiliate links.
- Standalone Viability: The clip must deliver complete narrative value without needing context from the rest of the video.

### Video Metadata:
- Video ID: {video_id}
- Video Title: {video_title}
- Channel: {channel_title}
- Total Duration: {total_duration:.1f} seconds

### Audience Retention / Replay Heatmap Signals:
{retention_context}

### Transcript Segments (with timestamps):
{formatted_transcript}

### Required JSON Output Format:
Respond ONLY with a valid JSON object matching this schema:
{{
  "highlights": [
    {{
      "start_seconds": <float, start timestamp in seconds>,
      "end_seconds": <float, end timestamp in seconds>,
      "hook_title": "<punchy 5-8 word viral title>",
      "suggested_description": "<1-2 sentence description with viral hashtags>",
      "transcript_text": "<verbatim transcript excerpt of the clip>",
      "hook_score": <float 0.0 to 10.0>,
      "moment_score": <float 0.0 to 10.0>,
      "coherence_score": <float 0.0 to 10.0>,
      "pacing_score": <float 0.0 to 10.0>,
      "heatmap_score": <float 0.0 to 10.0>,
      "rationale": "<concise explanation of hook, arc, and payoff>"
    }}
  ]
}}
"""


class GeminiHighlightDiscoveryProvider(HighlightDetector, HighlightScorer):
    """
    Multimodal highlight discovery provider powered by Gemini 1.5 Flash.
    Executes in the cloud with zero GPU VRAM allocation.
    Automatically degrades gracefully to ContextAwareSegmenter + ExplainableScorecardScorer.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        api_base: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
        offline_mode: bool = False,
        config: Optional[Any] = None,
        heuristic_detector: Optional[HighlightDetector] = None,
        heuristic_scorer: Optional[HighlightScorer] = None,
    ):
        # Resolve config/env with safe string coercion
        raw_key = (
            api_key
            or (getattr(config, "gemini_api_key", None) if config else None)
            or (getattr(config, "llm_api_key", None) if config else None)
            or (config.get("gemini_api_key") if isinstance(config, dict) else None)
            or (config.get("llm_api_key") if isinstance(config, dict) else None)
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or ""
        )
        self.api_key = str(raw_key).strip()

        raw_model = (
            model
            or (getattr(config, "gemini_model", None) if config else None)
            or (config.get("gemini_model") if isinstance(config, dict) else None)
            or os.getenv("GEMINI_MODEL")
            or "gemini-1.5-flash"
        )
        self.model = str(raw_model).strip()

        raw_api_base = (
            api_base
            or (getattr(config, "gemini_api_base", None) if config else None)
            or (config.get("gemini_api_base") if isinstance(config, dict) else None)
            or os.getenv("GEMINI_API_BASE")
            or "https://generativelanguage.googleapis.com/v1beta"
        )
        self.api_base = str(raw_api_base).rstrip("/")

        self.timeout = timeout
        self.max_retries = max_retries
        raw_offline = (
            offline_mode
            or (getattr(config, "offline_mode", False) if config else False)
            or (config.get("offline_mode", False) if isinstance(config, dict) else False)
            or os.getenv("GEMINI_OFFLINE_MODE", "").lower() in ("true", "1", "yes")
            or os.getenv("OFFLINE_MODE", "").lower() in ("true", "1", "yes")
        )
        self.offline_mode = bool(raw_offline)

        # Fallback engines
        self.heuristic_detector = heuristic_detector or ContextAwareSegmenter()
        self.heuristic_scorer = heuristic_scorer or ExplainableScorecardScorer()

    @property
    def is_cloud_available(self) -> bool:
        """Returns True if cloud API calls are configured and permitted."""
        return bool(self.api_key) and not self.offline_mode

    def is_available(self) -> bool:
        """Method alias for is_cloud_available satisfying AlignmentEngine/Provider protocol."""
        return self.is_cloud_available

    def detect_candidates(
        self,
        transcript: Transcript,
        min_duration: float = 20.0,
        max_duration: float = 60.0,
        heatmap: Optional[HeatmapData] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[HighlightCandidate]:
        """
        Segments transcript into highlight candidates using Gemini Flash.
        Degrades gracefully to ContextAwareSegmenter on failure.
        """
        if not self.is_cloud_available:
            logger.info("Gemini provider cloud execution unavailable. Using heuristic detector.")
            return self.heuristic_detector.detect_candidates(
                transcript, min_duration=min_duration, max_duration=max_duration, heatmap=heatmap, **kwargs
            )

        try:
            candidates = self._call_gemini_detection(
                transcript=transcript,
                min_duration=min_duration,
                max_duration=max_duration,
                heatmap=heatmap,
                metadata=metadata,
            )
            if candidates:
                return candidates
            logger.warning("Gemini returned zero candidates. Falling back to heuristic detector.")
        except Exception as exc:
            logger.warning("Gemini cloud detection failed (%s). Falling back to heuristic detector.", exc)

        return self.heuristic_detector.detect_candidates(
            transcript, min_duration=min_duration, max_duration=max_duration, heatmap=heatmap, **kwargs
        )

    def score_candidate(
        self,
        candidate: HighlightCandidate,
        transcript: Transcript,
        heatmap: Optional[HeatmapData] = None,
        **kwargs: Any,
    ) -> HighlightCandidate:
        """
        Scores candidate hook, moment, and coherence.
        If candidate was generated by Gemini, validates or refines the score breakdown.
        Degrades gracefully to ExplainableScorecardScorer.
        """
        if candidate.score > 0.0 and candidate.breakdown and candidate.breakdown.hook_score > 0.0:
            # Score already computed via Gemini discovery
            return candidate

        return self.heuristic_scorer.score_candidate(
            candidate, transcript, heatmap=heatmap, **kwargs
        )

    def discover_highlights(
        self,
        video_path: Optional[str] = None,
        transcript: Optional[Union[Transcript, Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        min_duration: float = 20.0,
        max_duration: float = 60.0,
        heatmap: Optional[HeatmapData] = None,
        **kwargs: Any,
    ) -> List[HighlightCandidate]:
        """
        Unified discovery method matching PROJECT.md interface contract.
        Supports both positional and keyword invocations:
        - discover_highlights(video_path, transcript, metadata, ...)
        - discover_highlights(video_path, metadata_dict, ...)
        - discover_highlights(transcript=transcript, ...)
        """
        resolved_metadata: Dict[str, Any] = dict(metadata or {})
        resolved_transcript: Optional[Transcript] = None

        if isinstance(transcript, dict):
            # Positional call where 2nd parameter is metadata dict
            passed_dict = transcript
            merged = dict(passed_dict)
            merged.update(resolved_metadata)
            resolved_metadata = merged

            candidate_transcript = passed_dict.get("transcript")
            if isinstance(candidate_transcript, Transcript):
                resolved_transcript = candidate_transcript
            elif isinstance(candidate_transcript, dict):
                try:
                    resolved_transcript = Transcript.from_dict(candidate_transcript)
                except Exception:
                    resolved_transcript = None
            elif isinstance(candidate_transcript, str):
                resolved_transcript = Transcript(
                    video_id=resolved_metadata.get("video_id", "unknown"),
                    language=resolved_metadata.get("language", "en"),
                    duration_seconds=float(resolved_metadata.get("duration_seconds", 0.0)),
                    text=candidate_transcript,
                    segments=[],
                )
        elif isinstance(transcript, Transcript):
            resolved_transcript = transcript

        # If transcript not resolved yet, check metadata dictionary
        if resolved_transcript is None and "transcript" in resolved_metadata:
            candidate_transcript = resolved_metadata["transcript"]
            if isinstance(candidate_transcript, Transcript):
                resolved_transcript = candidate_transcript
            elif isinstance(candidate_transcript, dict):
                try:
                    resolved_transcript = Transcript.from_dict(candidate_transcript)
                except Exception:
                    resolved_transcript = None
            elif isinstance(candidate_transcript, str):
                resolved_transcript = Transcript(
                    video_id=resolved_metadata.get("video_id", "unknown"),
                    language=resolved_metadata.get("language", "en"),
                    duration_seconds=float(resolved_metadata.get("duration_seconds", 0.0)),
                    text=candidate_transcript,
                    segments=[],
                )

        if resolved_transcript is None:
            raise ValueError("Transcript is required for Gemini highlight discovery.")

        candidates = self.detect_candidates(
            transcript=resolved_transcript,
            min_duration=min_duration,
            max_duration=max_duration,
            heatmap=heatmap,
            metadata=resolved_metadata,
            **kwargs,
        )
        scored = [self.score_candidate(c, resolved_transcript, heatmap=heatmap, **kwargs) for c in candidates]
        return sorted(scored, key=lambda c: c.score, reverse=True)

    def _build_detection_prompt(
        self,
        transcript: Transcript,
        min_duration: float,
        max_duration: float,
        heatmap: Optional[HeatmapData] = None,
        metadata: Optional[Dict[str, Any]] = None,
        max_clips: int = 5,
    ) -> str:
        """Formats the structured prompt with metadata, retention telemetry, and transcript."""
        meta = metadata or {}
        video_id = getattr(transcript, "video_id", meta.get("video_id", "unknown"))
        video_title = meta.get("title", meta.get("video_title", "Untitled Video"))
        channel_title = meta.get("channel", meta.get("channel_title", "Unknown Channel"))
        total_duration = getattr(transcript, "duration_seconds", meta.get("duration_seconds", 0.0))

        # Retention context
        retention_lines = []
        if heatmap and heatmap.peaks:
            for idx, p in enumerate(heatmap.peaks[:6]):
                p_dur = p.end_time - p.start_time
                line = (
                    f"- Peak {idx+1}: [{p.start_time:.1f}s - {p.end_time:.1f}s] "
                    f"(Intensity {p.intensity:.0%}, Prominence {p.prominence:.2f}, "
                    f"Type: {p.classification}, Suggested: {p.suggested_clip_start:.1f}s-{p.suggested_clip_end:.1f}s)"
                )
                retention_lines.append(line)
        retention_context = "\n".join(retention_lines) if retention_lines else "No audience replay heatmap available."

        # Format transcript segments
        formatted_segments = []
        for s in transcript.segments:
            spk = f"{s.speaker_tag}: " if s.speaker_tag else ""
            formatted_segments.append(f"[{s.start:.2f}s - {s.end:.2f}s] {spk}{s.text}")
        formatted_transcript = "\n".join(formatted_segments) if formatted_segments else transcript.text

        return PROMPT_TEMPLATE.format(
            max_clips=max_clips,
            min_duration=min_duration,
            max_duration=max_duration,
            video_id=video_id,
            video_title=video_title,
            channel_title=channel_title,
            total_duration=total_duration,
            retention_context=retention_context,
            formatted_transcript=formatted_transcript,
        )

    def _execute_rest_request(self, prompt: str) -> str:
        """Executes HTTPS POST to Gemini REST API with retry backoff."""
        url = f"{self.api_base}/models/{self.model}:generateContent?key={self.api_key}"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "yt-clipping-intelligence/1.0 (Windows; Python 3.12)",
        }
        payload_data = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.2,
                "maxOutputTokens": 4096,
            },
        }
        payload_bytes = json.dumps(payload_data).encode("utf-8")

        for attempt in range(self.max_retries):
            try:
                req = urllib.request.Request(url, data=payload_bytes, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read().decode("utf-8")
            except urllib.error.HTTPError as err:
                if err.code in (401, 403):
                    logger.warning("Gemini API authentication failed (HTTP %d). Check GEMINI_API_KEY.", err.code)
                    raise
                if err.code in (429, 500, 502, 503, 504) and attempt < self.max_retries - 1:
                    backoff = 0.5 * (2 ** attempt)
                    logger.warning("Gemini API transient HTTP error %d (attempt %d). Retrying in %.1fs.", err.code, attempt + 1, backoff)
                    time.sleep(backoff)
                    continue
                raise
            except (urllib.error.URLError, socket.timeout, TimeoutError) as err:
                if attempt < self.max_retries - 1:
                    backoff = 0.5 * (2 ** attempt)
                    logger.warning("Gemini API network timeout/error: %s (attempt %d). Retrying in %.1fs.", err, attempt + 1, backoff)
                    time.sleep(backoff)
                    continue
                raise

        raise RuntimeError("Gemini API request failed across all retries.")

    def _call_gemini_detection(
        self,
        transcript: Transcript,
        min_duration: float,
        max_duration: float,
        heatmap: Optional[HeatmapData] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[HighlightCandidate]:
        """Constructs prompt, sends HTTPS request, and parses response."""
        prompt = self._build_detection_prompt(
            transcript=transcript,
            min_duration=min_duration,
            max_duration=max_duration,
            heatmap=heatmap,
            metadata=metadata,
        )
        response_json = self._execute_rest_request(prompt)
        return self._parse_gemini_response(response_json, transcript, min_duration, max_duration)

    def _parse_gemini_response(
        self,
        response_json: str,
        transcript: Transcript,
        min_duration: float,
        max_duration: float,
    ) -> List[HighlightCandidate]:
        """Extracts JSON text, strips markdown code fences, validates bounds, and builds candidates."""
        data = json.loads(response_json)

        # Extract text from Gemini response structure: candidates[0].content.parts[0].text
        raw_text = ""
        if "candidates" in data and len(data["candidates"]) > 0:
            c0 = data["candidates"][0]
            content = c0.get("content", {})
            parts = content.get("parts", [])
            if parts and "text" in parts[0]:
                raw_text = parts[0]["text"]
        elif "highlights" in data or isinstance(data, list):
            # Direct json structure (if returned directly or mocked)
            raw_text = response_json

        if not raw_text:
            raise ValueError("No text parts returned from Gemini response.")

        # Strip markdown fences if present (case-insensitive)
        text = raw_text.strip()
        fence_match = FENCE_REGEX.search(text)
        if fence_match:
            text = fence_match.group(1).strip()

        parsed_data = json.loads(text)
        items = (
            parsed_data.get("highlights", [])
            if isinstance(parsed_data, dict)
            else (parsed_data if isinstance(parsed_data, list) else [])
        )

        total_duration = getattr(transcript, "duration_seconds", 0.0)
        candidates: List[HighlightCandidate] = []

        for item in items:
            try:
                if not isinstance(item, dict):
                    continue

                start = float(item.get("start_seconds", item.get("start", 0.0)))
                end = float(item.get("end_seconds", item.get("end", 0.0)))

                # 1. Skip NaN / Inf values immediately
                if (
                    math.isnan(start)
                    or math.isnan(end)
                    or math.isinf(start)
                    or math.isinf(end)
                ):
                    continue

                # 2. Strict non-negativity and temporal order
                if start < 0.0 or end <= start:
                    continue

                # 3. Clamp end to total_duration if total_duration > 0.0
                if total_duration > 0.0:
                    if start >= total_duration:
                        continue
                    end = min(end, total_duration)

                dur = round(end - start, 2)

                # 4. Validate duration finiteness and bounds
                if math.isnan(dur) or math.isinf(dur) or dur <= 0.0 or end <= start:
                    continue
                if dur < (min_duration - 1.0) or dur > (max_duration + 1.0):
                    continue

                # 5. Clamping helper for scores: ensure range [min_val, max_val]
                def _clamp_score(val: Any, default: float, min_val: float = 0.0, max_val: float = 10.0) -> float:
                    try:
                        f = float(val) if val is not None else default
                        if math.isnan(f) or math.isinf(f):
                            return default
                        return max(min_val, min(max_val, f))
                    except (ValueError, TypeError):
                        return default

                hook_score = _clamp_score(item.get("hook_score"), 7.0)
                moment_score = _clamp_score(item.get("moment_score"), 7.0)
                coherence_score = _clamp_score(item.get("coherence_score"), 7.0)
                pacing_score = _clamp_score(item.get("pacing_score"), 7.0)
                heatmap_score = _clamp_score(item.get("heatmap_score"), 0.0)
                confidence = _clamp_score(item.get("confidence"), 0.85, min_val=0.0, max_val=1.0)
                rationale = str(item.get("rationale", "Gemini multimodal highlight"))

                breakdown = ScoreBreakdown(
                    hook_score=hook_score,
                    moment_score=moment_score,
                    coherence_score=coherence_score,
                    pacing_score=pacing_score,
                    heatmap_score=heatmap_score,
                    confidence=confidence,
                    rationale=rationale,
                )
                composite_score = max(0.0, min(100.0, breakdown.compute_composite_score()))

                cid = f"hl_gemini_{uuid.uuid4().hex[:8]}"
                hook_title = item.get("hook_title", f"Highlight {start:.1f}s-{end:.1f}s")
                suggested_description = item.get("suggested_description", "")
                transcript_text = item.get("transcript_text", "")

                candidates.append(
                    HighlightCandidate(
                        candidate_id=cid,
                        video_id=transcript.video_id,
                        start_seconds=round(start, 2),
                        end_seconds=round(end, 2),
                        duration_seconds=dur,
                        score=composite_score,
                        breakdown=breakdown,
                        hook_title=hook_title,
                        suggested_description=suggested_description,
                        rationale=rationale,
                        transcript_text=transcript_text,
                    )
                )
            except Exception as e:
                logger.debug("Skipping invalid candidate entry: %s", e)
                continue

        return candidates


def get_highlight_detector(
    config: Optional[Any] = None,
    engine: Optional[str] = None,
    **kwargs: Any,
) -> HighlightDetector:
    """
    Factory creating a HighlightDetector.

    Args:
        config: Optional AppConfig instance or dict.
        engine: 'gemini' | 'heuristic' | None (auto-select).
        **kwargs: Additional overrides passed to detector constructor.

    Returns:
        Instance conforming to HighlightDetector ABC.
    """
    selected_engine = engine
    if selected_engine is None:
        if config is not None:
            if isinstance(config, dict):
                selected_engine = config.get("highlight_engine")
            else:
                selected_engine = getattr(config, "highlight_engine", None)
        if selected_engine is None:
            selected_engine = os.getenv("HIGHLIGHT_ENGINE")

    if selected_engine is not None:
        if isinstance(selected_engine, str):
            selected_engine = selected_engine.lower().strip()
            if not selected_engine:
                selected_engine = None
        else:
            logger.warning(
                "Non-string highlight_engine configuration %r provided to get_highlight_detector; ignoring and using auto-selection.",
                selected_engine,
            )
            selected_engine = None

    if selected_engine in ("heuristic", "local", "offline"):
        return ContextAwareSegmenter(**kwargs)

    if selected_engine == "gemini":
        return GeminiHighlightDiscoveryProvider(config=config, **kwargs)

    if selected_engine is not None and selected_engine != "auto":
        raise ValueError(f"Unsupported highlight detector engine: '{selected_engine}'. Expected 'gemini' or 'heuristic'.")

    # Auto selection: check if API key exists and not offline
    key = (
        (getattr(config, "gemini_api_key", None) if config else None)
        or (getattr(config, "llm_api_key", None) if config else None)
        or (config.get("gemini_api_key") if isinstance(config, dict) else None)
        or (config.get("llm_api_key") if isinstance(config, dict) else None)
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
    )
    offline = (
        (getattr(config, "offline_mode", False) if config else False)
        or (config.get("offline_mode", False) if isinstance(config, dict) else False)
        or os.getenv("GEMINI_OFFLINE_MODE", "").lower() in ("true", "1", "yes")
        or os.getenv("OFFLINE_MODE", "").lower() in ("true", "1", "yes")
    )

    if key and not offline:
        return GeminiHighlightDiscoveryProvider(config=config, **kwargs)

    return ContextAwareSegmenter(**kwargs)


def get_highlight_scorer(
    config: Optional[Any] = None,
    engine: Optional[str] = None,
    **kwargs: Any,
) -> HighlightScorer:
    """
    Factory creating a HighlightScorer.

    Args:
        config: Optional AppConfig instance or dict.
        engine: 'gemini' | 'heuristic' | None (auto-select).
        **kwargs: Additional overrides passed to scorer constructor.

    Returns:
        Instance conforming to HighlightScorer ABC.
    """
    selected_engine = engine
    if selected_engine is None:
        if config is not None:
            if isinstance(config, dict):
                selected_engine = config.get("highlight_engine")
            else:
                selected_engine = getattr(config, "highlight_engine", None)
        if selected_engine is None:
            selected_engine = os.getenv("HIGHLIGHT_ENGINE")

    if selected_engine is not None:
        if isinstance(selected_engine, str):
            selected_engine = selected_engine.lower().strip()
            if not selected_engine:
                selected_engine = None
        else:
            logger.warning(
                "Non-string highlight_engine configuration %r provided to get_highlight_scorer; ignoring and using auto-selection.",
                selected_engine,
            )
            selected_engine = None

    if selected_engine in ("heuristic", "local", "offline"):
        return ExplainableScorecardScorer(**kwargs)

    if selected_engine == "gemini":
        return GeminiHighlightDiscoveryProvider(config=config, **kwargs)

    if selected_engine is not None and selected_engine != "auto":
        raise ValueError(f"Unsupported highlight scorer engine: '{selected_engine}'. Expected 'gemini' or 'heuristic'.")

    # Auto selection
    key = (
        (getattr(config, "gemini_api_key", None) if config else None)
        or (getattr(config, "llm_api_key", None) if config else None)
        or (config.get("gemini_api_key") if isinstance(config, dict) else None)
        or (config.get("llm_api_key") if isinstance(config, dict) else None)
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
    )
    offline = (
        (getattr(config, "offline_mode", False) if config else False)
        or (config.get("offline_mode", False) if isinstance(config, dict) else False)
        or os.getenv("GEMINI_OFFLINE_MODE", "").lower() in ("true", "1", "yes")
        or os.getenv("OFFLINE_MODE", "").lower() in ("true", "1", "yes")
    )

    if key and not offline:
        return GeminiHighlightDiscoveryProvider(config=config, **kwargs)

    return ExplainableScorecardScorer(**kwargs)
