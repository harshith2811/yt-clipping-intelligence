"""
Dead-Air & Filler Pacing Pruner (Algorithmic mechanics adapted from deadair.py).
Performs deterministic pre-render and scoring analysis on Whisper word timestamps:
- Dead Air Removal: Detects and trims silent pauses between spoken cues > 0.35s.
- Filler Pruning: Identifies standalone non-value filler tokens ('um', 'uh', 'so yeah', 'basically', 'you know').
- Sentence Restart Detection: Detects false starts and retakes where the first 3-5 normalized words of consecutive cues match.
- Pacing Tightness Score: Calibrated 0.0 to 10.0 pacing cadence metric.
- Micro-Jump-Cut Generation: Produces keep intervals and FFmpeg filter specifications.
"""

from typing import List, Dict, Tuple, Optional, Any, Set
from dataclasses import dataclass, field, asdict
import re

from ..contracts.models import (
    WordTimestamp,
    TranscriptSegment,
    Transcript,
    HighlightCandidate,
)

# Standard standalone filler single words
STANDALONE_FILLER_WORDS: Set[str] = {
    "um", "uh", "er", "ah", "basically", "literally", "like"
}

# Standard multi-word filler phrases
MULTI_WORD_FILLERS: List[Tuple[str, ...]] = [
    ("so", "yeah"),
    ("you", "know"),
    ("i", "mean"),
    ("sort", "of"),
    ("kind", "of"),
]

DEFAULT_DEAD_AIR_THRESHOLD = 0.35  # seconds
DEFAULT_TARGET_PAUSE = 0.15        # seconds to retain during micro-jump-cuts


@dataclass(frozen=True)
class DeadAirGap:
    """Represents a silent pause between consecutive spoken words or cues."""
    start: float
    end: float
    duration: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FillerOccurrence:
    """Represents detected filler tokens in the transcript."""
    phrase: str
    start: float
    end: float
    word_indices: List[int]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SentenceRestart:
    """Represents a false start retake where consecutive cues share a 3-5 word prefix."""
    prev_text: str
    curr_text: str
    matching_prefix: List[str]
    prefix_length: int
    prev_start: float
    prev_end: float
    curr_start: float
    curr_end: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PruneResult:
    """Telemetry and intervals resulting from dead-air, filler, and restart pruning."""
    original_duration: float
    pruned_duration: float
    dead_air_duration: float
    dead_air_gaps: List[DeadAirGap] = field(default_factory=list)
    filler_occurrences: List[FillerOccurrence] = field(default_factory=list)
    restarts: List[SentenceRestart] = field(default_factory=list)
    keep_intervals: List[Tuple[float, float]] = field(default_factory=list)
    pacing_tightness_score: float = 10.0
    pruned_words: List[WordTimestamp] = field(default_factory=list)
    pruned_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_duration": round(self.original_duration, 3),
            "pruned_duration": round(self.pruned_duration, 3),
            "dead_air_duration": round(self.dead_air_duration, 3),
            "dead_air_gaps": [g.to_dict() for g in self.dead_air_gaps],
            "filler_occurrences": [f.to_dict() for f in self.filler_occurrences],
            "restarts": [r.to_dict() for r in self.restarts],
            "keep_intervals": [(round(s, 3), round(e, 3)) for s, e in self.keep_intervals],
            "pacing_tightness_score": self.pacing_tightness_score,
            "pruned_text": self.pruned_text,
        }


def _normalize_word(raw: str) -> str:
    """Strips punctuation and lowercases a word for deterministic linguistic matching."""
    return re.sub(r"[^\w]", "", raw).lower()


class DeadAirPruner:
    """
    Deterministic pre-render pacing optimizer and dead-air pruner.
    """

    def __init__(
        self,
        dead_air_threshold: float = DEFAULT_DEAD_AIR_THRESHOLD,
        target_pause: float = DEFAULT_TARGET_PAUSE,
        filler_words: Optional[Set[str]] = None,
        multi_word_fillers: Optional[List[Tuple[str, ...]]] = None,
    ):
        self.dead_air_threshold = dead_air_threshold
        self.target_pause = target_pause
        self.filler_words = filler_words or STANDALONE_FILLER_WORDS
        self.multi_word_fillers = multi_word_fillers or MULTI_WORD_FILLERS

    def detect_dead_air_gaps(
        self,
        words: List[WordTimestamp],
        threshold: Optional[float] = None,
        start_bound: Optional[float] = None,
        end_bound: Optional[float] = None,
    ) -> List[DeadAirGap]:
        """
        Identifies silent pauses between consecutive spoken words > threshold (default 0.35s),
        as well as leading and trailing dead air silence if bounds are provided.
        """
        th = threshold if threshold is not None else self.dead_air_threshold
        gaps: List[DeadAirGap] = []
        if not words:
            if start_bound is not None and end_bound is not None:
                duration = end_bound - start_bound
                if duration > th:
                    gaps.append(
                        DeadAirGap(
                            start=round(start_bound, 3),
                            end=round(end_bound, 3),
                            duration=round(duration, 3),
                        )
                    )
            return gaps

        # 1. Leading silence check
        if start_bound is not None and (words[0].start - start_bound) > th:
            gaps.append(
                DeadAirGap(
                    start=round(start_bound, 3),
                    end=round(words[0].start, 3),
                    duration=round(words[0].start - start_bound, 3),
                )
            )

        # 2. Internal gaps between adjacent words
        for i in range(len(words) - 1):
            curr_w = words[i]
            next_w = words[i + 1]
            gap_duration = next_w.start - curr_w.end
            if gap_duration > th:
                gaps.append(
                    DeadAirGap(
                        start=round(curr_w.end, 3),
                        end=round(next_w.start, 3),
                        duration=round(gap_duration, 3),
                    )
                )

        # 3. Trailing silence check
        if end_bound is not None and (end_bound - words[-1].end) > th:
            gaps.append(
                DeadAirGap(
                    start=round(words[-1].end, 3),
                    end=round(end_bound, 3),
                    duration=round(end_bound - words[-1].end, 3),
                )
            )

        return gaps

    def detect_fillers(
        self,
        words: List[WordTimestamp],
    ) -> List[FillerOccurrence]:
        """
        Scans word sequence for standalone non-value filler tokens ('um', 'uh', 'so yeah', etc.).
        """
        fillers: List[FillerOccurrence] = []
        if not words:
            return fillers

        norm_words = [_normalize_word(w.word) for w in words]
        n = len(norm_words)
        visited_indices: Set[int] = set()

        # 1. Multi-word filler search
        for mw in self.multi_word_fillers:
            mw_len = len(mw)
            for i in range(n - mw_len + 1):
                if any(idx in visited_indices for idx in range(i, i + mw_len)):
                    continue
                if tuple(norm_words[i : i + mw_len]) == mw:
                    indices = list(range(i, i + mw_len))
                    visited_indices.update(indices)
                    fillers.append(
                        FillerOccurrence(
                            phrase=" ".join(words[idx].word for idx in indices),
                            start=round(words[i].start, 3),
                            end=round(words[i + mw_len - 1].end, 3),
                            word_indices=indices,
                        )
                    )

        # 2. Single-word standalone filler search
        for i, nw in enumerate(norm_words):
            if i in visited_indices:
                continue
            if nw in self.filler_words:
                visited_indices.add(i)
                fillers.append(
                    FillerOccurrence(
                        phrase=words[i].word,
                        start=round(words[i].start, 3),
                        end=round(words[i].end, 3),
                        word_indices=[i],
                    )
                )

        fillers.sort(key=lambda f: f.start)
        return fillers

    def detect_restarts(
        self,
        cues: List[TranscriptSegment],
        min_prefix_words: int = 3,
        max_prefix_words: int = 5,
    ) -> List[SentenceRestart]:
        """
        Detects false starts and retakes where the first 3-5 normalized words of
        consecutive cues match (norm(prev)[:k] == norm(curr)[:k]).
        """
        restarts: List[SentenceRestart] = []
        if len(cues) < 2:
            return restarts

        for i in range(len(cues) - 1):
            prev_cue = cues[i]
            curr_cue = cues[i + 1]

            prev_norm = [_normalize_word(w) for w in prev_cue.text.split() if _normalize_word(w)]
            curr_norm = [_normalize_word(w) for w in curr_cue.text.split() if _normalize_word(w)]

            # Check matching prefix length from max down to min
            max_check = min(max_prefix_words, len(prev_norm), len(curr_norm))
            if max_check < min_prefix_words:
                continue

            matching_k = 0
            for k in range(max_check, min_prefix_words - 1, -1):
                if prev_norm[:k] == curr_norm[:k]:
                    matching_k = k
                    break

            if matching_k >= min_prefix_words:
                restarts.append(
                    SentenceRestart(
                        prev_text=prev_cue.text,
                        curr_text=curr_cue.text,
                        matching_prefix=prev_norm[:matching_k],
                        prefix_length=matching_k,
                        prev_start=round(prev_cue.start, 3),
                        prev_end=round(prev_cue.end, 3),
                        curr_start=round(curr_cue.start, 3),
                        curr_end=round(curr_cue.end, 3),
                    )
                )

        return restarts

    def calculate_pacing_tightness_score(
        self,
        duration: float,
        dead_air_duration: float,
        filler_count: int,
        restart_count: int,
    ) -> float:
        """
        Calculates calibrated pacing tightness score (0.0 to 10.0).
        Penalizes dead air ratio, non-value filler frequency, and false starts.
        """
        if duration <= 0.0:
            return 5.0

        dead_air_ratio = min(dead_air_duration / max(duration, 0.1), 1.0)
        # Deductions
        dead_air_deduction = dead_air_ratio * 12.0
        filler_deduction = min(filler_count * 0.6, 3.5)
        restart_deduction = min(restart_count * 1.5, 3.0)

        raw_score = 10.0 - dead_air_deduction - filler_deduction - restart_deduction
        return round(max(0.0, min(10.0, raw_score)), 2)

    def prune_words(
        self,
        words: List[WordTimestamp],
        cues: Optional[List[TranscriptSegment]] = None,
        prune_fillers: bool = False,
        prune_restarts: bool = True,
        clip_start: Optional[float] = None,
        clip_end: Optional[float] = None,
    ) -> PruneResult:
        """
        Performs full deterministic analysis and constructs keep intervals for micro-jump-cuts.
        """
        if not words:
            return PruneResult(
                original_duration=0.0,
                pruned_duration=0.0,
                dead_air_duration=0.0,
                keep_intervals=[],
                pacing_tightness_score=5.0,
            )

        # Filter words to clip bounds if provided
        filtered_words = words
        if clip_start is not None or clip_end is not None:
            c_start = clip_start if clip_start is not None else 0.0
            c_end = clip_end if clip_end is not None else float("inf")
            filtered_words = [w for w in words if w.end >= c_start and w.start <= c_end]

        if not filtered_words:
            return PruneResult(
                original_duration=0.0,
                pruned_duration=0.0,
                dead_air_duration=0.0,
                keep_intervals=[],
                pacing_tightness_score=5.0,
            )

        orig_start = clip_start if clip_start is not None else filtered_words[0].start
        orig_end = clip_end if clip_end is not None else filtered_words[-1].end
        orig_duration = max(0.0, orig_end - orig_start)

        # 1. Detect dead-air gaps (> 0.35s) including leading and trailing silence
        gaps = self.detect_dead_air_gaps(
            filtered_words,
            start_bound=orig_start if clip_start is not None else None,
            end_bound=orig_end if clip_end is not None else None,
        )
        total_dead_air = sum(g.duration for g in gaps)

        # 2. Detect fillers
        fillers = self.detect_fillers(filtered_words)

        # 3. Detect restarts if cues provided or synthesize cues
        if cues is not None:
            # Filter cues to clip bounds so external cues cannot corrupt clip intervals
            valid_cues = [
                c for c in cues
                if c.end > orig_start and c.start < orig_end
            ]
            restarts = self.detect_restarts(valid_cues)
        else:
            # Group words into sentence-like cues by terminal punctuation or large gaps
            synthesized_cues = self._synthesize_cues_from_words(filtered_words)
            restarts = self.detect_restarts(synthesized_cues)

        # 4. Compute Pacing Tightness Score
        tightness = self.calculate_pacing_tightness_score(
            duration=orig_duration,
            dead_air_duration=total_dead_air,
            filler_count=len(fillers),
            restart_count=len(restarts),
        )

        # 5. Build Keep Intervals for Micro-Jump-Cuts
        keep_intervals = self._compute_keep_intervals(
            words=filtered_words,
            gaps=gaps,
            fillers=fillers if prune_fillers else [],
            restarts=restarts if prune_restarts else [],
            start_bound=orig_start,
            end_bound=orig_end,
        )

        pruned_duration = sum(e - s for s, e in keep_intervals)

        # 6. Extract pruned word sequence and text
        pruned_words = self._extract_kept_words(filtered_words, keep_intervals)
        pruned_text = " ".join(w.word for w in pruned_words)

        return PruneResult(
            original_duration=orig_duration,
            pruned_duration=pruned_duration,
            dead_air_duration=total_dead_air,
            dead_air_gaps=gaps,
            filler_occurrences=fillers,
            restarts=restarts,
            keep_intervals=keep_intervals,
            pacing_tightness_score=tightness,
            pruned_words=pruned_words,
            pruned_text=pruned_text,
        )

    def prune_candidate(
        self,
        candidate: HighlightCandidate,
        transcript: Transcript,
        prune_fillers: bool = False,
        prune_restarts: bool = True,
    ) -> PruneResult:
        """
        Runs dead-air and pacing analysis across a HighlightCandidate's timeframe.
        """
        all_words: List[WordTimestamp] = []
        matching_segments: List[TranscriptSegment] = []

        for seg in transcript.segments:
            if seg.end >= candidate.start_seconds and seg.start <= candidate.end_seconds:
                matching_segments.append(seg)
                if seg.words:
                    all_words.extend(seg.words)
                else:
                    # Synthesize word timestamps for this segment if words were absent
                    seg_words = seg.text.split()
                    if seg_words:
                        w_dur = (seg.end - seg.start) / len(seg_words)
                        for idx, w in enumerate(seg_words):
                            ws = seg.start + (idx * w_dur)
                            we = ws + w_dur
                            all_words.append(WordTimestamp(word=w, start=ws, end=we))

        return self.prune_words(
            words=all_words,
            cues=matching_segments,
            prune_fillers=prune_fillers,
            prune_restarts=prune_restarts,
            clip_start=candidate.start_seconds,
            clip_end=candidate.end_seconds,
        )

    def _synthesize_cues_from_words(self, words: List[WordTimestamp]) -> List[TranscriptSegment]:
        """Groups words into cue-level segments using punctuation and pauses."""
        cues: List[TranscriptSegment] = []
        if not words:
            return cues

        current_words: List[WordTimestamp] = []
        seg_id = 0

        for i, w in enumerate(words):
            current_words.append(w)
            is_terminal = any(w.word.endswith(punct) for punct in [".", "?", "!", ";"])
            is_pause = (i < len(words) - 1) and ((words[i + 1].start - w.end) > 0.4)

            if is_terminal or is_pause or len(current_words) >= 15:
                text = " ".join(cw.word for cw in current_words)
                cues.append(
                    TranscriptSegment(
                        segment_id=seg_id,
                        start=current_words[0].start,
                        end=current_words[-1].end,
                        text=text,
                        words=list(current_words),
                    )
                )
                seg_id += 1
                current_words = []

        if current_words:
            text = " ".join(cw.word for cw in current_words)
            cues.append(
                TranscriptSegment(
                    segment_id=seg_id,
                    start=current_words[0].start,
                    end=current_words[-1].end,
                    text=text,
                    words=list(current_words),
                )
            )

        return cues

    def _compute_keep_intervals(
        self,
        words: List[WordTimestamp],
        gaps: List[DeadAirGap],
        fillers: List[FillerOccurrence],
        restarts: List[SentenceRestart],
        start_bound: float,
        end_bound: float,
    ) -> List[Tuple[float, float]]:
        """
        Builds tightly trimmed keep intervals by cutting dead-air gaps (> 0.35s)
        and discarding false start retakes.
        """
        # Cut zones to remove: [(cut_start, cut_end), ...]
        cut_zones: List[Tuple[float, float]] = []

        # 1. Dead air cuts
        for g in gaps:
            # Leading silence cut: remove start_bound up to breath before first word
            if abs(g.start - start_bound) < 0.05 or g.start <= start_bound:
                cut_start = start_bound
                cut_end = max(start_bound, g.end - self.target_pause)
            # Trailing silence cut: remove after breath to end_bound
            elif abs(g.end - end_bound) < 0.05 or g.end >= end_bound:
                cut_start = g.start + self.target_pause
                cut_end = end_bound
            else:
                # Internal gap cut: compress gap to target_pause
                cut_start = g.start + self.target_pause
                cut_end = g.end

            if cut_end > cut_start + 0.01:
                cut_zones.append((cut_start, cut_end))

        # 2. Filler cuts if requested
        for f in fillers:
            cut_zones.append((f.start, f.end))

        # 3. Restart cuts (cut the false start / previous cue through retake start)
        for r in restarts:
            cut_end = max(r.prev_end, r.curr_start)
            cut_zones.append((r.prev_start, cut_end))

        # Clamp cut zones strictly within [start_bound, end_bound]
        valid_cuts: List[Tuple[float, float]] = []
        for c_start, c_end in cut_zones:
            if c_end <= start_bound or c_start >= end_bound:
                continue
            c_s = max(c_start, start_bound)
            c_e = min(c_end, end_bound)
            if c_e > c_s + 0.01:
                valid_cuts.append((c_s, c_e))

        if not valid_cuts:
            return [(round(start_bound, 3), round(end_bound, 3))]

        # Sort and merge overlapping cut zones
        valid_cuts.sort(key=lambda x: x[0])
        merged_cuts: List[Tuple[float, float]] = []
        for c_start, c_end in valid_cuts:
            if not merged_cuts:
                merged_cuts.append((c_start, c_end))
            else:
                last_start, last_end = merged_cuts[-1]
                if c_start <= last_end:
                    merged_cuts[-1] = (last_start, max(last_end, c_end))
                else:
                    merged_cuts.append((c_start, c_end))

        # Invert merged cut zones into keep intervals within [start_bound, end_bound]
        keep: List[Tuple[float, float]] = []
        cursor = start_bound

        for c_start, c_end in merged_cuts:
            if c_start > cursor + 0.05:  # Require at least 50ms interval
                keep.append((round(cursor, 3), round(c_start, 3)))
            cursor = max(cursor, c_end)

        if cursor + 0.05 < end_bound:
            keep.append((round(cursor, 3), round(end_bound, 3)))

        return keep if keep else [(round(start_bound, 3), round(end_bound, 3))]

    def _extract_kept_words(
        self,
        words: List[WordTimestamp],
        keep_intervals: List[Tuple[float, float]],
    ) -> List[WordTimestamp]:
        """Returns the words that fall inside any keep interval."""
        kept: List[WordTimestamp] = []
        for w in words:
            word_mid = (w.start + w.end) / 2.0
            if any(s <= word_mid <= e for s, e in keep_intervals):
                kept.append(w)
        return kept

    def generate_select_expressions(
        self,
        keep_intervals: List[Tuple[float, float]],
        offset_seconds: float = 0.0,
    ) -> Tuple[str, str]:
        """
        Returns (video_select_expr, audio_select_expr) with timestamps shifted by offset_seconds.
        """
        if not keep_intervals:
            return "", ""

        expr_terms = [
            f"between(t,{max(0.0, s - offset_seconds):.3f},{max(0.0, e - offset_seconds):.3f})"
            for s, e in keep_intervals
        ]
        combined_expr = "+".join(expr_terms)
        video_expr = f"select='{combined_expr}',setpts=N/FRAME_RATE/TB"
        audio_expr = f"aselect='{combined_expr}',asetpts=N/SR/TB"
        return video_expr, audio_expr

    def generate_ffmpeg_select_filter(
        self,
        keep_intervals: List[Tuple[float, float]],
        offset_seconds: float = 0.0,
        video_in_label: str = "0:v",
        video_out_label: str = "v_cut",
        audio_in_label: str = "0:a",
        audio_out_label: str = "a_cut",
    ) -> str:
        """
        Generates FFmpeg select filter expression for micro-jump-cuts.
        Example output:
        [0:v]select='between(t,1.2,4.5)+between(t,5.1,10.0)',setpts=N/FRAME_RATE/TB[v_cut];[0:a]aselect='between(t,1.2,4.5)+between(t,5.1,10.0)',asetpts=N/SR/TB[a_cut]
        """
        if not keep_intervals:
            return ""

        v_filter, a_filter = self.generate_select_expressions(keep_intervals, offset_seconds)
        return f"[{video_in_label}]{v_filter}[{video_out_label}];[{audio_in_label}]{a_filter}[{audio_out_label}]"
