"""
Context-Preserving Candidate Segmenter.
Discovers complete, coherent moments using sentence boundaries, pauses,
and target duration constraints rather than arbitrary fixed time windows.
"""

from typing import List, Optional
import uuid
from ..contracts.models import Transcript, TranscriptSegment, HighlightCandidate, ScoreBreakdown
from ..contracts.interfaces import HighlightDetector
from .dedupe import suppress_overlapping_candidates


class ContextAwareSegmenter(HighlightDetector):
    """
    Builds highlight candidates from transcript segments.
    Aligns cuts strictly to sentence starts and sentence completions.
    """

    def __init__(
        self,
        default_min_duration: float = 20.0,
        default_max_duration: float = 60.0,
        target_duration: float = 35.0,
    ):
        self.default_min_duration = default_min_duration
        self.default_max_duration = default_max_duration
        self.target_duration = target_duration

    def _normalize_segments(self, segments: List[TranscriptSegment], max_dur: float) -> List[TranscriptSegment]:
        """Splits any oversized transcript segments into target duration chunks."""
        normalized: List[TranscriptSegment] = []
        seg_counter = 1
        for seg in segments:
            dur = seg.end - seg.start
            if dur <= max_dur:
                normalized.append(seg)
                continue

            # Oversized segment: split by words if available
            if seg.words:
                chunk_words = []
                w_start = seg.words[0].start
                for w in seg.words:
                    chunk_words.append(w)
                    if (w.end - w_start) >= self.target_duration:
                        chunk_text = " ".join(cw.word for cw in chunk_words)
                        normalized.append(
                            TranscriptSegment(
                                segment_id=seg_counter,
                                start=w_start,
                                end=w.end,
                                text=chunk_text,
                                words=chunk_words,
                            )
                        )
                        seg_counter += 1
                        chunk_words = []
                        w_start = w.end
                if chunk_words:
                    chunk_text = " ".join(cw.word for cw in chunk_words)
                    normalized.append(
                        TranscriptSegment(
                            segment_id=seg_counter,
                            start=w_start,
                            end=chunk_words[-1].end,
                            text=chunk_text,
                            words=chunk_words,
                        )
                    )
                    seg_counter += 1
            else:
                # Split text evenly across duration
                words = seg.text.split()
                if not words:
                    continue
                num_chunks = max(int(dur // self.target_duration) + 1, 1)
                chunk_size = max(len(words) // num_chunks, 1)
                chunk_dur = dur / num_chunks
                for idx in range(0, len(words), chunk_size):
                    c_text = " ".join(words[idx : idx + chunk_size])
                    c_idx = idx // chunk_size
                    c_start = round(seg.start + (c_idx * chunk_dur), 2)
                    c_end = round(min(c_start + chunk_dur, seg.end), 2)
                    normalized.append(
                        TranscriptSegment(
                            segment_id=seg_counter,
                            start=c_start,
                            end=c_end,
                            text=c_text,
                            words=[],
                        )
                    )
                    seg_counter += 1
        return normalized

    def detect_candidates(
        self,
        transcript: Transcript,
        min_duration: Optional[float] = None,
        max_duration: Optional[float] = None,
    ) -> List[HighlightCandidate]:
        min_dur = min_duration or self.default_min_duration
        max_dur = max_duration or self.default_max_duration
        if transcript.duration_seconds and transcript.duration_seconds < min_dur and transcript.duration_seconds >= 5.0:
            min_dur = round(transcript.duration_seconds * 0.9, 1)

        raw_segments = transcript.segments
        if not raw_segments:
            # Handle empty transcript safely
            return []

        segments = self._normalize_segments(raw_segments, max_dur)
        raw_candidates: List[HighlightCandidate] = []
        n = len(segments)

        # Slide through segments to find coherent windows
        for i in range(n):
            start_seg = segments[i]
            cand_start = start_seg.start
            text_parts = [start_seg.text]

            best_window = None
            best_diff = float("inf")

            for j in range(i, n):
                end_seg = segments[j]
                if j > i:
                    text_parts.append(end_seg.text)

                cand_end = end_seg.end
                cand_dur = cand_end - cand_start

                if cand_dur >= min_dur and cand_dur <= max_dur:
                    # Preference for complete sentence endings near target_duration
                    ends_sentence = end_seg.text.strip().endswith((".", "!", "?"))
                    diff = abs(cand_dur - self.target_duration)
                    effective_diff = diff if ends_sentence else diff + 10.0

                    if effective_diff < best_diff:
                        best_diff = effective_diff
                        best_window = (cand_start, cand_end, cand_dur, list(text_parts))

                    if cand_dur >= self.target_duration and ends_sentence:
                        break
                elif cand_dur > max_dur:
                    break

            if best_window:
                w_start, w_end, w_dur, w_parts = best_window
                full_text = " ".join(w_parts).strip()
                first_sentence = w_parts[0].strip()

                # Starter scorecard (refined by HighlightScorer)
                breakdown = ScoreBreakdown(
                    hook_score=5.0,
                    moment_score=5.0,
                    coherence_score=7.0,
                    pacing_score=6.0,
                    confidence=0.8,
                    rationale="Candidate segment with complete sentence boundaries.",
                )
                score = breakdown.compute_composite_score()

                cid = f"cand-{transcript.video_id}-{uuid.uuid4().hex[:8]}"
                cand = HighlightCandidate(
                    candidate_id=cid,
                    video_id=transcript.video_id,
                    start_seconds=round(w_start, 2),
                    end_seconds=round(w_end, 2),
                    duration_seconds=round(w_dur, 2),
                    score=score,
                    breakdown=breakdown,
                    hook_title=first_sentence[:60] + ("..." if len(first_sentence) > 60 else ""),
                    suggested_description=f"Highlight from {transcript.video_id}: {full_text[:100]}...",
                    rationale=f"Context-safe window from {w_start:.1f}s to {w_end:.1f}s ({w_dur:.1f}s).",
                    transcript_text=full_text,
                )
                raw_candidates.append(cand)

        # Deduplicate overlapping candidates
        return suppress_overlapping_candidates(raw_candidates, iou_threshold=0.40, containment_threshold=0.65)
