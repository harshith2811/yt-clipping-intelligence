"""
Audio Speaker Diarization Subsystem for Podcast & Multi-Speaker Video.
Provides:
- SpeakerTurn dataclass.
- SpeakerDiarizer ABC and word attribution helper.
- AcousticEnergyDiarizer: pure Python / NumPy / FFmpeg / SciPy offline diarizer (0MB VRAM).
- PyannoteDiarizerAdapter: neural diarizer with automated acoustic fallback.
- get_speaker_diarizer: factory function.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
import dataclasses
import logging
import os
import shutil
import subprocess
import sys
from typing import List, Optional, Tuple, Dict, Any
import numpy as np

from ..contracts.models import WordTimestamp

logger = logging.getLogger(__name__)


def _get_ffmpeg_path() -> str:
    """Locates ffmpeg executable in environment or system PATH."""
    env_bin = os.environ.get("FFMPEG_BINARY")
    if env_bin and os.path.exists(env_bin):
        return env_bin
    scripts_dir = os.path.join(os.path.dirname(sys.executable), "Scripts")
    py_ffmpeg = os.path.join(scripts_dir, "ffmpeg.exe")
    if os.path.exists(py_ffmpeg):
        return py_ffmpeg
    return shutil.which("ffmpeg") or "ffmpeg"


@dataclass(frozen=True)
class SpeakerTurn:
    """Represents an attributed speech turn within an audio/video interval."""
    speaker_id: str
    start: float
    end: float
    confidence: float = 1.0

    def __post_init__(self):
        if self.start < 0.0:
            raise ValueError(f"Turn start ({self.start}) cannot be negative.")
        if self.end < self.start:
            raise ValueError(f"Turn end ({self.end}) cannot precede start ({self.start}).")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Turn confidence ({self.confidence}) must be in [0.0, 1.0].")

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def overlap_seconds(self, start_time: float, end_time: float) -> float:
        return max(0.0, min(self.end, end_time) - max(self.start, start_time))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "speaker_id": self.speaker_id,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration": round(self.duration, 3),
            "confidence": round(self.confidence, 3),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SpeakerTurn:
        return cls(
            speaker_id=str(data["speaker_id"]),
            start=float(data["start"]),
            end=float(data["end"]),
            confidence=float(data.get("confidence", 1.0)),
        )


class SpeakerDiarizer(ABC):
    """Abstract base class for speaker diarization engines."""

    @abstractmethod
    def diarize(
        self,
        audio_path: str,
        num_speakers: Optional[int] = None,
        min_turn_duration: float = 0.4
    ) -> List[SpeakerTurn]:
        pass

    @classmethod
    def attribute_words_to_speakers(
        cls,
        turns: List[SpeakerTurn],
        words: List[WordTimestamp],
        default_speaker: str = "SPEAKER_00",
        gap_tolerance_seconds: float = 0.8
    ) -> List[WordTimestamp]:
        if not words:
            return []
        if not turns:
            return [
                dataclasses.replace(w, speaker_tag=default_speaker)
                if w.speaker_tag is None else w
                for w in words
            ]

        sorted_turns = sorted(turns, key=lambda t: t.start)
        attributed: List[WordTimestamp] = []

        for w in words:
            best_speaker: Optional[str] = None
            max_overlap = 0.0

            for turn in sorted_turns:
                if turn.start > w.end + 2.0:
                    break
                overlap = turn.overlap_seconds(w.start, w.end)
                if overlap > max_overlap:
                    max_overlap = overlap
                    best_speaker = turn.speaker_id

            if best_speaker is None or max_overlap <= 0.0:
                min_dist = float("inf")
                nearest_spk = None
                for turn in sorted_turns:
                    dist = turn.start - w.end if w.end < turn.start else (w.start - turn.end if w.start > turn.end else 0.0)
                    if dist < min_dist:
                        min_dist = dist
                        nearest_spk = turn.speaker_id

                best_speaker = nearest_spk if (nearest_spk and min_dist <= gap_tolerance_seconds) else default_speaker

            attributed.append(dataclasses.replace(w, speaker_tag=best_speaker))

        return attributed


class AcousticEnergyDiarizer(SpeakerDiarizer):
    """
    Pure Python / NumPy / SciPy / FFmpeg offline speaker diarizer.
    Requires 0MB VRAM, zero cloud accounts, and zero Hugging Face tokens.
    """

    def __init__(self, sample_rate: int = 16000, ffmpeg_bin: Optional[str] = None):
        self.sample_rate = sample_rate
        self.ffmpeg_bin = ffmpeg_bin or _get_ffmpeg_path()

    def _extract_pcm(self, audio_path: str) -> Optional[Tuple[np.ndarray, int]]:
        """Extracts 16kHz PCM audio via FFmpeg pipe as (samples, channels)."""
        if not audio_path or not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
            return None
        cmd = [
            self.ffmpeg_bin, "-y", "-v", "error",
            "-i", audio_path,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", str(self.sample_rate),
            "-ac", "2",
            "-f", "s16le",
            "pipe:1"
        ]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
            if proc.returncode == 0 and len(proc.stdout) > 0:
                raw = proc.stdout
                if len(raw) % 4 != 0:
                    raw = raw[:len(raw) - (len(raw) % 4)]
                stereo = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                stereo = stereo.reshape((-1, 2))
                return stereo, 2
        except Exception as exc:
            logger.debug("Stereo extraction failed: %s; trying mono", exc)

        # Mono fallback
        cmd[12] = "1"
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
            if proc.returncode == 0 and len(proc.stdout) > 0:
                raw = proc.stdout
                if len(raw) % 2 != 0:
                    raw = raw[:len(raw) - 1]
                mono = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                return mono.reshape((-1, 1)), 1
        except Exception:
            return None
        return None

    def diarize(
        self,
        audio_path: str,
        num_speakers: Optional[int] = None,
        min_turn_duration: float = 0.4
    ) -> List[SpeakerTurn]:
        extracted = self._extract_pcm(audio_path)
        if extracted is None:
            return []

        audio, n_channels = extracted
        n_samples = audio.shape[0]
        total_dur = n_samples / self.sample_rate
        if total_dur < 0.2:
            return []

        mono = np.mean(audio, axis=1)

        # Handle complete silence edge-case
        if np.all(np.abs(mono) < 1e-5):
            return [SpeakerTurn("SPEAKER_00", 0.0, round(total_dur, 3), 0.5)]

        # 1. Short-Time Framing
        frame_len = int(0.030 * self.sample_rate)  # 30 ms
        hop_len = int(0.010 * self.sample_rate)    # 10 ms
        n_frames = (n_samples - frame_len) // hop_len + 1
        if n_frames < 5:
            return [SpeakerTurn("SPEAKER_00", 0.0, round(total_dur, 3), 0.9)]

        frames = np.lib.stride_tricks.as_strided(
            mono,
            shape=(n_frames, frame_len),
            strides=(mono.strides[0] * hop_len, mono.strides[0])
        )

        # 2. VAD: RMS & Dynamic Thresholding
        rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
        dbfs = 20 * np.log10(rms + 1e-9)
        floor_db = float(np.min(dbfs))
        peak_db = float(np.max(dbfs))
        vad_thresh = max(floor_db + 12.0, peak_db - 32.0, -45.0)
        is_speech = dbfs > vad_thresh

        # Hangover smoothing: close small gaps < 250ms (25 frames)
        smoothed_speech = is_speech.copy()
        gap_limit = 25
        gap_count = 0
        for i in range(len(smoothed_speech)):
            if not smoothed_speech[i]:
                gap_count += 1
            else:
                if 0 < gap_count <= gap_limit:
                    smoothed_speech[i - gap_count : i] = True
                gap_count = 0

        speech_indices = np.where(smoothed_speech)[0]
        if len(speech_indices) == 0:
            return [SpeakerTurn("SPEAKER_00", 0.0, round(total_dur, 3), 0.5)]

        # 3. Acoustic Feature Extraction per Window (0.5s chunks)
        window_func = np.hanning(frame_len)
        spec = np.abs(np.fft.rfft(frames * window_func, axis=1))
        freqs = np.fft.rfftfreq(frame_len, d=1.0 / self.sample_rate)

        # Spectral Centroid
        centroids = np.sum(spec * freqs, axis=1) / (np.sum(spec, axis=1) + 1e-12)

        # Zero Crossing Rate
        zcr = np.mean(np.abs(np.diff(np.sign(frames), axis=1)) > 0, axis=1)

        # Sub-band Energy Ratio: Low (80-350Hz) / Mid (350-2500Hz)
        low_mask = (freqs >= 80) & (freqs < 350)
        mid_mask = (freqs >= 350) & (freqs < 2500)
        low_eng = np.sum(spec[:, low_mask], axis=1) + 1e-9
        mid_eng = np.sum(spec[:, mid_mask], axis=1) + 1e-9
        band_ratio = low_eng / mid_eng

        # Stereo Panning (if stereo)
        panning = np.zeros(n_frames, dtype=np.float32)
        if n_channels == 2:
            l_frames = np.lib.stride_tricks.as_strided(audio[:, 0], shape=(n_frames, frame_len), strides=(audio.strides[0] * hop_len, audio.strides[0]))
            r_frames = np.lib.stride_tricks.as_strided(audio[:, 1], shape=(n_frames, frame_len), strides=(audio.strides[0] * hop_len, audio.strides[0]))
            l_rms = np.sqrt(np.mean(l_frames ** 2, axis=1) + 1e-12)
            r_rms = np.sqrt(np.mean(r_frames ** 2, axis=1) + 1e-12)
            panning = (l_rms - r_rms) / (l_rms + r_rms + 1e-6)

        # Group speech frames into contiguous analysis chunks (~0.5s = 50 frames)
        chunk_len_frames = 50
        feature_list = []
        chunk_intervals = []

        # Find contiguous speech segments
        diff = np.diff(speech_indices)
        split_points = np.where(diff > 1)[0] + 1
        speech_segments = np.split(speech_indices, split_points)

        for seg in speech_segments:
            if len(seg) < 5:
                continue
            for k_idx in range(0, len(seg), chunk_len_frames):
                sub = seg[k_idx : k_idx + chunk_len_frames]
                if len(sub) < 5:
                    continue
                c_mean = float(np.mean(centroids[sub]))
                z_mean = float(np.mean(zcr[sub]))
                b_mean = float(np.mean(band_ratio[sub]))
                p_mean = float(np.mean(panning[sub]))
                feature_list.append([c_mean, z_mean, b_mean, p_mean])
                t_start = sub[0] * hop_len / self.sample_rate
                t_end = (sub[-1] + 1) * hop_len / self.sample_rate
                chunk_intervals.append((t_start, t_end))

        if not feature_list:
            return [SpeakerTurn("SPEAKER_00", 0.0, round(total_dur, 3), 0.7)]

        X = np.array(feature_list)
        k = num_speakers if num_speakers is not None else 2
        k = max(1, min(k, len(feature_list)))

        if k == 1 or len(feature_list) < 2:
            labels = np.zeros(len(feature_list), dtype=int)
        else:
            # Z-score normalization
            std_dev = np.std(X, axis=0)
            std_dev[std_dev == 0] = 1.0
            X_norm = (X - np.mean(X, axis=0)) / (std_dev + 1e-6)
            try:
                from sklearn.cluster import KMeans
                km = KMeans(n_clusters=k, random_state=42, n_init=10).fit(X_norm)
                labels = km.labels_
            except Exception:
                # Built-in pure NumPy KMeans fallback
                labels = self._numpy_kmeans(X_norm, k)

        # 4. Turn Synthesis & Merging
        raw_turns: List[Tuple[int, float, float]] = []
        for (t_start, t_end), label in zip(chunk_intervals, labels):
            if raw_turns and raw_turns[-1][0] == label and abs(t_start - raw_turns[-1][2]) < 0.35:
                raw_turns[-1] = (label, raw_turns[-1][1], t_end)
            else:
                raw_turns.append((label, t_start, t_end))

        # Enforce min_turn_duration smoothing with temporal adjacency check
        final_turns: List[SpeakerTurn] = []
        for i, (spk_idx, s_start, s_end) in enumerate(raw_turns):
            dur = s_end - s_start
            if dur < min_turn_duration and final_turns and (s_start - final_turns[-1].end) <= 0.8:
                # Merge into previous turn only if temporally adjacent (pause <= 0.8s)
                prev = final_turns[-1]
                final_turns[-1] = SpeakerTurn(
                    prev.speaker_id,
                    prev.start,
                    round(max(prev.end, s_end), 3),
                    prev.confidence,
                )
            else:
                spk_id = f"SPEAKER_{spk_idx:02d}"
                final_turns.append(SpeakerTurn(spk_id, round(s_start, 3), round(s_end, 3), 0.90))

        return final_turns if final_turns else [SpeakerTurn("SPEAKER_00", 0.0, round(total_dur, 3), 0.8)]

    @staticmethod
    def _numpy_kmeans(
        X: np.ndarray,
        k: int,
        max_iter: int = 50,
        random_state: int = 42,
    ) -> np.ndarray:
        """Pure NumPy K-Means implementation with isolated random state and zero external dependencies."""
        n_samples = X.shape[0]
        if n_samples <= k:
            return np.arange(n_samples, dtype=int)
        rng = np.random.RandomState(random_state)
        indices = np.linspace(0, n_samples - 1, k, dtype=int)
        centroids = X[indices].copy()
        labels = np.zeros(n_samples, dtype=int)

        for _ in range(max_iter):
            dists = np.sum((X[:, np.newaxis, :] - centroids[np.newaxis, :, :]) ** 2, axis=2)
            new_labels = np.argmin(dists, axis=1)
            if np.array_equal(labels, new_labels):
                break
            labels = new_labels
            for j in range(k):
                mask = labels == j
                if np.any(mask):
                    centroids[j] = np.mean(X[mask], axis=0)

        return labels


class PyannoteDiarizerAdapter(SpeakerDiarizer):
    """
    Neural speaker diarizer adapter utilizing pyannote.audio.
    Falls back gracefully to AcousticEnergyDiarizer on missing package,
    missing token, CUDA OOM, or runtime exceptions.
    """

    def __init__(
        self,
        hf_token: Optional[str] = None,
        model_name: str = "pyannote/speaker-diarization-3.1",
        device: str = "auto",
        fallback_diarizer: Optional[SpeakerDiarizer] = None,
    ):
        self.hf_token = hf_token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
        self.model_name = model_name
        self.requested_device = device
        self.fallback_diarizer = fallback_diarizer or AcousticEnergyDiarizer()
        self._pipeline = None
        self._load_attempted = False

    def _get_device(self) -> str:
        if self.requested_device in ("cpu", "cuda"):
            return self.requested_device
        # Check CUDA and VRAM headroom
        try:
            import torch
            if torch.cuda.is_available():
                free_mb = torch.cuda.mem_get_info()[0] / (1024 ** 2)
                if free_mb >= 1500.0:
                    return "cuda"
        except Exception:
            pass
        return "cpu"

    def _load_pipeline(self):
        if self._load_attempted:
            return self._pipeline
        self._load_attempted = True

        if not self.hf_token:
            logger.info("HF_TOKEN not set; using AcousticEnergyDiarizer fallback.")
            return None

        try:
            import torch
            from pyannote.audio import Pipeline
            target_device = self._get_device()
            try:
                pipeline = Pipeline.from_pretrained(self.model_name, token=self.hf_token)
            except TypeError:
                pipeline = Pipeline.from_pretrained(self.model_name, use_auth_token=self.hf_token)

            if pipeline is not None and target_device == "cuda":
                pipeline.to(torch.device("cuda"))
            self._pipeline = pipeline
            return self._pipeline
        except ImportError:
            logger.info("pyannote.audio not installed; using AcousticEnergyDiarizer.")
            return None
        except Exception as exc:
            logger.warning("Failed to initialize pyannote pipeline: %s; falling back.", exc)
            return None

    def diarize(
        self,
        audio_path: str,
        num_speakers: Optional[int] = None,
        min_turn_duration: float = 0.4
    ) -> List[SpeakerTurn]:
        pipeline = self._load_pipeline()
        if pipeline is None:
            return self.fallback_diarizer.diarize(audio_path, num_speakers, min_turn_duration)

        try:
            diarization = pipeline(audio_path, num_speakers=num_speakers)
            turns: List[SpeakerTurn] = []
            for turn, _, speaker_label in diarization.itertracks(yield_label=True):
                turns.append(SpeakerTurn(
                    speaker_id=str(speaker_label),
                    start=round(turn.start, 3),
                    end=round(turn.end, 3),
                    confidence=0.95
                ))
            return turns if turns else self.fallback_diarizer.diarize(audio_path, num_speakers, min_turn_duration)
        except Exception as exc:
            logger.warning("Neural diarization failed at runtime: %s; using fallback.", exc)
            return self.fallback_diarizer.diarize(audio_path, num_speakers, min_turn_duration)


def get_speaker_diarizer(
    config: Optional[Any] = None,
    prefer_neural: bool = False,
    hf_token: Optional[str] = None,
    **kwargs: Any,
) -> SpeakerDiarizer:
    """
    Factory function returning the configured SpeakerDiarizer.
    Safely coerces config values and string flags without raising AttributeError.
    """
    should_use_neural = False

    # 1. Resolve prefer_neural flag safely
    if isinstance(prefer_neural, str):
        should_use_neural = prefer_neural.lower().strip() in ("true", "1", "yes")
    elif isinstance(prefer_neural, (bool, int)):
        should_use_neural = bool(prefer_neural)

    # 2. Check environment variable safely
    env_neural = os.environ.get("USE_PYANNOTE_DIARIZATION", "").lower().strip()
    if env_neural in ("1", "true", "yes"):
        should_use_neural = True

    # 3. Extract and safely coerce config settings
    engine_val = None
    if config is not None:
        if isinstance(config, str):
            engine_val = config
        elif isinstance(config, dict):
            for key in ("diarization_engine", "diarizer", "speaker_diarizer"):
                if key in config and config[key] is not None:
                    engine_val = config[key]
                    break
            flag_val = config.get("use_neural_diarizer")
            if flag_val is not None:
                if isinstance(flag_val, str):
                    should_use_neural = flag_val.lower().strip() in ("true", "1", "yes")
                elif isinstance(flag_val, (bool, int)):
                    should_use_neural = bool(flag_val)
            if hf_token is None:
                hf_token = config.get("hf_token", config.get("huggingface_token"))
        else:
            for attr in ("diarization_engine", "diarizer", "speaker_diarizer"):
                val = getattr(config, attr, None)
                if val is not None:
                    engine_val = val
                    break
            flag_val = getattr(config, "use_neural_diarizer", None)
            if flag_val is not None:
                if isinstance(flag_val, str):
                    should_use_neural = flag_val.lower().strip() in ("true", "1", "yes")
                elif isinstance(flag_val, (bool, int)):
                    should_use_neural = bool(flag_val)
            if hf_token is None:
                hf_token = getattr(config, "hf_token", getattr(config, "huggingface_token", None))

    # 4. Normalize engine_val safely with str coercion
    if engine_val is not None:
        try:
            engine_str = str(engine_val).lower().strip()
            if engine_str in ("pyannote", "neural", "gpu"):
                should_use_neural = True
            elif engine_str in ("acoustic", "energy", "offline", "cpu", "local"):
                should_use_neural = False
        except Exception:
            pass

    sample_rate = kwargs.pop("sample_rate", 16000)
    ffmpeg_bin = kwargs.pop("ffmpeg_bin", None)
    acoustic = AcousticEnergyDiarizer(sample_rate=sample_rate, ffmpeg_bin=ffmpeg_bin)
    if should_use_neural:
        return PyannoteDiarizerAdapter(hf_token=hf_token, fallback_diarizer=acoustic, **kwargs)
    return acoustic
