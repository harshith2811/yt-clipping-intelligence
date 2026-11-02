"""
Forced-Alignment Subsystem for Sub-Second Word Timestamp Synchronization.
Provides abstract AlignmentEngine protocol, lightweight FasterWhisperAlignmentAdapter,
and phoneme-level WhisperXAlignmentAdapter with automated GPU/CPU/fallback cascades.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Union, Tuple
import os
import sys
import copy
import logging
import math
from dataclasses import replace

from ..contracts.models import Transcript, TranscriptSegment, WordTimestamp

logger = logging.getLogger(__name__)

# Polymorphic type contract: accepts either a strongly-typed Transcript or its dict representation
TranscriptData = Union[Transcript, Dict[str, Any]]


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Safely converts input value to a finite float, returning default on None, NaN, inf, or error."""
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default



class AlignmentEngine(ABC):
    """
    Abstract Base Class for word-level and phoneme-level forced-alignment engines.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Returns the unique identifier for the alignment engine."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Checks if the required underlying runtime dependencies and models are functional."""
        pass

    @abstractmethod
    def align_words(
        self,
        audio_path: str,
        transcript: TranscriptData,
        **kwargs: Any,
    ) -> TranscriptData:
        """
        Refines word-level timestamps in the transcript against the audio waveform.

        Args:
            audio_path: Path to the source audio or video media file.
            transcript: Input Transcript dataclass instance or dict representation.
            **kwargs: Additional runtime parameters (e.g. language override, device override).

        Returns:
            TranscriptData: Transcript instance or dict with refined, strictly monotonic word timestamps.
        """
        pass

    @staticmethod
    def _coerce_to_transcript(transcript: TranscriptData) -> Tuple[Transcript, bool]:
        """
        Coerces input TranscriptData into a Transcript dataclass instance.
        Returns (Transcript, is_dict_input).
        """
        if isinstance(transcript, dict):
            return Transcript.from_dict(transcript), True
        elif isinstance(transcript, Transcript):
            return copy.deepcopy(transcript), False
        else:
            raise TypeError(f"Unsupported transcript type: {type(transcript)}. Expected Transcript or dict.")

    @staticmethod
    def _restore_output_type(transcript: Transcript, was_dict_input: bool) -> TranscriptData:
        """Restores output to match the input format (dict or Transcript)."""
        if was_dict_input:
            return transcript.to_dict()
        return transcript


class FasterWhisperAlignmentAdapter(AlignmentEngine):
    """
    Lightweight, offline word alignment adapter.
    Sanitizes, clamps, and enforces strict monotonicity on faster-whisper word timestamps
    without requiring additional neural models or external dependencies.
    """

    def __init__(self, min_word_duration: float = 0.04):
        """
        Args:
            min_word_duration: Minimum duration in seconds for any single word (default 40ms).
        """
        self.min_word_duration = min_word_duration

    @property
    def name(self) -> str:
        return "faster-whisper"

    def is_available(self) -> bool:
        return True  # Always available; pure Python standard library

    def align_words(
        self,
        audio_path: str,
        transcript: TranscriptData,
        **kwargs: Any,
    ) -> TranscriptData:
        t_obj, was_dict = self._coerce_to_transcript(transcript)

        if not t_obj.segments:
            return self._restore_output_type(t_obj, was_dict)

        aligned_segments: List[TranscriptSegment] = []

        for seg in t_obj.segments:
            cleaned_words = self.sanitize_segment_words(seg)
            seg.words = cleaned_words
            aligned_segments.append(seg)

        t_obj.segments = aligned_segments
        if "aligned" not in t_obj.provider:
            t_obj.provider = f"{t_obj.provider}+faster-whisper-aligned"

        return self._restore_output_type(t_obj, was_dict)

    def sanitize_segment_words(self, seg: TranscriptSegment) -> List[WordTimestamp]:
        """
        Sanitizes word timestamps for a single segment:
        1. Synthesizes word timestamps if missing.
        2. Sorts words by start timestamp.
        3. Clamps start and end times to segment bounds.
        4. Inverts reversed bounds (start > end).
        5. Enforces minimum word duration.
        6. Resolves word overlaps.
        7. Preserves speaker tags and confidence scores.
        """
        seg_start = round(_safe_float(getattr(seg, "start", 0.0) if not isinstance(seg, dict) else seg.get("start", 0.0), 0.0), 2)
        seg_end = round(_safe_float(getattr(seg, "end", 0.0) if not isinstance(seg, dict) else seg.get("end", 0.0), 0.0), 2)
        if seg_end <= seg_start:
            seg_end = round(seg_start + 0.1, 2)

        seg_words = seg.get("words") if isinstance(seg, dict) else getattr(seg, "words", None)
        seg_speaker = seg.get("speaker_tag") if isinstance(seg, dict) else getattr(seg, "speaker_tag", None)

        # Case A: Missing words -> synthesize proportional timestamps
        if not seg_words:
            raw_text = (seg.get("text") if isinstance(seg, dict) else getattr(seg, "text", "")) or ""
            raw_words = raw_text.strip().split()
            if not raw_words:
                return []
            total_chars = sum(max(len(w), 1) for w in raw_words)
            duration = max(seg_end - seg_start, 0.1)
            time_per_char = duration / max(total_chars, 1)

            synthesized: List[WordTimestamp] = []
            cur_time = seg_start
            for idx, w in enumerate(raw_words):
                w_dur = max(len(w) * time_per_char, self.min_word_duration)
                w_start = round(cur_time, 2)
                w_end = round(min(cur_time + w_dur, seg_end), 2)
                if idx == len(raw_words) - 1:
                    w_end = max(seg_end, round(w_start + self.min_word_duration, 2))
                if w_end <= w_start:
                    w_end = round(w_start + self.min_word_duration, 2)

                synthesized.append(
                    WordTimestamp(
                        word=w,
                        start=w_start,
                        end=w_end,
                        confidence=0.85,
                        speaker_tag=seg_speaker,
                    )
                )
                cur_time = w_end
            return synthesized

        # Case B: Words present -> sanitize and resolve
        sorted_words = sorted(
            seg_words,
            key=lambda w: _safe_float(w.get("start") if isinstance(w, dict) else getattr(w, "start", 0.0), 0.0)
        )
        sanitized: List[WordTimestamp] = []
        last_end = seg_start

        for idx, w in enumerate(sorted_words):
            word_str = (w.get("word") if isinstance(w, dict) else getattr(w, "word", "") or "").strip()
            raw_start = w.get("start") if isinstance(w, dict) else getattr(w, "start", 0.0)
            raw_end = w.get("end") if isinstance(w, dict) else getattr(w, "end", 0.0)

            w_start = round(_safe_float(raw_start, 0.0), 2)
            w_end = round(_safe_float(raw_end, w_start + self.min_word_duration), 2)

            # Inversion fix
            if w_end < w_start:
                w_start, w_end = w_end, w_start

            # Enforce minimum duration
            if (w_end - w_start) < self.min_word_duration:
                w_end = round(w_start + self.min_word_duration, 2)

            # Clamp to segment bounds
            w_start = max(w_start, seg_start)
            w_end = min(w_end, seg_end)
            if w_end <= w_start:
                w_end = min(round(w_start + self.min_word_duration, 2), max(seg_end, round(w_start + self.min_word_duration, 2)))

            # Overlap resolution: ensure monotonic progress
            if w_start < last_end:
                w_start = last_end
                if w_end <= w_start:
                    w_end = round(w_start + self.min_word_duration, 2)

            last_end = w_end

            raw_conf = w.get("confidence") if isinstance(w, dict) else getattr(w, "confidence", 0.9)
            raw_speaker = w.get("speaker_tag") if isinstance(w, dict) else getattr(w, "speaker_tag", None)

            sanitized.append(
                WordTimestamp(
                    word=word_str,
                    start=w_start,
                    end=w_end,
                    confidence=round(_safe_float(raw_conf, 0.9), 2),
                    speaker_tag=raw_speaker or seg_speaker,
                )
            )

        return sanitized


class WhisperXAlignmentAdapter(AlignmentEngine):
    """
    Phoneme-level forced-alignment adapter using WhisperX / wav2vec2.
    Features automated GPU -> CPU cascade fallback, VRAM safety thresholding,
    and graceful degradation to FasterWhisperAlignmentAdapter.
    """

    def __init__(
        self,
        device: str = "auto",
        model_name: Optional[str] = None,
        model_dir: Optional[str] = None,
        vram_safety_threshold_mb: float = 1024.0,
        max_chunk_duration_seconds: float = 300.0,
    ):
        self.device = device
        self.model_name = model_name
        self.model_dir = model_dir
        self.vram_safety_threshold_mb = vram_safety_threshold_mb
        self.max_chunk_duration_seconds = max_chunk_duration_seconds
        self._fallback = FasterWhisperAlignmentAdapter()

    @property
    def name(self) -> str:
        return "whisperx"

    def is_available(self) -> bool:
        """Checks if whisperx library is importable."""
        try:
            import whisperx
            return True
        except ImportError:
            return False

    def _determine_execution_device(self) -> str:
        """
        Determines whether to execute on CUDA or CPU based on device preference
        and free VRAM safety thresholds.
        """
        if self.device == "cpu":
            return "cpu"

        try:
            import torch
            if not torch.cuda.is_available():
                return "cpu"

            if self.device in ("auto", "cuda"):
                free_bytes, total_bytes = torch.cuda.mem_get_info(0)
                free_mb = free_bytes / (1024 * 1024)
                if free_mb < self.vram_safety_threshold_mb:
                    logger.warning(
                        f"[WhisperXAlignmentAdapter] Free VRAM ({free_mb:.1f} MB) is below safety "
                        f"threshold ({self.vram_safety_threshold_mb} MB). Diverting to CPU."
                    )
                    return "cpu"
                return "cuda"
        except Exception as e:
            logger.debug(f"[WhisperXAlignmentAdapter] Hardware check exception: {e}. Defaulting to CPU.")
            return "cpu"

        return "cpu"

    def align_words(
        self,
        audio_path: str,
        transcript: TranscriptData,
        **kwargs: Any,
    ) -> TranscriptData:
        t_obj, was_dict = self._coerce_to_transcript(transcript)

        # Validation: Audio file existence & non-empty transcript
        if not audio_path or not os.path.exists(audio_path) or not t_obj.segments:
            logger.info("[WhisperXAlignmentAdapter] Audio file missing or transcript empty. Using fallback.")
            return self._fallback.align_words(audio_path, transcript, **kwargs)

        # Check whisperx availability
        if not self.is_available():
            logger.info(
                "[WhisperXAlignmentAdapter] whisperx package not installed. "
                "Degrading gracefully to FasterWhisperAlignmentAdapter."
            )
            return self._fallback.align_words(audio_path, transcript, **kwargs)

        target_device = self._determine_execution_device()
        language_code = getattr(t_obj, "language", "en") or "en"

        # Attempt primary alignment on target_device
        aligned_transcript = self._try_whisperx_align(audio_path, t_obj, target_device, language_code)
        if aligned_transcript is not None:
            return self._restore_output_type(aligned_transcript, was_dict)

        # Cascade 1: If CUDA was attempted and failed, retry on CPU
        if target_device == "cuda":
            logger.warning("[WhisperXAlignmentAdapter] CUDA alignment failed. Retrying on CPU cascade.")
            aligned_transcript = self._try_whisperx_align(audio_path, t_obj, "cpu", language_code)
            if aligned_transcript is not None:
                return self._restore_output_type(aligned_transcript, was_dict)

        # Cascade 2: Degradation to FasterWhisperAlignmentAdapter
        logger.warning(
            "[WhisperXAlignmentAdapter] WhisperX alignment failed across all execution targets. "
            "Falling back to FasterWhisperAlignmentAdapter."
        )
        return self._fallback.align_words(audio_path, transcript, **kwargs)

    def _try_whisperx_align(
        self,
        audio_path: str,
        transcript: Transcript,
        device: str,
        language_code: str,
    ) -> Optional[Transcript]:
        """Attempts WhisperX alignment under specified device target."""
        try:
            import whisperx
            import torch
            import gc

            # 1. Load audio
            audio = whisperx.load_audio(audio_path)

            # 2. Format segments for whisperx
            wx_segments = []
            for seg in transcript.segments:
                wx_segments.append({
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text,
                    "words": [{"word": w.word, "start": w.start, "end": w.end} for w in seg.words],
                })

            # 3. Load alignment model
            align_model, align_metadata = whisperx.load_align_model(
                language_code=language_code,
                device=device,
                model_name=self.model_name,
                model_dir=self.model_dir,
            )

            # 4. Perform alignment
            result = whisperx.align(
                wx_segments,
                align_model,
                align_metadata,
                audio,
                device,
                return_char_alignments=False,
            )

            # 5. Unload alignment model & free memory
            del align_model
            if device == "cuda" and torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

            # 6. Map results back to Transcript dataclasses
            refined_segments: List[TranscriptSegment] = []
            for idx, res_seg in enumerate(result.get("segments", [])):
                original_seg = transcript.segments[idx] if idx < len(transcript.segments) else None
                seg_id = original_seg.segment_id if original_seg else (idx + 1)
                speaker_tag = original_seg.speaker_tag if original_seg else None

                words_list: List[WordTimestamp] = []
                for w_data in res_seg.get("words", []):
                    w_text = w_data.get("word", "").strip()
                    w_start = w_data.get("start")
                    w_end = w_data.get("end")
                    score = w_data.get("score", 0.95)

                    # Repair unaligned words with missing/NaN bounds
                    if w_start is None or math.isnan(w_start) or w_end is None or math.isnan(w_end):
                        continue

                    words_list.append(
                        WordTimestamp(
                            word=w_text,
                            start=round(float(w_start), 2),
                            end=round(float(w_end), 2),
                            confidence=round(float(score), 2),
                            speaker_tag=speaker_tag,
                        )
                    )

                new_seg = TranscriptSegment(
                    segment_id=seg_id,
                    start=round(float(res_seg.get("start", original_seg.start if original_seg else 0.0)), 2),
                    end=round(float(res_seg.get("end", original_seg.end if original_seg else 0.0)), 2),
                    text=res_seg.get("text", original_seg.text if original_seg else "").strip(),
                    words=words_list,
                    speaker_tag=speaker_tag,
                )
                # Sanitize word timestamps to guarantee monotonicity
                new_seg.words = self._fallback.sanitize_segment_words(new_seg)
                refined_segments.append(new_seg)

            transcript_copy = copy.deepcopy(transcript)
            transcript_copy.segments = refined_segments
            transcript_copy.provider = f"whisperx-aligned-{device}"
            return transcript_copy

        except Exception as e:
            logger.warning(f"[WhisperXAlignmentAdapter] Execution failed on {device}: {e}")
            try:
                import gc
                gc.collect()
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
            return None


def get_alignment_engine(
    config: Optional[Union[Any, Dict[str, Any], str]] = None,
    **kwargs: Any,
) -> AlignmentEngine:
    """
    Factory function resolving and returning the appropriate AlignmentEngine.

    Resolution:
    - "faster-whisper": FasterWhisperAlignmentAdapter (offline, lightweight).
    - "whisperx": WhisperXAlignmentAdapter (phoneme-level forced alignment with fallback).
    - "auto" (default): Checks WhisperX availability; if available returns WhisperXAlignmentAdapter,
                        otherwise returns FasterWhisperAlignmentAdapter.
    """
    raw_engine: Any = kwargs.pop("engine", kwargs.pop("alignment_engine", "auto"))
    device = kwargs.pop("device", "auto")
    model_name = kwargs.pop("model_name", None)

    # Extract settings from config object or dict
    if config is not None:
        if isinstance(config, str):
            raw_engine = config
        elif isinstance(config, dict):
            raw_engine = config.get("alignment_engine")
            if raw_engine is None:
                raw_engine = config.get("transcription_provider", "auto")
            device = config.get("alignment_device", config.get("transcription_device", device))
            model_name = config.get("alignment_model_name", model_name)
        elif hasattr(config, "alignment_engine") or hasattr(config, "transcription_provider"):
            raw_engine = getattr(config, "alignment_engine", None)
            if raw_engine is None:
                raw_engine = getattr(config, "transcription_provider", "auto")
            device = getattr(config, "alignment_device", getattr(config, "transcription_device", device))
            model_name = getattr(config, "alignment_model_name", model_name)
        else:
            raw_engine = config

    # Safe string normalization
    if raw_engine is None:
        engine_type = "auto"
    elif isinstance(raw_engine, str):
        engine_type = raw_engine.lower().strip()
    else:
        try:
            engine_type = str(raw_engine).lower().strip()
        except Exception:
            engine_type = "auto"

    # Normalization
    if engine_type in ("faster-whisper", "faster_whisper", "offline", "builtin"):
        return FasterWhisperAlignmentAdapter(**kwargs)

    if engine_type == "whisperx":
        return WhisperXAlignmentAdapter(device=device, model_name=model_name, **kwargs)

    # "auto" resolution
    wx_adapter = WhisperXAlignmentAdapter(device=device, model_name=model_name, **kwargs)
    if wx_adapter.is_available():
        return wx_adapter
    return FasterWhisperAlignmentAdapter(**kwargs)
