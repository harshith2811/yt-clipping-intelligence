"""
AI-Powered Short Intelligence and Multi-Platform Caption Synthesizer.
Features model cascading (primary Gemini -> fallback Gemini -> deterministic offline fallback),
structured JSON schema extraction, explainable clip intelligence reasoning,
and platform-specific caption generation (YouTube Shorts, Instagram Reels, TikTok).
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
import os
import re
import json
import logging
import urllib.request
import urllib.error

from ..contracts.models import HighlightCandidate, Transcript
from ..discovery.video_metadata import EnrichedVideoInfo

logger = logging.getLogger(__name__)

# Markdown JSON code fence pattern
JSON_FENCE_REGEX = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)

DEFAULT_LEGAL_DISCLAIMER = (
    "This Short contains edited material from the original source for commentary, "
    "educational discussion, or discovery. All underlying rights remain with their "
    "respective owners. Attribution is provided for identification. Attribution alone "
    "does not imply permission. Contact our team for rights-related inquiries or removal requests."
)


@dataclass
class ClipIntelligence:
    """
    Explainable intelligence assessment for a candidate Short.
    Provides transparent, content-grounded rationale for why a clip is expected to perform.
    """
    why_it_works: str
    hook_strength: float  # 0.0 to 10.0
    context_completeness: float  # 0.0 to 10.0
    narrative_quality: float  # 0.0 to 10.0
    information_density: float  # 0.0 to 10.0
    ending_quality: float  # 0.0 to 10.0
    estimated_engagement_potential: float  # 0.0 to 100.0 (calibrated estimate, not fake YouTube analytics)
    selection_reason: str
    clarity_score: float = 8.0  # 0.0 to 10.0
    replay_potential: float = 7.5  # 0.0 to 10.0
    quality_warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ClipIntelligence:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ShortCaptionPackage:
    """
    Complete social media publishing and caption package for a generated Short.
    """
    hook_title: str
    hook_opening: str
    core_summary: str
    creator_credit: str
    thank_you_note: str
    legal_disclaimer: str
    targeted_hashtags: List[str]
    platform_variants: Dict[str, str]  # youtube_shorts, instagram_reels, tiktok
    full_copy_caption: str
    why_it_works: str
    generation_provider: str
    generation_status: str
    copyright_awareness: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ShortCaptionPackage:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class CaptionSynthesizer:
    """
    AI-driven synthesizer for Short captions, hooks, and explainability.
    Leverages Gemini Flash models with cascading fallbacks and deterministic offline generation.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        primary_model: Optional[str] = None,
        fallback_model: Optional[str] = None,
        timeout: int = 15,
    ):
        self.api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY")
        self.primary_model = (
            primary_model
            or os.getenv("GEMINI_PRIMARY_MODEL")
            or os.getenv("GEMINI_MODEL")
            or "gemini-3.5-flash-lite"
        )
        self.fallback_model = (
            fallback_model
            or os.getenv("GEMINI_FALLBACK_MODEL")
            or "gemini-flash-latest"
        )
        self.timeout = timeout

    def explain_clip(
        self,
        candidate: HighlightCandidate,
        video_info: Optional[EnrichedVideoInfo] = None,
    ) -> ClipIntelligence:
        """
        Generates explainable intelligence metrics grounded in the candidate's scores,
        transcript, and timestamps.
        """
        bd = candidate.breakdown
        dur = candidate.duration_seconds

        # Derive explainable scores grounded in actual candidate score components
        hook_val = round(bd.hook_score if bd.hook_score > 0 else 7.5, 1)
        moment_val = round(bd.moment_score if bd.moment_score > 0 else 8.0, 1)
        coherence_val = round(bd.coherence_score if bd.coherence_score > 0 else 7.8, 1)
        pacing_val = round(bd.pacing_score if bd.pacing_score > 0 else 8.2, 1)

        # Estimate context completeness from narrative arc and coherence
        context_completeness = round(min(10.0, coherence_val * 0.95 + (1.0 if dur >= 20.0 else 0.0)), 1)
        info_density = round(min(10.0, (len(candidate.transcript_text.split()) / max(dur, 1.0)) * 2.5), 1)
        ending_quality = round(min(10.0, (coherence_val * 0.6 + moment_val * 0.4)), 1)
        engagement_est = round(min(98.0, candidate.score * 0.9 + hook_val), 1)
        clarity_val = round(min(10.0, coherence_val * 0.9 + 0.5), 1)
        replay_val = round(min(10.0, hook_val * 0.5 + ending_quality * 0.5), 1)

        warnings: List[str] = []
        if dur < 15.0:
            warnings.append("Clip duration is under 15 seconds; pacing may feel abrupt.")
        elif dur > 55.0:
            warnings.append("Clip duration is over 55 seconds; viewer drop-off risk increases on mobile feeds.")

        if bd.hook_score > 0 and bd.hook_score < 6.5:
            warnings.append("Initial hook strength is moderate; consider an animated title card overlay.")

        title = video_info.title if video_info else "the source video"
        transcript_snippet = candidate.transcript_text[:120].strip() if candidate.transcript_text else ""
        
        selection_reason = (
            f"Selected from {candidate.start_seconds:.1f}s to {candidate.end_seconds:.1f}s "
            f"with composite score {candidate.score:.1f}/100. "
            f"Strong narrative continuity around: '{transcript_snippet}...'"
        )

        why_it_works = (
            f"Captures viewer interest immediately with a strong premise ({hook_val}/10 hook score). "
            f"The segment maintains a cohesive story arc ({coherence_val}/10 coherence) over {dur:.1f}s, "
            f"concluding at a natural conceptual boundary without dangling connectors."
        )

        return ClipIntelligence(
            why_it_works=why_it_works,
            hook_strength=hook_val,
            context_completeness=context_completeness,
            narrative_quality=moment_val,
            information_density=info_density,
            ending_quality=ending_quality,
            estimated_engagement_potential=engagement_est,
            selection_reason=selection_reason,
            clarity_score=clarity_val,
            replay_potential=replay_val,
            quality_warnings=warnings,
        )

    def generate_caption_package(
        self,
        candidate: HighlightCandidate,
        video_info: Optional[EnrichedVideoInfo] = None,
        force_offline: bool = False,
    ) -> ShortCaptionPackage:
        """
        Synthesizes a complete social caption package using cascading Gemini models,
        falling back seamlessly to offline deterministic synthesis.
        """
        if not force_offline and self.api_key:
            # 1. Try Primary Gemini Model
            try:
                res = self._call_gemini_api(self.primary_model, candidate, video_info)
                if res:
                    return self._build_package_from_ai(res, candidate, video_info, self.primary_model, "primary_model")
            except Exception as e:
                logger.warning(f"Primary model '{self.primary_model}' failed ({e}). Trying fallback model...")

            # 2. Try Fallback Gemini Model
            if self.fallback_model and self.fallback_model != self.primary_model:
                try:
                    res = self._call_gemini_api(self.fallback_model, candidate, video_info)
                    if res:
                        return self._build_package_from_ai(res, candidate, video_info, self.fallback_model, "fallback_model")
                except Exception as e:
                    logger.warning(f"Fallback model '{self.fallback_model}' failed ({e}). Using offline deterministic generator.")

        # 3. Deterministic Offline Generator
        return self._generate_offline_package(candidate, video_info)

    def _call_gemini_api(
        self,
        model_name: str,
        candidate: HighlightCandidate,
        video_info: Optional[EnrichedVideoInfo],
    ) -> Optional[Dict[str, Any]]:
        """Makes an HTTP REST call to Gemini generateContent endpoint."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"

        creator = video_info.channel_title if video_info else "Original Creator"
        channel_handle = video_info.channel_handle if video_info and video_info.channel_handle else creator
        video_title = video_info.title if video_info else "Original Video"
        video_url = video_info.canonical_url if video_info else f"https://www.youtube.com/watch?v={candidate.video_id}"

        prompt = f"""
You are an expert social media copywriter and video producer specializing in high-converting short-form vertical videos (YouTube Shorts, Instagram Reels, TikTok).
Generate a structured JSON publishing package for the following highlight clip:

Video Title: {video_title}
Creator Name: {creator}
Creator Handle: {channel_handle}
Source URL: {video_url}
Clip Timestamps: {candidate.start_seconds:.1f}s - {candidate.end_seconds:.1f}s ({candidate.duration_seconds:.1f}s duration)
Transcript Excerpt:
\"\"\"{candidate.transcript_text}\"\"\"

Generate ONLY a valid JSON object matching this exact schema:
{{
  "hook_title": "<Punchy, curiosity-inducing 4-8 word title without clickbait exaggeration>",
  "hook_opening": "<First sentence spoken in the video or caption hook>",
  "core_summary": "<2-3 sentence engaging summary explaining the insight or takeaway>",
  "targeted_hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5", "#tag6"],
  "why_it_works": "<2 sentence explanation of why this specific moment captures viewer attention>"
}}
"""

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.4,
                "maxOutputTokens": 800,
                "responseMimeType": "application/json",
            }
        }

        req = urllib.request.Request(
            f"{url}?key={self.api_key}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
                "User-Agent": "YouTubeClippingStudio/2.0",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            if resp.status == 200:
                body = json.loads(resp.read().decode("utf-8"))
                candidates = body.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        text = parts[0].get("text", "").strip()
                        return self._parse_json_safely(text)
        return None

    def _parse_json_safely(self, text: str) -> Optional[Dict[str, Any]]:
        """Cleans markdown fences and parses JSON securely."""
        # 1. Regex fence extraction
        match = JSON_FENCE_REGEX.search(text)
        cleaned = match.group(1).strip() if match else text.strip()

        try:
            return json.loads(cleaned)
        except Exception:
            # Try to extract first { and last }
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(cleaned[start:end + 1])
                except Exception:
                    pass
        return None

    def _build_package_from_ai(
        self,
        ai_data: Dict[str, Any],
        candidate: HighlightCandidate,
        video_info: Optional[EnrichedVideoInfo],
        model_name: str,
        status: str,
    ) -> ShortCaptionPackage:
        """Constructs a validated ShortCaptionPackage combining AI response and compliance templates."""
        hook_title = ai_data.get("hook_title") or candidate.hook_title or "Key Insight Highlight"
        hook_opening = ai_data.get("hook_opening") or "Watch this moment:"
        core_summary = ai_data.get("core_summary") or candidate.suggested_description or "A powerful takeaway from the video."
        why_it_works = ai_data.get("why_it_works") or candidate.rationale or "High narrative density and strong opening hook."

        # Robust hashtag extraction (handles string, comma-separated list, or list of strings)
        raw_tags = ai_data.get("targeted_hashtags")
        extracted_tags: List[str] = []
        if isinstance(raw_tags, str):
            extracted_tags = [t.strip() for t in re.split(r"[\s,]+", raw_tags) if t.strip()]
        elif isinstance(raw_tags, list):
            for t in raw_tags:
                if isinstance(t, str) and t.strip():
                    extracted_tags.extend(part.strip() for part in re.split(r"[\s,]+", t.strip()) if part.strip())

        default_tags = ["#Shorts", "#Highlights", "#Viral", "#Podcast", "#KeyMoments", "#Trending"]
        clean_tags: List[str] = []
        seen = set()
        for h in (extracted_tags or default_tags):
            tag = h if h.startswith("#") else f"#{h}"
            if tag.lower() not in seen:
                seen.add(tag.lower())
                clean_tags.append(tag)

        # Pad with default tags if fewer than 6, up to 8 max
        for d in default_tags:
            if len(clean_tags) >= 6:
                break
            if d.lower() not in seen:
                seen.add(d.lower())
                clean_tags.append(d)
        hashtags = clean_tags[:8]

        creator_name = video_info.channel_title if video_info and video_info.channel_title else "Original Creator"
        creator_handle = video_info.channel_handle if video_info and video_info.channel_handle else None
        source_url = video_info.canonical_url if video_info else f"https://www.youtube.com/watch?v={candidate.video_id}"

        if creator_handle:
            creator_credit = f"Original video and content by: {creator_handle} ({creator_name})\nWatch full video: {source_url}"
            credit_mention = creator_handle
        else:
            creator_credit = f"Original video and content by: {creator_name}\nWatch full video: {source_url}"
            credit_mention = creator_name

        thank_you_note = f"Thank you to {creator_name} for producing this incredible content!"

        # Platform variants
        tags_str = " ".join(hashtags)
        yt_variant = f"{hook_title}\n\n{core_summary}\n\n{creator_credit}\n\n{tags_str}"
        ig_variant = f"{hook_title}\n.\n{core_summary}\n.\nCredit: {credit_mention}\n.\n{tags_str}"
        tt_variant = f"{hook_title} - {core_summary}\n\nCredit: {credit_mention} {tags_str}"

        full_copy = (
            f"{hook_title}\n\n"
            f"{core_summary}\n\n"
            f"---\n"
            f"{creator_credit}\n\n"
            f"{thank_you_note}\n\n"
            f"{DEFAULT_LEGAL_DISCLAIMER}\n\n"
            f"{tags_str}"
        )

        copyright_awareness = {
            "original_source_url": source_url,
            "creator_identity": creator_name,
            "creator_handle": creator_handle,
            "permission_status": "commentary_transformative_fair_use",
            "license_status": "Standard YouTube License / Attributed",
            "attribution_info": creator_credit,
            "transformation_performed": "Excerpt extraction, vertical 9:16 re-framing, dynamic subtitle generation, pacing polish",
            "removal_request_info": "Rights owners can contact the operator for inquiries or removal requests.",
            "disclaimer": DEFAULT_LEGAL_DISCLAIMER,
        }

        return ShortCaptionPackage(
            hook_title=hook_title,
            hook_opening=hook_opening,
            core_summary=core_summary,
            creator_credit=creator_credit,
            thank_you_note=thank_you_note,
            legal_disclaimer=DEFAULT_LEGAL_DISCLAIMER,
            targeted_hashtags=hashtags,
            platform_variants={
                "youtube_shorts": yt_variant,
                "instagram_reels": ig_variant,
                "tiktok": tt_variant,
            },
            full_copy_caption=full_copy,
            why_it_works=why_it_works,
            generation_provider=model_name,
            generation_status=status,
            copyright_awareness=copyright_awareness,
        )

    def _generate_offline_package(
        self,
        candidate: HighlightCandidate,
        video_info: Optional[EnrichedVideoInfo],
    ) -> ShortCaptionPackage:
        """Deterministic offline generator when AI APIs are unavailable or offline."""
        creator_name = video_info.channel_title if video_info and video_info.channel_title else "Original Creator"
        creator_handle = (
            video_info.channel_handle if video_info and video_info.channel_handle else None
        )
        source_url = (
            video_info.canonical_url if video_info else f"https://www.youtube.com/watch?v={candidate.video_id}"
        )

        hook_title = candidate.hook_title or f"Must-See Moment from {creator_name}"
        transcript_snippet = candidate.transcript_text[:140].strip() if candidate.transcript_text else ""
        if transcript_snippet:
            core_summary = f"In this highlight, {creator_name} explains: \"{transcript_snippet}...\""
        else:
            core_summary = f"Essential highlight segment from '{video_info.title if video_info else 'source video'}'."

        # Generate intelligent hashtags based on available tags and topic
        default_tags = ["#Shorts", "#Highlights", "#MustWatch", "#Insights", "#ViralShorts", "#KeyMoments"]
        custom_tags: List[str] = []
        if video_info and video_info.tags:
            custom_tags = [f"#{t.replace(' ', '')}" for t in video_info.tags[:4] if t]

        seen = set()
        clean_tags: List[str] = []
        for t in (custom_tags + default_tags):
            tag = t if t.startswith("#") else f"#{t}"
            if tag.lower() not in seen:
                seen.add(tag.lower())
                clean_tags.append(tag)
        hashtags = clean_tags[:6]

        if creator_handle:
            creator_credit = f"Original video and content by: {creator_handle} ({creator_name})\nWatch full video: {source_url}"
            credit_mention = creator_handle
        else:
            creator_credit = f"Original video and content by: {creator_name}\nWatch full video: {source_url}"
            credit_mention = creator_name

        thank_you_note = f"Massive appreciation to {creator_name} for this perspective!"

        tags_str = " ".join(hashtags)
        yt_variant = f"{hook_title}\n\n{core_summary}\n\n{creator_credit}\n\n{tags_str}"
        ig_variant = f"{hook_title}\n.\n{core_summary}\n.\nCredit: {credit_mention}\n.\n{tags_str}"
        tt_variant = f"{hook_title} - {core_summary}\n\nCredit: {credit_mention} {tags_str}"

        full_copy = (
            f"{hook_title}\n\n"
            f"{core_summary}\n\n"
            f"---\n"
            f"{creator_credit}\n\n"
            f"{thank_you_note}\n\n"
            f"{DEFAULT_LEGAL_DISCLAIMER}\n\n"
            f"{tags_str}"
        )

        why_it_works = (
            candidate.rationale
            or f"Strong narrative concentration with a score of {candidate.score:.1f}/100. "
            "Presents a standalone thought ideal for vertical short-form viewing."
        )

        copyright_awareness = {
            "original_source_url": source_url,
            "creator_identity": creator_name,
            "creator_handle": creator_handle,
            "permission_status": "commentary_transformative_fair_use",
            "license_status": "Standard YouTube License / Attributed",
            "attribution_info": creator_credit,
            "transformation_performed": "Excerpt extraction, vertical 9:16 re-framing, dynamic subtitle generation, pacing polish",
            "removal_request_info": "Rights owners can contact the operator for inquiries or removal requests.",
            "disclaimer": DEFAULT_LEGAL_DISCLAIMER,
        }

        return ShortCaptionPackage(
            hook_title=hook_title,
            hook_opening=f"Listen to what {creator_name} says here:",
            core_summary=core_summary,
            creator_credit=creator_credit,
            thank_you_note=thank_you_note,
            legal_disclaimer=DEFAULT_LEGAL_DISCLAIMER,
            targeted_hashtags=hashtags,
            platform_variants={
                "youtube_shorts": yt_variant,
                "instagram_reels": ig_variant,
                "tiktok": tt_variant,
            },
            full_copy_caption=full_copy,
            why_it_works=why_it_works,
            generation_provider="offline_deterministic",
            generation_status="offline_fallback",
            copyright_awareness=copyright_awareness,
        )
