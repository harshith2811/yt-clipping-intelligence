"""
Narrative Arc Detector for High-Retention Short-Form Highlight Discovery.
Enforces 'Strong Start, Strong End' paradigm:
- Strong Start (Hook): Opens with curiosity gap, question, bold claim, or high-conviction statement.
  Rejects clips starting on weak dangling connectors (e.g. 'and', 'so', 'because', 'uh').
- Escalation (Arc Body): Tension or interest builds via revelation, contrast, or explanation.
- Strong End (Payoff): Resolves with a punchline, conclusion, takeaway, or emotional resolution.
  Rejects clips trailing off mid-sentence or ending on weak hedges ('kind of', 'sort of').
- Speech Dynamics: Evaluates tempo variance (WPM modulation) and dramatic pause beats.
Zero external dependencies, microsecond latency (< 10ms for full video).
"""

from typing import List, Optional, Tuple, Any
import uuid
import math
import statistics

from ..contracts.models import (
    Transcript,
    HighlightCandidate,
    ScoreBreakdown,
    HeatmapData,
    WordTimestamp,
)
from .sentence_classifier import (
    SentenceClassifier,
    ClassifiedSentence,
    HOOK,
    CONTEXT,
    ESCALATION,
    REVELATION,
    PAYOFF,
    FILLER,
    SPONSOR,
    HOOK_QUESTION_WORDS,
    HOOK_BOLD_ABSOLUTES,
    HOOK_PROVOCATIVE,
    HOOK_IMPERATIVES,
    PAYOFF_CONCLUSION_MARKERS,
    PAYOFF_EMOTION_RESOLUTION,
    WEAK_OPENERS,
    WEAK_ENDINGS,
    PROVOCATIVE_THEY_HOOKS,
    CONTRAST_BUT_HOOKS,
)

PAYOFF_CLIMAX_MARKERS = frozenset({
    "changes everything", "blow your mind", "completely", "solution",
    "the reason is", "that is how", "that's how", "that is why", "that's why",
    "turns out", "it turns out", "in fact", "the point is", "my take",
    "at the end of the day", "the bottom line", "so yeah", "and that's",
    "i'm fine with", "i'm cool with", "worth it", "not worth it",
    "makes a big difference", "pretty cool", "peace", "let me know",
})

RHETORICAL_CLOSING_PATTERNS = (
    "would you", "could you", "what do you", "have you", "how about",
    "do you think", "will you", "should you", "can you",
)
from .dedupe import suppress_overlapping_candidates


class ArcDetector:
    """
    Discovers complete, high-retention highlight moments by scanning for
    strong hooks, escalating narrative context, and satisfying payoffs.
    """

    def __init__(
        self,
        classifier: Optional[SentenceClassifier] = None,
        default_min_duration: float = 15.0,
        default_max_duration: float = 60.0,
    ):
        self.classifier = classifier or SentenceClassifier()
        self.default_min_duration = default_min_duration
        self.default_max_duration = default_max_duration

    def discover_arcs(
        self,
        transcript: Transcript,
        min_duration: Optional[float] = None,
        max_duration: Optional[float] = None,
        heatmap: Optional[HeatmapData] = None,
        deduplicate: bool = True,
    ) -> List[HighlightCandidate]:
        """
        Discovers complete narrative arcs within duration bounds.
        Each candidate is guaranteed to have a strong start and a strong end.
        """
        min_dur = min_duration or self.default_min_duration
        max_dur = max_duration or self.default_max_duration

        if transcript.duration_seconds and transcript.duration_seconds < min_dur and transcript.duration_seconds >= 5.0:
            min_dur = round(transcript.duration_seconds * 0.9, 1)

        classified_sentences = self.classifier.classify_transcript(transcript)
        if not classified_sentences:
            return []

        raw_candidates: List[HighlightCandidate] = []
        n = len(classified_sentences)

        for i in range(n):
            start_sent = classified_sentences[i]

            # Hard gate 1: Never start on a sponsor segment
            if start_sent.sentence_type == SPONSOR:
                continue

            # Hard gate 2: Reject weak dangling starters ("and", "so", "uh", "or", etc.)
            # unless it's a high-confidence quoted line or intentional contrast hook
            first_word = start_sent.text.split()[0].lower().rstrip(".,!?:;") if start_sent.text.split() else ""
            is_quoted = start_sent.text.strip().startswith((">>", '"', "'"))
            lower_start = start_sent.text.lower().strip()
            is_they_hook = (first_word == "they" and any(lower_start.startswith(th) for th in PROVOCATIVE_THEY_HOOKS))
            is_but_hook = (first_word == "but" and any(lower_start.startswith(bh) for bh in CONTRAST_BUT_HOOKS))

            if first_word in WEAK_OPENERS and not is_but_hook and not is_quoted and start_sent.confidence < 0.90:
                continue
            if first_word == "they" and not is_they_hook and not is_quoted:
                continue

            # Hard gate 3: Prefer starting on HOOK, REVELATION, or strong CONTEXT.
            # Skip pure FILLER starts.
            if start_sent.sentence_type == FILLER:
                continue

            # Scan forward to discover matching payoffs within duration window
            arc_sentences: List[ClassifiedSentence] = [start_sent]
            hook_candidates: List[HighlightCandidate] = []

            for j in range(i + 1, n):
                end_sent = classified_sentences[j]

                # Stop if we hit a sponsor read
                if end_sent.sentence_type == SPONSOR:
                    break

                arc_sentences.append(end_sent)
                arc_dur = end_sent.end - start_sent.start

                if arc_dur > max_dur:
                    break

                if arc_dur >= min_dur:
                    # Check end boundary quality
                    end_text = end_sent.text.strip()
                    ends_sentence = end_text.endswith((".", "!", "?"))
                    
                    # Reject weak trailing hedges ("kind of", "sort of", "i guess")
                    end_lower = end_text.lower()
                    has_weak_ending = any(w in end_lower[-30:] for w in WEAK_ENDINGS)

                    if ends_sentence and not has_weak_ending:
                        cand = self._evaluate_and_build_candidate(
                            start_sent=start_sent,
                            end_sent=end_sent,
                            arc_sentences=arc_sentences,
                            transcript=transcript,
                            heatmap=heatmap,
                        )
                        if cand and cand.validate_bounds(transcript.duration_seconds or end_sent.end):
                            hook_candidates.append(cand)

            if hook_candidates:
                # Keep top 2 distinctly-sized candidates for this hook
                hook_candidates.sort(key=lambda c: c.score, reverse=True)
                raw_candidates.append(hook_candidates[0])
                if len(hook_candidates) > 1 and abs(hook_candidates[1].duration_seconds - hook_candidates[0].duration_seconds) >= 8.0:
                    raw_candidates.append(hook_candidates[1])

        if not raw_candidates:
            return []

        if deduplicate:
            return suppress_overlapping_candidates(raw_candidates, iou_threshold=0.40, containment_threshold=0.65)
        return sorted(raw_candidates, key=lambda c: c.score, reverse=True)

    def _evaluate_and_build_candidate(
        self,
        start_sent: ClassifiedSentence,
        end_sent: ClassifiedSentence,
        arc_sentences: List[ClassifiedSentence],
        transcript: Transcript,
        heatmap: Optional[HeatmapData] = None,
    ) -> Optional[HighlightCandidate]:
        """Evaluates candidate arc across multi-signal dimensions and constructs candidate."""
        w_start = start_sent.start
        w_end = end_sent.end
        w_dur = w_end - w_start

        if w_dur <= 0.0 or w_end <= w_start:
            return None

        full_text = " ".join(s.text for s in arc_sentences).strip()
        first_sentence_text = start_sent.text.strip()
        last_sentence_text = end_sent.text.strip()

        # 1. Hook Strength Score (0.0 - 10.0)
        hook_score = self._score_hook_strength(start_sent)

        # 2. Payoff Resolution Score (0.0 - 10.0)
        payoff_score = self._score_payoff_resolution(end_sent, full_text)

        # 3. Arc Completeness Score (0.0 - 10.0)
        arc_score = self._score_arc_completeness(arc_sentences)

        # 4. Speech Dynamics & Pacing (0.0 - 10.0)
        pacing_score = self._score_speech_dynamics(arc_sentences, w_dur)

        # 5. Audience Retention / Heatmap (0.0 - 10.0)
        heatmap_score = 0.0
        heatmap_rationale = ""
        if heatmap:
            peaks = [pk for pk in heatmap.peaks if w_start <= pk.center_time <= w_end]
            if peaks:
                top_pk = max(peaks, key=lambda p: p.intensity)
                if top_pk.classification == "GLOBAL_MAXIMA":
                    heatmap_score = 10.0
                    heatmap_rationale = f", Heatmap=10.0/10 (Global #1 Peak {top_pk.intensity*100:.0f}%)"
                elif top_pk.classification == "SPIKE_PAYOFF":
                    heatmap_score = min(top_pk.intensity * 9.0 + top_pk.prominence * 4.0, 9.5)
                    heatmap_rationale = f", Heatmap={heatmap_score:.1f}/10 (Replay Spike {top_pk.intensity*100:.0f}%)"
                else:
                    heatmap_score = min(top_pk.intensity * 8.5, 8.5)
                    heatmap_rationale = f", Heatmap={heatmap_score:.1f}/10 (Engagement Wave {top_pk.intensity*100:.0f}%)"
            elif heatmap.points:
                pts = [p.value for p in heatmap.points if p.end_time >= w_start and p.start_time <= w_end]
                if pts:
                    avg_val = sum(pts) / len(pts)
                    heatmap_score = round(avg_val * 8.0, 1)
                    if heatmap_score >= 4.0:
                        heatmap_rationale = f", Heatmap={heatmap_score:.1f}/10 (Avg {avg_val*100:.0f}%)"

        breakdown = ScoreBreakdown(
            hook_score=round(hook_score, 1),
            moment_score=round(payoff_score, 1),
            coherence_score=round(arc_score, 1),
            pacing_score=round(pacing_score, 1),
            audio_energy_score=7.0,
            visual_score=8.0,
            heatmap_score=round(heatmap_score, 1),
            confidence=0.88,
            rationale=(
                f"Hook={hook_score:.1f}/10 [{start_sent.sentence_type}], "
                f"Payoff={payoff_score:.1f}/10 [{end_sent.sentence_type}], "
                f"Arc={arc_score:.1f}/10, Dynamics={pacing_score:.1f}/10"
                f"{heatmap_rationale}."
            ),
        )

        composite = breakdown.compute_composite_score()

        cid = f"cand-arc-{transcript.video_id}-{uuid.uuid4().hex[:8]}"
        return HighlightCandidate(
            candidate_id=cid,
            video_id=transcript.video_id,
            start_seconds=round(w_start, 2),
            end_seconds=round(w_end, 2),
            duration_seconds=round(w_dur, 2),
            score=composite,
            breakdown=breakdown,
            hook_title=first_sentence_text[:60] + ("..." if len(first_sentence_text) > 60 else ""),
            suggested_description=f"Highlight from {transcript.video_id}: {full_text[:120]}...",
            rationale=f"Narrative Arc ({w_dur:.1f}s): {breakdown.rationale}",
            transcript_text=full_text,
        )

    def _score_hook_strength(self, sent: ClassifiedSentence) -> float:
        """Evaluates opening sentence capture power (0.0 to 10.0)."""
        score = 4.0
        text = sent.text.strip()
        lower = text.lower()
        words = text.split()
        first_word = words[0].lower().rstrip(".,!?:;") if words else ""

        # Question hook
        if first_word in HOOK_QUESTION_WORDS and text.endswith("?"):
            score += 3.0
        elif first_word in HOOK_QUESTION_WORDS:
            score += 1.5

        # Bold absolute
        if any(ba in lower for ba in HOOK_BOLD_ABSOLUTES):
            score += 2.0

        # Provocative opening
        if any(p in lower for p in HOOK_PROVOCATIVE):
            score += 2.0

        # Imperative opening ("Look", "Listen", "Stop")
        if first_word in HOOK_IMPERATIVES:
            score += 1.5

        # Direct address
        if first_word == "you" or "you " in lower[:20]:
            score += 1.0

        # Punchy shortness
        if len(words) <= 10:
            score += 1.0

        # Sentence type boost
        if sent.sentence_type == HOOK:
            score += 1.5
        elif sent.sentence_type == REVELATION:
            score += 1.0

        # Weak dangling opener penalty
        is_they_hook = (first_word == "they" and any(lower.startswith(th) for th in PROVOCATIVE_THEY_HOOKS))
        is_but_hook = (first_word == "but" and any(lower.startswith(bh) for bh in CONTRAST_BUT_HOOKS))

        if first_word in WEAK_OPENERS and not is_but_hook:
            score -= 3.0
        elif first_word == "they" and not is_they_hook:
            score -= 2.5

        return max(1.0, min(10.0, score))

    def _score_payoff_resolution(self, sent: ClassifiedSentence, full_text: str) -> float:
        """Evaluates closing payoff and conclusion power (0.0 to 10.0)."""
        score = 4.0
        text = sent.text.strip()
        lower = text.lower()

        # Strong terminal punctuation
        if text.endswith("!"):
            score += 2.0
        elif text.endswith("."):
            score += 1.0

        # Rhetorical closing question
        if text.endswith("?"):
            if any(lower.startswith(q) for q in RHETORICAL_CLOSING_PATTERNS):
                score += 2.5
            else:
                score += 1.5

        # Climax markers
        if any(c in lower for c in PAYOFF_CLIMAX_MARKERS):
            score += 2.0

        # Conclusion markers
        if any(m in lower for m in PAYOFF_CONCLUSION_MARKERS):
            score += 2.5

        # Emotional resolution
        if any(e in lower for e in PAYOFF_EMOTION_RESOLUTION):
            score += 2.0

        # Sentence type boost
        if sent.sentence_type in (PAYOFF, REVELATION):
            score += 1.5

        # Weak ending penalty
        last_30 = lower[-30:] if len(lower) > 30 else lower
        if any(w in last_30 for w in WEAK_ENDINGS):
            score -= 2.5

        return max(1.0, min(10.0, score))

    def _score_arc_completeness(self, sentences: List[ClassifiedSentence]) -> float:
        """Evaluates narrative structure: setup -> escalation -> payoff (0.0 to 10.0)."""
        score = 6.0
        full_text = " ".join(s.text for s in sentences).strip()
        if full_text and full_text[0].isupper():
            score += 1.0
        if full_text and full_text.endswith((".", "!", "?")):
            score += 1.0

        types = [s.sentence_type for s in sentences]

        # Contains escalation / tension
        if ESCALATION in types:
            score += 1.0

        # Contains revelation / insight
        if REVELATION in types:
            score += 1.0

        # Low filler ratio
        filler_count = types.count(FILLER)
        filler_ratio = filler_count / max(len(types), 1)
        if filler_ratio < 0.10:
            score += 0.5
        elif filler_ratio > 0.25:
            score -= 2.0

        # Diversity of sentence roles (setup != payoff)
        if sentences[0].sentence_type != sentences[-1].sentence_type:
            score += 0.5

        return max(1.0, min(10.0, score))

    def _score_speech_dynamics(self, sentences: List[ClassifiedSentence], total_dur: float) -> float:
        """Evaluates pacing, tempo variance, and dramatic pauses (0.0 to 10.0)."""
        all_words: List[WordTimestamp] = []
        for s in sentences:
            if s.words:
                all_words.extend(s.words)

        num_words = sum(len(s.text.split()) for s in sentences)
        avg_wpm = (num_words / max(total_dur, 1.0)) * 60.0

        # Baseline WPM cadence scoring
        score = 6.0
        if 135.0 <= avg_wpm <= 185.0:
            score += 2.5
        elif 110.0 <= avg_wpm <= 210.0:
            score += 1.5
        elif 80.0 <= avg_wpm < 110.0:
            score += 0.5
        else:
            score -= 0.5

        # If word timestamps are available, measure 3-act tempo variance
        if len(all_words) >= 9 and total_dur >= 10.0:
            third = total_dur / 3.0
            t_start = sentences[0].start
            w1 = [w for w in all_words if w.start < t_start + third]
            w2 = [w for w in all_words if t_start + third <= w.start < t_start + 2 * third]
            w3 = [w for w in all_words if w.start >= t_start + 2 * third]

            if w1 and w2 and w3:
                wpm1 = (len(w1) / third) * 60.0
                wpm2 = (len(w2) / third) * 60.0
                wpm3 = (len(w3) / third) * 60.0

                try:
                    tempo_stdev = statistics.stdev([wpm1, wpm2, wpm3])
                    # Dynamic modulation (speeding up in middle / settling at end)
                    if 8.0 <= tempo_stdev <= 60.0:
                        score += 1.5
                except statistics.StatisticsError:
                    pass

        # Check for dramatic pauses between sentences (0.3s to 1.2s gap is dramatic, not dead air)
        pause_beats = 0
        for k in range(len(sentences) - 1):
            gap = sentences[k + 1].start - sentences[k].end
            if 0.35 <= gap <= 1.2:
                pause_beats += 1

        if 1 <= pause_beats <= 4:
            score += 1.0

        return max(1.0, min(10.0, score))
