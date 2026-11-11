"""
Gemini Visual Creative Director for Strategic FLUX.1 Image Generation.
Acts as an AI creative director that analyzes video topic, subtitles, narrative arc,
and pacing to determine whether an AI-generated visual asset is genuinely justified
before generating anything, avoiding gratuitous visual interruptions and prioritizing
speaker continuity and existing stock footage reuse.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List, Set
import os
import re
import json
import logging
import urllib.request
import urllib.error
import socket
import time

from ..contracts.models import HighlightCandidate, Transcript, WordTimestamp
from ..rendering.flux_generator import FluxImageGenerator, FluxGenerationResult, STYLE_PRESETS

logger = logging.getLogger(__name__)

# Fencing regex for JSON block extraction
JSON_BLOCK_REGEX = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)

CREATIVE_DIRECTOR_PROMPT = """
You are an elite creative director and visual storytelling supervisor for short-form viral video (TikTok, YouTube Shorts, Reels).
Analyze this short-form video clip segment and determine if an AI-generated visual asset (FLUX.1 Schnell) is genuinely justified.

### GUIDELINES & PHILOSOPHY:
1. DO NOT generate images unnecessarily. The human speaker's authentic presence and eye contact are often the strongest retention driver.
2. ONLY justify an AI image if it illustrates an abstract concept, mental model, futuristic scenario, historical scene, or high-stakes metaphor that the speaker is describing and that CANNOT be conveyed by the speaker alone.
3. Keep visual interventions concise (2.0 to 3.5 seconds) and never cover the beginning or ending of a sentence or hook.
4. If the speaker is simply telling a personal story, making conversational jokes, or speaking directly to the audience, REJECT image generation.

### CLIP CONTEXT:
- Video Title: {video_title}
- Channel: {channel_title}
- Hook Title: {hook_title}
- Clip Duration: {clip_duration:.1f}s
- Monologue / Dialogue Excerpt:
"{transcript_text}"

### OUTPUT FORMAT:
Respond ONLY with a valid JSON object matching this schema:
{{
  "flux_justified": <true or false>,
  "rationale": "<1-2 sentences explaining why the image is or is not justified>",
  "concept": "<3-5 word concept name, e.g. Quantum Computing Grid, Futuristic Cybernetic City>",
  "target_start_offset": <float seconds from clip start where overlay should begin, e.g. 1.5>,
  "target_duration": <float seconds, between 2.0 and 3.5>,
  "flux_prompt": "<detailed photorealistic 9:16 vertical prompt specifically for FLUX.1. Describe lighting, focal subject, depth of field, texture. No text/logos in prompt>",
  "style_preset": "<one of: cinematic_hook, tech_minimal, documentary, neon_cyber>",
  "motion": "<one of: zoom_in, zoom_out, pan>"
}}
"""


@dataclass
class VisualInterventionDecision:
    """Provenance and telemetry of a creative visual intervention decision."""
    needed: bool
    rationale: str
    concept: str = ""
    target_start_seconds: float = 0.0
    target_duration_seconds: float = 0.0
    flux_prompt: str = ""
    style_preset: str = "cinematic_hook"
    motion: str = "zoom_in"
    asset_path: Optional[str] = None
    broll_video_path: Optional[str] = None
    is_generated: bool = False
    provider: str = "heuristic"
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GeminiVisualDirector:
    """
    Evaluates highlight candidates with creative intelligence to determine
    if, when, and how FLUX.1 image generation should be strategically utilized.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        api_base: Optional[str] = None,
        flux_generator: Optional[FluxImageGenerator] = None,
        offline_mode: bool = False,
    ):
        self.api_key = str(
            api_key
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or ""
        ).strip()
        self.model = str(model or os.getenv("GEMINI_MODEL") or "gemini-1.5-flash").strip()
        self.api_base = str(
            api_base or os.getenv("GEMINI_API_BASE") or "https://generativelanguage.googleapis.com/v1beta"
        ).rstrip("/")
        self.offline_mode = offline_mode or (os.getenv("GEMINI_OFFLINE_MODE", "").lower() in ("1", "true", "yes"))
        self.flux_generator = flux_generator or FluxImageGenerator()

    @property
    def is_cloud_available(self) -> bool:
        return bool(self.api_key) and not self.offline_mode

    def evaluate_candidate(
        self,
        candidate: HighlightCandidate,
        transcript: Transcript,
        video_metadata: Optional[Dict[str, Any]] = None,
        available_assets_dir: Optional[str] = None,
    ) -> VisualInterventionDecision:
        """
        Analyzes a candidate clip to decide whether visual intervention via FLUX is justified.
        """
        start_t = time.perf_counter()
        meta = video_metadata or {}
        clip_dur = candidate.duration_seconds

        # Guard 1: Too short for visual intervention without annoying the viewer
        if clip_dur < 6.0:
            return VisualInterventionDecision(
                needed=False,
                rationale="Clip duration is under 6 seconds; maintaining primary footage focus for high pacing.",
                provider="duration_guard",
                latency_ms=round((time.perf_counter() - start_t) * 1000, 2),
            )

        # Extract transcript text for this candidate
        cand_text = self._extract_candidate_text(candidate, transcript)

        # Guard 2: Evaluate if existing local stock assets already satisfy the visual requirement
        if available_assets_dir and os.path.exists(available_assets_dir):
            matched_stock = self._check_existing_stock(cand_text, available_assets_dir)
            if matched_stock:
                return VisualInterventionDecision(
                    needed=False,
                    rationale=f"Found existing high-relevance stock asset ({os.path.basename(matched_stock)}). Reusing asset without unnecessary AI generation.",
                    concept="Stock Footage Reuse",
                    asset_path=matched_stock,
                    provider="stock_reuse_gate",
                    latency_ms=round((time.perf_counter() - start_t) * 1000, 2),
                )

        # Path A: Gemini Creative Intelligence (Cloud)
        if self.is_cloud_available:
            try:
                decision = self._call_gemini_director(
                    candidate=candidate,
                    transcript_text=cand_text,
                    video_metadata=meta,
                )
                decision.latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
                return decision
            except Exception as e:
                logger.warning(f"Gemini Visual Director query failed ({e}). Falling back to heuristic director.")

        # Path B: Deterministic Heuristic Creative Evaluation
        decision = self._heuristic_evaluation(candidate, cand_text, meta)
        decision.latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
        return decision

    def execute_intervention(
        self,
        decision: VisualInterventionDecision,
        output_dir: Optional[str] = None,
    ) -> VisualInterventionDecision:
        """
        If decision.needed is True, invokes FLUX generator to produce the image
        and renders a smooth 9:16 Ken Burns MP4 clip.
        """
        if not decision.needed or not decision.flux_prompt:
            return decision

        try:
            # 1. Generate 9:16 vertical image
            gen_res = self.flux_generator.generate_image(
                prompt=decision.flux_prompt,
                style_preset=decision.style_preset,
                width=768,
                height=1344,
            )

            if gen_res.success and os.path.exists(gen_res.file_path):
                decision.asset_path = gen_res.file_path
                decision.is_generated = True

                # 2. Render smooth Ken Burns 9:16 B-roll MP4
                broll_dur = max(2.0, min(decision.target_duration_seconds or 3.0, 4.0))
                broll_mp4 = self.flux_generator.create_broll_clip(
                    image_path=gen_res.file_path,
                    duration=broll_dur,
                    motion=decision.motion or "zoom_in",
                )
                if broll_mp4 and os.path.exists(broll_mp4):
                    decision.broll_video_path = broll_mp4
                    logger.info(f"Visual Creative Director successfully synthesized B-roll: {broll_mp4}")
            else:
                decision.needed = False
                decision.rationale = f"Generation failed: {gen_res.error or 'Image could not be produced'}"
        except Exception as e:
            logger.warning(f"Failed to execute FLUX visual intervention: {e}")
            decision.needed = False
            decision.rationale = f"Generation failed: {e}"

        return decision

    def _call_gemini_director(
        self,
        candidate: HighlightCandidate,
        transcript_text: str,
        video_metadata: Dict[str, Any],
    ) -> VisualInterventionDecision:
        """Invokes Gemini 1.5 Flash via REST API with structured creative director prompt."""
        prompt = CREATIVE_DIRECTOR_PROMPT.format(
            video_title=video_metadata.get("title", "YouTube Video"),
            channel_title=video_metadata.get("channel", "Creator"),
            hook_title=candidate.hook_title or "Key Highlight",
            clip_duration=candidate.duration_seconds,
            transcript_text=transcript_text[:1200],
        )

        url = f"{self.api_base}/models/{self.model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.2,
                "maxOutputTokens": 1024,
            },
        }

        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        raw_text = ""
        if "candidates" in data and len(data["candidates"]) > 0:
            c0 = data["candidates"][0]
            parts = c0.get("content", {}).get("parts", [])
            if parts and "text" in parts[0]:
                raw_text = parts[0]["text"]

        fence_m = JSON_BLOCK_REGEX.search(raw_text)
        if fence_m:
            raw_text = fence_m.group(1).strip()

        parsed = json.loads(raw_text)
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            parsed = parsed[0]
        elif not isinstance(parsed, dict):
            parsed = {}

        flux_justified = bool(parsed.get("flux_justified", False))
        rationale = str(parsed.get("rationale", "Evaluated by Gemini Creative Director"))
        concept = str(parsed.get("concept", "Visual Hook"))
        start_off = float(parsed.get("target_start_offset", 1.5))
        duration = float(parsed.get("target_duration", 2.5))
        flux_prompt = str(parsed.get("flux_prompt", ""))
        style_preset = str(parsed.get("style_preset", "cinematic_hook"))
        motion = str(parsed.get("motion", "zoom_in"))

        if style_preset not in STYLE_PRESETS:
            style_preset = "cinematic_hook"

        # Bound timings
        start_off = max(0.5, min(start_off, candidate.duration_seconds - 2.5))
        duration = max(1.5, min(duration, 4.0))

        return VisualInterventionDecision(
            needed=flux_justified,
            rationale=rationale,
            concept=concept,
            target_start_seconds=round(start_off, 2),
            target_duration_seconds=round(duration, 2),
            flux_prompt=flux_prompt,
            style_preset=style_preset,
            motion=motion,
            provider="gemini_creative_director",
        )

    def _heuristic_evaluation(
        self,
        candidate: HighlightCandidate,
        transcript_text: str,
        video_metadata: Dict[str, Any],
    ) -> VisualInterventionDecision:
        """
        Deterministic, offline heuristic assessment of visual intervention need.
        Identifies high-impact abstract, technological, or metaphorical narrative clusters.
        """
        text_lower = (transcript_text + " " + (candidate.hook_title or "")).lower()

        # Topic domain clusters that strongly benefit from visual reinforcement
        clusters = {
            "tech_minimal": [
                ("ai", "artificial intelligence", "algorithm", "neural network"),
                "High-tech neural computing interface with glowing cyan data circuits and quantum light pulses",
            ],
            "neon_cyber": [
                ("cyber", "future", "matrix", "code", "virtual reality", "crypto", "blockchain"),
                "Futuristic cybernetic city grid bathed in deep violet and neon cyan reflections",
            ],
            "documentary": [
                ("history", "ancient", "century", "earth", "evolution", "space", "universe", "planet"),
                "Authentic 35mm documentary visual capturing astronomical and historical depth in dramatic natural lighting",
            ],
            "cinematic_hook": [
                ("billion", "money", "power", "secret", "breakthrough", "revolution", "danger", "shocking"),
                "Dramatic cinematic portrait of monumental human ambition, high contrast chiaroscuro lighting, deep cinematic shadows",
            ],
        }

        matched_preset = None
        matched_concept = None
        matched_prompt = None

        for preset, (keywords, default_prompt) in clusters.items():
            for kw in keywords:
                if re.search(r"\b" + re.escape(kw) + r"\b", text_lower):
                    matched_preset = preset
                    matched_concept = f"{kw.capitalize()} Concept"
                    matched_prompt = f"{default_prompt}. Context: {candidate.hook_title or kw}"
                    break
            if matched_preset:
                break

        # Only justify if candidate has sustained monologue and a rich visual concept
        if matched_preset and candidate.duration_seconds >= 10.0:
            start_offset = max(1.0, round(candidate.duration_seconds * 0.25, 2))
            dur = min(3.0, round(candidate.duration_seconds * 0.35, 2))
            return VisualInterventionDecision(
                needed=True,
                rationale=f"Dialogue introduces abstract visual concept ('{matched_concept}'). Strategic FLUX card reinforces narrative comprehension.",
                concept=matched_concept,
                target_start_seconds=start_offset,
                target_duration_seconds=dur,
                flux_prompt=matched_prompt,
                style_preset=matched_preset,
                motion="zoom_in",
                provider="heuristic_topic_director",
            )

        return VisualInterventionDecision(
            needed=False,
            rationale="Dialogue is direct conversational engagement. Preserving raw speaker eye-contact and authenticity without visual disruption.",
            provider="heuristic_topic_director",
        )

    def _extract_candidate_text(self, candidate: HighlightCandidate, transcript: Transcript) -> str:
        """Gathers verbatim transcript text inside the candidate start/end window."""
        cand_words = []
        for s in transcript.segments:
            for w in s.words:
                if w.end > candidate.start_seconds and w.start < candidate.end_seconds:
                    cand_words.append(w.word)
        if cand_words:
            return " ".join(cand_words)
        return transcript.text[:400]

    def _check_existing_stock(self, text: str, assets_dir: str) -> Optional[str]:
        """Checks if local stock footage directory already contains clean matching clips."""
        from ..rendering.b_roll import EXTRA_STOP_WORDS
        from ..scoring.packaging_linter import GENERIC_STOP_WORDS

        stop_words = EXTRA_STOP_WORDS.union(GENERIC_STOP_WORDS).union({
            "and", "the", "for", "with", "this", "that", "you", "are", "not", "have",
            "welcome", "hello", "everyone", "today", "video", "guys", "please",
        })

        meaningful_words = {
            w for w in re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
            if w not in stop_words
        }
        if not meaningful_words:
            return None

        valid_exts = {".mp4", ".mov", ".mkv", ".webm"}

        for root, _, files in os.walk(assets_dir):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in valid_exts:
                    fname_tokens = set(re.findall(r"[a-z0-9]{3,}", os.path.splitext(f)[0].lower()))
                    if fname_tokens.intersection(meaningful_words):
                        return os.path.join(root, f)
        return None


VisualCreativeDirector = GeminiVisualDirector

__all__ = [
    "VisualInterventionDecision",
    "GeminiVisualDirector",
    "VisualCreativeDirector",
]
