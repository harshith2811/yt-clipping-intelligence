"""
Explainable Multi-Signal Highlight Scorer.
Implements the hook vs moment scorecard methodology adapted from ClipMint.
Evaluates opening hook strength, narrative payoff, pacing (WPM), coherence,
and produces human-auditable rationales.
"""

from typing import List, Optional
import re
from ..contracts.models import HighlightCandidate, Transcript, ScoreBreakdown, HeatmapData
from ..contracts.interfaces import HighlightScorer


HOOK_KEYWORDS = {
    "secret", "never", "why", "how to", "most", "mistake", "truth", "revealed",
    "insane", "stop", "here is", "don't", "shocking", "game changer", "formula",
    "fail", "proven", "hack", "trick", "worst", "best", "warning"
}

PAYOFF_KEYWORDS = {
    "actually", "instead", "turns out", "that is why", "the reason is", "solution",
    "key takeaway", "result", "finally", "realized", "in fact", "ultimately", "remember"
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
    """

    def score_candidate(
        self,
        candidate: HighlightCandidate,
        transcript: Transcript,
        heatmap: Optional[HeatmapData] = None,
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
        dangling_starts = ["and", "or", "but", "so", "because", "then", "which", "he", "she", "they"]
        if words and words[0].lower() in dangling_starts:
            coherence_score -= 3.0
        if text and text[0].isupper():
            coherence_score += 2.5
        if text and text[-1] in [".", "!", "?"]:
            coherence_score += 2.5
        coherence_score = max(min(coherence_score, 10.0), 0.0)

        # 4. Pacing Score (0 to 10) based on Words Per Minute (WPM)
        wpm = (num_words / duration) * 60.0
        # Optimal vertical short cadence is ~140-180 WPM
        if 135.0 <= wpm <= 185.0:
            pacing_score = 9.5
        elif 110.0 <= wpm < 135.0 or 185.0 < wpm <= 210.0:
            pacing_score = 7.5
        elif 90.0 <= wpm < 110.0 or 210.0 < wpm <= 240.0:
            pacing_score = 5.5
        else:
            pacing_score = 3.5

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
        audio_energy_score = 7.0  # Heuristic baseline
        visual_score = 8.0        # Default 9:16 layout suitability

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
                f"{heatmap_rationale}. Confidence={confidence:.2f}."
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
    ) -> List[HighlightCandidate]:
        """Scores all candidates and sorts descending by composite score."""
        scored = [self.score_candidate(c, transcript, heatmap=heatmap) for c in candidates]
        return sorted(scored, key=lambda c: c.score, reverse=True)
