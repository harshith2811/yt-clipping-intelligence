"""
Context-Preserving Candidate Segmenter.
Discovers complete, coherent moments using sentence boundaries, pauses,
and target duration constraints rather than arbitrary fixed time windows.
Guarantees end_time > start_time and duration > 0.
"""

from typing import List, Optional, Any
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
        default_min_duration: float = 15.0,
        default_max_duration: float = 60.0,
        target_duration: Optional[float] = None,
        dynamic_windowing: bool = True,
    ):
        self.default_min_duration = default_min_duration
        self.default_max_duration = default_max_duration
        self.target_duration = target_duration
        self.dynamic_windowing = dynamic_windowing

    def _normalize_segments(self, segments: List[TranscriptSegment], max_dur: float) -> List[TranscriptSegment]:
        """Splits any oversized transcript segments into manageable duration chunks."""
        normalized: List[TranscriptSegment] = []
        seg_counter = 1
        chunk_target = self.target_duration or min(45.0, max_dur)
        for seg in segments:
            dur = seg.end - seg.start
            # Skip invalid or negative-duration segments
            if dur <= 0.0:
                continue

            if dur <= max_dur:
                normalized.append(seg)
                continue

            # Oversized segment: split by words if available
            if seg.words:
                chunk_words = []
                w_start = seg.words[0].start
                for w in seg.words:
                    chunk_words.append(w)
                    if (w.end - w_start) >= chunk_target:
                        chunk_text = " ".join(cw.word for cw in chunk_words)
                        if w.end > w_start:
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
                if chunk_words and chunk_words[-1].end > w_start:
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
                num_chunks = max(int(dur // chunk_target) + 1, 1)
                chunk_size = max(len(words) // num_chunks, 1)
                chunk_dur = dur / num_chunks
                for idx in range(0, len(words), chunk_size):
                    c_text = " ".join(words[idx : idx + chunk_size])
                    c_idx = idx // chunk_size
                    c_start = round(seg.start + (c_idx * chunk_dur), 2)
                    c_end = round(min(c_start + chunk_dur, seg.end), 2)
                    # BUG-15 fix: strictly require c_end > c_start
                    if c_end <= c_start:
                        continue
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

    def _generate_candidates_from_duration(
        self,
        video_id: str,
        total_duration: float,
        min_duration: float,
        max_duration: float,
        deduplicate: bool = True,
    ) -> List[HighlightCandidate]:
        """
        Generates candidate highlight moments when transcripts are unavailable,
        strictly enforcing positive start times, end > start, min/max duration bounds,
        and source media duration boundaries using a sliding window strategy with boundary backward extension.
        """
        candidates: List[HighlightCandidate] = []
        if total_duration < 1.0:
            return []

        # If source media is shorter than min_duration, allow single clip of full duration if >= 3.0s
        if total_duration <= min_duration:
            cid = f"cand-{video_id}-{uuid.uuid4().hex[:8]}"
            cand = HighlightCandidate(
                candidate_id=cid,
                video_id=video_id,
                start_seconds=0.0,
                end_seconds=round(total_duration, 2),
                duration_seconds=round(total_duration, 2),
                score=60.0,
                breakdown=ScoreBreakdown(
                    hook_score=5.0,
                    moment_score=5.0,
                    coherence_score=6.0,
                    pacing_score=6.0,
                    confidence=0.7,
                    rationale="Duration-bounded full-length candidate without transcript.",
                ),
                hook_title=f"Highlight Window 0.0s - {total_duration:.1f}s",
                suggested_description=f"Highlight from {video_id}: 0.0s to {total_duration:.1f}s",
                rationale=f"Full-source candidate window bounded to media duration {total_duration:.1f}s.",
                transcript_text="",
            )
            return [cand]

        target_win = min(self.target_duration or 35.0, max_duration)
        step = max(target_win / 2.0, 10.0)

        cur_start = 0.0
        while cur_start < total_duration:
            cur_end = min(cur_start + target_win, total_duration)
            cur_dur = cur_end - cur_start

            # Boundary clipping strategy:
            # If remaining duration near boundary is below min_duration, extend start backward
            if cur_dur < min_duration:
                if cur_start > 0:
                    cur_start = max(0.0, cur_end - min_duration)
                    cur_dur = cur_end - cur_start
                else:
                    break

            if cur_dur >= min_duration and cur_dur <= max_duration:
                cid = f"cand-{video_id}-{uuid.uuid4().hex[:8]}"
                cand = HighlightCandidate(
                    candidate_id=cid,
                    video_id=video_id,
                    start_seconds=round(cur_start, 2),
                    end_seconds=round(cur_end, 2),
                    duration_seconds=round(cur_dur, 2),
                    score=65.0,
                    breakdown=ScoreBreakdown(
                        hook_score=5.0,
                        moment_score=5.0,
                        coherence_score=6.0,
                        pacing_score=6.0,
                        confidence=0.7,
                        rationale="Duration-bounded sliding window without transcript.",
                    ),
                    hook_title=f"Highlight Moment at {cur_start:.0f}s",
                    suggested_description=f"Highlight from {video_id}: {cur_start:.1f}s to {cur_end:.1f}s",
                    rationale=f"Duration-bounded candidate window ({cur_dur:.1f}s) without transcript.",
                    transcript_text="",
                )
                if cand.validate_bounds(total_duration):
                    candidates.append(cand)

            if cur_end >= total_duration:
                break
            cur_start += step

        if not deduplicate:
            return candidates

        return suppress_overlapping_candidates(candidates, iou_threshold=0.40, containment_threshold=0.65)

    def _create_and_append_candidate(
        self,
        window_tuple: tuple,
        transcript: Transcript,
        raw_candidates: List[HighlightCandidate],
    ) -> None:
        w_start, w_end, w_dur, w_parts = window_tuple
        if w_end <= w_start or w_dur <= 0.0:
            return

        full_text = " ".join(w_parts).strip()
        first_sentence = w_parts[0].strip()

        # Dynamic heuristic scoring
        hook_score = 5.0
        first_lower = first_sentence.lower()
        if any(w in first_lower for w in ["why", "how", "what", "is", "this", "the secret", "here's", "never"]):
            hook_score += 1.5

        ends_sentence = full_text.endswith((".", "!", "?"))
        coherence_score = 7.5 if ends_sentence else 6.0
        if full_text and full_text[0].isupper():
            coherence_score += 1.0

        # WPM estimation for pacing
        num_words = len(full_text.split())
        wpm = (num_words / max(w_dur, 1.0)) * 60.0
        if 135.0 <= wpm <= 185.0:
            pacing_score = 8.5
        elif 110.0 <= wpm <= 210.0:
            pacing_score = 7.0
        else:
            pacing_score = 5.0

        breakdown = ScoreBreakdown(
            hook_score=min(hook_score, 10.0),
            moment_score=5.0,
            coherence_score=min(coherence_score, 10.0),
            pacing_score=pacing_score,
            confidence=0.8,
            rationale=f"Dynamic semantic candidate ({w_dur:.1f}s) bounded to natural sentence completion.",
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
            rationale=f"Dynamic context window from {w_start:.1f}s to {w_end:.1f}s ({w_dur:.1f}s).",
            transcript_text=full_text,
        )
        raw_candidates.append(cand)

    def detect_candidates(
        self,
        transcript: Transcript,
        min_duration: Optional[float] = None,
        max_duration: Optional[float] = None,
        deduplicate: bool = True,
        heatmap: Optional[Any] = None,
    ) -> List[HighlightCandidate]:
        min_dur = min_duration or self.default_min_duration
        max_dur = max_duration or self.default_max_duration
        if transcript.duration_seconds and transcript.duration_seconds < min_dur and transcript.duration_seconds >= 5.0:
            min_dur = round(transcript.duration_seconds * 0.9, 1)

        raw_segments = transcript.segments
        if not raw_segments:
            # BUG-08 fix: Generate duration-bounded highlight candidates even without transcript segments
            total_dur = transcript.duration_seconds
            if not total_dur or total_dur <= 0.0:
                return []
            return self._generate_candidates_from_duration(
                video_id=transcript.video_id,
                total_duration=total_dur,
                min_duration=min_dur,
                max_duration=max_dur,
                deduplicate=deduplicate,
            )

        segments = self._normalize_segments(raw_segments, max_dur)
        raw_candidates: List[HighlightCandidate] = []

        # Feature: Synthesize candidates directly anchored to audience retention peaks
        if heatmap and hasattr(heatmap, "peaks") and heatmap.peaks:
            for pk in heatmap.peaks:
                pk_start = max(pk.suggested_clip_start, 0.0)
                media_limit = transcript.duration_seconds if (transcript.duration_seconds and transcript.duration_seconds > 0) else pk.suggested_clip_end
                pk_end = min(pk.suggested_clip_end, media_limit)
                pk_dur = pk_end - pk_start
                if pk_dur >= min_dur and pk_dur <= max_dur:
                    matching_texts = [
                        s.text for s in raw_segments
                        if s.end >= pk_start and s.start <= pk_end
                    ]
                    full_pk_text = " ".join(matching_texts).strip()
                    first_line = matching_texts[0].strip() if matching_texts else f"Peak Moment at {pk_start:.0f}s"
                    cid = f"cand-peak-{transcript.video_id}-{pk.peak_id}"
                    breakdown = ScoreBreakdown(
                        hook_score=6.0,
                        moment_score=7.0,
                        coherence_score=7.0,
                        pacing_score=6.0,
                        heatmap_score=min(pk.intensity * 10.0, 10.0),
                        confidence=0.85,
                        rationale=f"Audience replay peak [{pk.classification}] intensity {pk.intensity*100:.0f}%.",
                    )
                    cand = HighlightCandidate(
                        candidate_id=cid,
                        video_id=transcript.video_id,
                        start_seconds=round(pk_start, 2),
                        end_seconds=round(pk_end, 2),
                        duration_seconds=round(pk_dur, 2),
                        score=breakdown.compute_composite_score(),
                        breakdown=breakdown,
                        hook_title=first_line[:60] + ("..." if len(first_line) > 60 else ""),
                        suggested_description=f"Audience Peak from {transcript.video_id}: {full_pk_text[:100]}...",
                        rationale=f"Peak-anchored candidate [{pk.classification}] from {pk_start:.1f}s to {pk_end:.1f}s.",
                        transcript_text=full_pk_text,
                    )
                    if cand.validate_bounds(media_limit):
                        raw_candidates.append(cand)

        n = len(segments)

        # Slide through segments to find coherent windows
        for i in range(n):
            start_seg = segments[i]
            cand_start = start_seg.start
            text_parts = [start_seg.text]

            # Legacy single target duration behavior if dynamic_windowing is explicitly disabled
            if not self.dynamic_windowing and self.target_duration is not None:
                best_window = None
                best_diff = float("inf")
                for j in range(i, n):
                    end_seg = segments[j]
                    if j > i:
                        text_parts.append(end_seg.text)
                    cand_end = end_seg.end
                    cand_dur = cand_end - cand_start
                    if cand_dur >= min_dur and cand_dur <= max_dur:
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
                    self._create_and_append_candidate(best_window, transcript, raw_candidates)
                continue

            # Dynamic Windowing: Discover all complete semantic thought units bounded to sentence endings or natural speech pauses
            has_emitted_thought = False
            last_valid_window = None
            for j in range(i, n):
                end_seg = segments[j]
                if j > i:
                    text_parts.append(end_seg.text)

                cand_end = end_seg.end
                cand_dur = cand_end - cand_start

                if cand_dur >= min_dur and cand_dur <= max_dur:
                    ends_sentence = end_seg.text.strip().endswith((".", "!", "?"))
                    has_pause = (j < n - 1 and (segments[j + 1].start - end_seg.end) >= 0.5)

                    if ends_sentence or has_pause:
                        self._create_and_append_candidate(
                            (cand_start, cand_end, cand_dur, list(text_parts)),
                            transcript,
                            raw_candidates,
                        )
                        has_emitted_thought = True

                    last_valid_window = (cand_start, cand_end, cand_dur, list(text_parts))
                elif cand_dur > max_dur:
                    break

            # Fallback for unpunctuated continuous segments
            if not has_emitted_thought and last_valid_window:
                self._create_and_append_candidate(last_valid_window, transcript, raw_candidates)

        if not deduplicate:
            return raw_candidates

        return suppress_overlapping_candidates(raw_candidates, iou_threshold=0.40, containment_threshold=0.65)
