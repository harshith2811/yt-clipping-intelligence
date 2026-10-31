"""
AI Metadata and Hook Generator for Vertical Video Highlights.
Produces alternative opening hooks (question, bold claim, curiosity gap),
concise captions, hashtags, and title suggestions from highlight transcript context.
Supports local LLM (Ollama / OpenAI-compatible API) with resilient heuristic fallback.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
import json
import re
import urllib.request
import urllib.error

from ..contracts.models import HighlightCandidate, Transcript


@dataclass
class ClipMetadata:
    title: str
    hooks: List[str]  # 3 distinct hooks: [question_hook, bold_statement, curiosity_gap]
    caption: str
    description: str
    hashtags: List[str]
    model_used: str = "heuristic_fallback"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ClipMetadata":
        return cls(**data)


class MetadataGenerator:
    """
    Generates compelling short-form metadata and hook alternatives.
    """

    def __init__(
        self,
        llm_api_base: Optional[str] = None,
        llm_api_key: Optional[str] = None,
        model: str = "llama3",
        timeout: int = 5,
    ):
        self.llm_api_base = (llm_api_base or "").rstrip("/")
        self.llm_api_key = llm_api_key
        self.model = model
        self.timeout = timeout

    def generate_metadata(
        self,
        candidate: HighlightCandidate,
        transcript: Optional[Transcript] = None,
    ) -> ClipMetadata:
        """
        Generates full metadata for a candidate highlight.
        Tries local/remote LLM first, falling back smoothly to rule-based synthesis.
        """
        clip_text = candidate.transcript_text or ""
        if not clip_text and transcript:
            # Extract text within candidate bounds
            matching_segments = [
                s.text for s in transcript.segments
                if s.end >= candidate.start_seconds and s.start <= candidate.end_seconds
            ]
            clip_text = " ".join(matching_segments)

        # 1. Try LLM generation if configured
        if self.llm_api_base:
            try:
                llm_meta = self._call_llm(candidate, clip_text)
                if llm_meta:
                    return llm_meta
            except Exception:
                pass

        # 2. Rule-based heuristic generation (zero-dependency, always deterministic)
        return self._generate_heuristic(candidate, clip_text)

    def _call_llm(self, candidate: HighlightCandidate, clip_text: str) -> Optional[ClipMetadata]:
        prompt = (
            f"You are a short-form video editor for TikTok, YouTube Shorts, and Reels.\n"
            f"Transcript snippet:\n\"{clip_text[:1000]}\"\n\n"
            f"Generate a JSON object with:\n"
            f"- 'title': punchy 5-8 word title\n"
            f"- 'hooks': list of 3 strings: [question hook, bold claim hook, curiosity gap hook]\n"
            f"- 'caption': short engaging caption under 150 characters\n"
            f"- 'description': 2-3 sentence overview\n"
            f"- 'hashtags': list of 4-6 hashtags (without #)\n"
            f"Respond ONLY with valid JSON."
        )

        headers = {"Content-Type": "application/json"}
        if self.llm_api_key:
            headers["Authorization"] = f"Bearer {self.llm_api_key}"

        # Support Ollama /api/generate or OpenAI /v1/chat/completions
        if "/v1" in self.llm_api_base or "openai" in self.llm_api_base:
            endpoint = f"{self.llm_api_base}/chat/completions"
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
            }
        else:
            endpoint = f"{self.llm_api_base}/api/generate"
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            }

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        raw_content = ""
        if "choices" in data and len(data["choices"]) > 0:
            raw_content = data["choices"][0]["message"]["content"]
        elif "response" in data:
            raw_content = data["response"]

        if raw_content:
            json_match = re.search(r"\{.*\}", raw_content, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group(0))
                return ClipMetadata(
                    title=parsed.get("title", candidate.hook_title),
                    hooks=parsed.get("hooks", [candidate.hook_title]),
                    caption=parsed.get("caption", candidate.hook_title)[:150],
                    description=parsed.get("description", ""),
                    hashtags=[f"#{tag.lstrip('#')}" for tag in parsed.get("hashtags", ["shorts", "viral"])],
                    model_used=self.model,
                )
        return None

    def _generate_heuristic(self, candidate: HighlightCandidate, clip_text: str) -> ClipMetadata:
        """
        Deterministic, natural heuristic fallback based on candidate text.
        """
        words = [w.strip() for w in clip_text.split() if w.strip()]
        first_few = " ".join(words[:6]) if words else "This Moment"

        # 3 Alternative Hook Types
        hook_question = f"Did you know {first_few.lower()}?"
        hook_bold = f"Why {first_few} changes everything."
        hook_curiosity = f"Nobody expects what happens when {first_few.lower()}..."

        # Title
        base_title = candidate.hook_title or f"Key Highlight: {first_few}"
        title = base_title.title()

        # Caption
        caption = f"{title}. Watch till the end for the full breakdown! #Shorts"
        if len(caption) > 150:
            caption = caption[:147] + "..."

        # Description
        description = (
            f"Highlight from {candidate.video_id}: {clip_text[:200]}... "
            f"Curated automatically with high retention scoring."
        )

        # Topic hashtags from text
        hashtags = ["#shorts", "#viral", "#highlight", "#trending", "#fyp"]
        if "ai" in clip_text.lower() or "model" in clip_text.lower():
            hashtags.append("#ai")
        if "code" in clip_text.lower() or "python" in clip_text.lower():
            hashtags.append("#coding")
        if "money" in clip_text.lower() or "business" in clip_text.lower():
            hashtags.append("#business")

        return ClipMetadata(
            title=title,
            hooks=[hook_question, hook_bold, hook_curiosity],
            caption=caption,
            description=description,
            hashtags=hashtags[:6],
            model_used="heuristic_rule_engine",
        )
