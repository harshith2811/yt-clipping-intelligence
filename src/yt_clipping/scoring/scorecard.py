"""
Explainable Multi-Signal Highlight Scorer.
Implements the hook vs moment scorecard methodology adapted from ClipMint.
Evaluates opening hook strength, narrative payoff, pacing (WPM), coherence,
and produces human-auditable rationales.
"""

from typing import List, Optional, Any
import re
from ..contracts.models import HighlightCandidate, Transcript, ScoreBreakdown, HeatmapData
from ..contracts.interfaces import HighlightScorer
from ..detection.audio_energy import AudioEnergyAnalyzer, MotionEnergyAnalyzer, AdaptiveCadenceScorer


HOOK_KEYWORDS = {
    "secret", "never", "why", "how to", "most", "mistake", "truth", "revealed",
    "insane", "stop", "here is", "don't", "shocking", "game changer", "formula",
    "fail", "proven", "hack", "trick", "worst", "best", "warning", "look at",
    "they said", "turns out", "fun fact", "imagine",
}

PAYOFF_KEYWORDS = {
    "actually", "instead", "turns out", "that is why", "the reason is", "solution",
    "key takeaway", "result", "finally", "realized", "in fact", "ultimately", "remember",
    "changes everything", "blow your mind", "my take", "at the end of the day", "the bottom line",
    "makes a big difference", "worth it", "completely", "that's why", "that is how",
}

SPONSOR_KEYWORDS = {
    "sponsor", "sponsored", "use code", "link in description", "discount", "percent off",
    "patreon", "merch", "displate", "nordvpn", "expressvpn", "audible", "skillshare", "squarespace"
}


class ExplainableScorecardScorer(HighlightScorer):
    """
    Evaluates highlight candidates across independent dimensions:
    - Opening Hook (0-10)
    - Moment Payoff (0-10)
    - Standalone Coherence (0-10)
    - Speech Pacing (0-10)
    - Audio Inflection / Energy (0-10)
    - Visual Legibility (0-10)
    Supports hybrid LLM co-pilot scoring with local Ollama models (Llama 3.2, DeepSeek-R1, Gemma 3).
    """

    def __init__(
        self,
        llm_api_base: Optional[str] = None,
        llm_model: Optional[str] = None,
        use_llm: bool = False,
        timeout: int = 15,
        audio_analyzer: Optional[Any] = None,
        motion_analyzer: Optional[Any] = None,
        media_path: Optional[str] = None,
    ):
        import os
        self.llm_api_base = (llm_api_base or os.getenv("LLM_API_BASE") or "").rstrip("/")
        self.llm_model = llm_model or os.getenv("LLM_MODEL", "llama3.2:1b")
        self.use_llm = use_llm
        self.timeout = timeout
        self.audio_analyzer = audio_analyzer
        self.motion_analyzer = motion_analyzer
        self.media_path = media_path
        if self.audio_analyzer is None and media_path is not None:
            self.audio_analyzer = AudioEnergyAnalyzer(media_path=media_path)
        if self.motion_analyzer is None and media_path is not None:
            self.motion_analyzer = MotionEnergyAnalyzer(video_path=media_path)

    def _evaluate_with_llm(self, text: str) -> Optional[dict]:
        """Queries local Ollama model to verify hook crispness and detect sponsor ad contamination."""
        if not self.llm_api_base or not text:
            return None
        import urllib.request
        import json
        prompt = (
            f"You are an expert video editor. Critique this candidate short transcript:\n"
            f"\"{text[:800]}\"\n\n"
            f"Evaluate in JSON:\n"
            f"- 'is_sponsor_ad': boolean (true if sponsor read / promo / merch plug / discount)\n"
            f"- 'hook_score': float 0.0 to 10.0\n"
            f"- 'payoff_score': float 0.0 to 10.0\n"
            f"- 'crispness_score': float 0.0 to 10.0\n"
            f"Respond ONLY with valid JSON."
        )
        try:
            format_arg = "" if "r1" in self.llm_model.lower() else "json"
            req = urllib.request.Request(
                f"{self.llm_api_base}/api/generate",
                data=json.dumps({
                    "model": self.llm_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": format_arg,
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                raw = res.get("response", "")
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    return json.loads(m.group(0))
        except Exception:
            pass
        return None

    def score_candidate(
        self,
        candidate: HighlightCandidate,
        transcript: Transcript,
        heatmap: Optional[HeatmapData] = None,
        audio_analyzer: Optional[Any] = None,
        motion_analyzer: Optional[Any] = None,
        media_path: Optional[str] = None,
    ) -> HighlightCandidate:
        text = candidate.transcript_text.strip()
        words = text.split()
        num_words = len(words)
        duration = max(candidate.duration_seconds, 1.0)

        # 1. Opening Hook Score (0 to 10)
        # Evaluates first sentence / opening 5 words
        first_few_words = " ".join(words[:8]).lower()
        hook_score = 4.0

        if any(kw in first_few_words for kw in HOOK_KEYWORDS):
            hook_score += 3.0
        if "?" in first_few_words or (len(words) > 0 and words[0].lower() in ["why", "how", "what", "is", "can"]):
            hook_score += 2.0
        if len(first_few_words) < 40:  # Punchy short opening
            hook_score += 1.0
        hook_score = min(hook_score, 10.0)

        # 2. Moment Payoff Score (0 to 10)
        moment_score = 4.0
        text_lower = text.lower()
        payoff_matches = sum(1 for kw in PAYOFF_KEYWORDS if kw in text_lower)
        moment_score += min(payoff_matches * 1.5, 4.5)
        # Reward exclamation or strong conclusion
        if text.endswith("!") or text.endswith("."):
            moment_score += 1.5
        moment_score = min(moment_score, 10.0)

        # 3. Coherence Score (0 to 10)
        coherence_score = 5.0
        # Check start capitalization and avoid dangling connectors
        dangling_starts = ["and", "or", "so", "because", "then", "which", "he", "she", "uh", "um", "like"]
        is_they_hook = words and words[0].lower() == "they" and any(text_lower.startswith(th) for th in ["they said", "they told", "they warned", "they wouldn't", "they didn't", "they never"])
        is_but_hook = words and words[0].lower() == "but" and any(text_lower.startswith(bh) for bh in ["but actually", "but wait", "but here's", "but why", "but the truth"])

        if words and words[0].lower() in dangling_starts:
            coherence_score -= 3.0
        elif words and words[0].lower() == "they" and not is_they_hook:
            coherence_score -= 3.0
        elif words and words[0].lower() == "but" and not is_but_hook:
            coherence_score -= 3.0

        if text and text[0].isupper():
            coherence_score += 2.5
        if text and text[-1] in [".", "!", "?"]:
            coherence_score += 2.5
        coherence_score = max(min(coherence_score, 10.0), 0.0)

        # Check sponsor ad keyword contamination
        sponsor_matches = sum(1 for kw in SPONSOR_KEYWORDS if kw in text_lower)
        if sponsor_matches > 0:
            moment_score = max(0.0, moment_score - (sponsor_matches * 2.5))
            coherence_score = max(0.0, coherence_score - (sponsor_matches * 2.5))

        # Hybrid LLM evaluation if enabled
        llm_rationale = ""
        if self.use_llm:
            llm_eval = self._evaluate_with_llm(text)
            if llm_eval:
                if llm_eval.get("is_sponsor_ad"):
                    hook_score = min(hook_score, 1.5)
                    moment_score = min(moment_score, 1.0)
                    llm_rationale = ", [AI: Sponsor Ad Detected]"
                else:
                    llm_h = float(llm_eval.get("hook_score", hook_score))
                    llm_p = float(llm_eval.get("payoff_score", moment_score))
                    hook_score = round(0.5 * hook_score + 0.5 * llm_h, 1)
                    moment_score = round(0.5 * moment_score + 0.5 * llm_p, 1)
                    crisp = llm_eval.get("crispness_score")
                    if crisp is not None:
                        llm_rationale = f", [AI Crispness={crisp}/10]"

        # 4. Pacing Score (0 to 10) based on relative cadence deviation or fallback WPM
        wpm = (num_words / duration) * 60.0
        cadence_scorer = AdaptiveCadenceScorer(transcript)
        if cadence_scorer.is_available:
            pacing_score = cadence_scorer.score_candidate_cadence(candidate, transcript)
        else:
            # Optimal vertical short cadence is ~140-180 WPM fallback
            if 135.0 <= wpm <= 185.0:
                pacing_score = 9.5
            elif 110.0 <= wpm < 135.0 or 185.0 < wpm <= 210.0:
                pacing_score = 7.5
            elif 90.0 <= wpm < 110.0 or 210.0 < wpm <= 240.0:
                pacing_score = 5.5
            else:
                pacing_score = 3.5

        # If candidate was discovered by ArcDetector, blend its granular arc metrics
        if candidate.candidate_id.startswith("cand-arc-") and candidate.breakdown:
            arc_bd = candidate.breakdown
            hook_score = max(hook_score, arc_bd.hook_score)
            moment_score = max(moment_score, arc_bd.moment_score)
            coherence_score = max(coherence_score, arc_bd.coherence_score)
            pacing_score = max(pacing_score, arc_bd.pacing_score)

        # 5. Audience Retention / Replay Heatmap Score (0 to 10)
        heatmap_score = 0.0
        heatmap_rationale = ""
        if heatmap:
            overlapping_peaks = [
                pk for pk in heatmap.peaks
                if candidate.start_seconds <= pk.center_time <= candidate.end_seconds
            ]
            if overlapping_peaks:
                top_pk = max(overlapping_peaks, key=lambda pk: pk.intensity)
                if top_pk.classification == "GLOBAL_MAXIMA":
                    heatmap_score = 10.0
                    heatmap_rationale = f", Heatmap=10.0/10 (Global #1 Peak {top_pk.intensity*100:.0f}%)"
                elif top_pk.classification == "SPIKE_PAYOFF":
                    heatmap_score = min(top_pk.intensity * 9.0 + top_pk.prominence * 4.0, 9.5)
                    heatmap_rationale = f", Heatmap={heatmap_score:.1f}/10 (Replay Spike {top_pk.intensity*100:.0f}%)"
                else:
                    heatmap_score = min(top_pk.intensity * 8.5, 8.5)
                    heatmap_rationale = f", Heatmap={heatmap_score:.1f}/10 (Sustained Wave {top_pk.intensity*100:.0f}%)"
            elif heatmap.points:
                pts = [
                    p.value for p in heatmap.points
                    if p.end_time >= candidate.start_seconds and p.start_time <= candidate.end_seconds
                ]
                if pts:
                    avg_val = sum(pts) / len(pts)
                    heatmap_score = round(avg_val * 8.0, 1)
                    if heatmap_score >= 4.0:
                        heatmap_rationale = f", Heatmap={heatmap_score:.1f}/10 (Avg Retention {avg_val*100:.0f}%)"

        # 6. Audio Energy & Visual Score
        eff_audio_analyzer = audio_analyzer or self.audio_analyzer
        eff_motion_analyzer = motion_analyzer or self.motion_analyzer
        eff_media_path = media_path or self.media_path
        if eff_audio_analyzer is None and eff_media_path is not None:
            eff_audio_analyzer = AudioEnergyAnalyzer(media_path=eff_media_path)
        if eff_motion_analyzer is None and eff_media_path is not None:
            eff_motion_analyzer = MotionEnergyAnalyzer(video_path=eff_media_path)

        if eff_audio_analyzer is not None:
            audio_energy_score = eff_audio_analyzer.evaluate_interval(
                candidate.start_seconds, candidate.end_seconds
            )
        elif candidate.breakdown and candidate.breakdown.audio_energy_score > 0.0:
            audio_energy_score = candidate.breakdown.audio_energy_score
        else:
            audio_energy_score = 7.0  # Heuristic baseline fallback

        if eff_motion_analyzer is not None:
            visual_score = eff_motion_analyzer.evaluate_interval(
                candidate.start_seconds, candidate.end_seconds
            )
        elif candidate.breakdown and candidate.breakdown.visual_score > 0.0:
            visual_score = candidate.breakdown.visual_score
        else:
            visual_score = 8.0        # Default 9:16 layout suitability fallback

        # Confidence
        confidence = 0.85 if num_words >= 25 else 0.70

        breakdown = ScoreBreakdown(
            hook_score=round(hook_score, 1),
            moment_score=round(moment_score, 1),
            coherence_score=round(coherence_score, 1),
            pacing_score=round(pacing_score, 1),
            audio_energy_score=round(audio_energy_score, 1),
            visual_score=round(visual_score, 1),
            heatmap_score=round(heatmap_score, 1),
            confidence=confidence,
            rationale=(
                f"Hook={hook_score:.1f}/10, Payoff={moment_score:.1f}/10, "
                f"Coherence={coherence_score:.1f}/10, Cadence={wpm:.0f} WPM ({pacing_score:.1f}/10)"
                f"{heatmap_rationale}{llm_rationale}. Confidence={confidence:.2f}."
            ),
        )

        composite_score = breakdown.compute_composite_score()
        candidate.breakdown = breakdown
        candidate.score = composite_score
        candidate.rationale = breakdown.rationale

        return candidate

    def score_all(
        self,
        candidates: List[HighlightCandidate],
        transcript: Transcript,
        heatmap: Optional[HeatmapData] = None,
        audio_analyzer: Optional[Any] = None,
        motion_analyzer: Optional[Any] = None,
        media_path: Optional[str] = None,
    ) -> List[HighlightCandidate]:
        """Scores all candidates and sorts descending by composite score."""
        scored = [
            self.score_candidate(
                c, transcript, heatmap=heatmap,
                audio_analyzer=audio_analyzer, motion_analyzer=motion_analyzer,
                media_path=media_path,
            )
            for c in candidates
        ]
        return sorted(scored, key=lambda c: c.score, reverse=True)

