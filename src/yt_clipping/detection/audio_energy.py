"""
Continuous Acoustic Energy, Visual Motion Dynamics, and Adaptive Cadence Profiling.
Implements Phase 1 and Phase 2 of the Generalized Adaptive Architecture:
- Sub-second memory-piped FFmpeg 16kHz PCM audio extraction.
- Short-time RMS energy E(t) in dBFS, baseline mean mu_E, standard deviation sigma_E, dynamic range DR_E = p90 - p10.
- Normalized energy Z_E(t) and transition contrast Delta Z_E(t).
- Non-linear sigmoid audio scoring mapping to [0.0, 10.0] with graceful fallback.
- Downscaled 1fps inter-frame motion energy analyzer.
- Video-relative speaking rate deviation Z_R, fluency baseline F_fluency, and modulation dynamic M_dynamic.
"""

from typing import List, Optional, Tuple, Any
import os
import math
import subprocess
import statistics
import numpy as np

from ..contracts.models import Transcript, HighlightCandidate, WordTimestamp, TranscriptSegment


def extract_pcm_from_file(media_path: str, sample_rate: int = 16000) -> Optional[bytes]:
    """
    Fast sub-second extraction of 16kHz mono 16-bit PCM audio via FFmpeg memory pipe.
    Returns raw bytes if successful, or None on failure or missing file.
    """
    if not media_path or not os.path.exists(media_path) or os.path.getsize(media_path) == 0:
        return None

    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", media_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", str(sample_rate),
        "-ac", "1",
        "-f", "s16le",
        "pipe:1"
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        if proc.returncode == 0 and len(proc.stdout) > 0:
            raw_pcm = proc.stdout
            if len(raw_pcm) % 2 != 0:
                raw_pcm = raw_pcm[:len(raw_pcm) - 1]
            return raw_pcm if len(raw_pcm) > 0 else None
        return None
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None


def extract_motion_frames_from_file(
    video_path: str, fps: int = 1, width: int = 160, height: int = 90
) -> Optional[np.ndarray]:
    """
    Extracts downscaled 1fps grayscale frames via FFmpeg memory pipe for fast motion analysis.
    Returns 3D numpy array [num_frames, height, width] uint8 or None.
    """
    if not video_path or not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
        return None

    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", video_path,
        "-vf", f"fps={fps},scale={width}:{height}",
        "-f", "rawvideo",
        "-pix_fmt", "gray",
        "pipe:1"
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        if proc.returncode == 0 and len(proc.stdout) > 0:
            frame_bytes = width * height
            n_frames = len(proc.stdout) // frame_bytes
            if n_frames > 0:
                raw_buf = proc.stdout[:n_frames * frame_bytes]
                return np.frombuffer(raw_buf, dtype=np.uint8).reshape((n_frames, height, width))
        return None
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None


class AudioEnergyAnalyzer:
    """
    Evaluates acoustic energy and dramatic inflection dynamics:
    - E(t): Continuous short-time RMS energy in dBFS.
    - mu_E, sigma_E: Video baseline mean and standard deviation.
    - DR_E: Dynamic range (p90 - p10).
    - Z_E(t): Normalized acoustic energy deviation.
    - Delta Z_E(t): Transition contrast |Z_E(t) - Z_E(t - delta)|.
    - evaluate_interval(): Maps candidate window to [0.0, 10.0] score with graceful fallback.
    """

    def __init__(
        self,
        media_path: Optional[str] = None,
        pcm_data: Optional[bytes] = None,
        sample_rate: int = 16000,
        hop_sec: float = 0.05,
        win_sec: float = 0.10,
        delta_sec: float = 0.50,
    ):
        self.sample_rate = sample_rate
        self.hop_sec = hop_sec
        self.win_sec = win_sec
        self.delta_sec = delta_sec

        self.is_available: bool = False
        self.frame_times: np.ndarray = np.array([], dtype=np.float32)
        self.energy_db: np.ndarray = np.array([], dtype=np.float32)
        self.z_energy: np.ndarray = np.array([], dtype=np.float32)
        self.delta_z: np.ndarray = np.array([], dtype=np.float32)

        self.mean_e: float = -20.0
        self.std_e: float = 5.0
        self.dynamic_range_e: float = 10.0

        raw_pcm = pcm_data
        if raw_pcm is None and media_path is not None:
            raw_pcm = extract_pcm_from_file(media_path, sample_rate=sample_rate)

        if raw_pcm is not None and len(raw_pcm) >= 4:
            self._compute_energy_profile(raw_pcm)

    def _compute_energy_profile(self, pcm_data: bytes) -> None:
        """Computes short-time RMS energy envelope and normalized deviations."""
        try:
            if len(pcm_data) % 2 != 0:
                pcm_data = pcm_data[:len(pcm_data) - 1]
            samples = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
            n_samples = len(samples)
            win_size = max(int(round(self.win_sec * self.sample_rate)), 1)
            hop_size = max(int(round(self.hop_sec * self.sample_rate)), 1)

            if n_samples < win_size:
                return

            # Vectorized rolling sum of squares using cumsum
            cumsum_sq = np.concatenate(([0.0], np.cumsum(samples.astype(np.float64) ** 2)))
            starts = np.arange(0, n_samples - win_size + 1, hop_size)
            ends = starts + win_size

            sums = cumsum_sq[ends] - cumsum_sq[starts]
            mean_sq = sums / float(win_size)
            rms = np.sqrt(np.maximum(mean_sq, 1e-12))
            # Convert to dBFS (minimum -100.0 dBFS)
            energy_db = 20.0 * np.log10(np.maximum(rms, 1e-5))

            self.frame_times = (starts + (win_size / 2.0)) / float(self.sample_rate)
            self.energy_db = energy_db.astype(np.float32)

            self.mean_e = float(np.mean(energy_db))
            self.std_e = float(np.std(energy_db))
            if self.std_e < 1e-4:
                self.std_e = 1.0

            p90 = float(np.percentile(energy_db, 90))
            p10 = float(np.percentile(energy_db, 10))
            self.dynamic_range_e = max(0.0, p90 - p10)

            # Normalized energy Z_E
            self.z_energy = (self.energy_db - self.mean_e) / self.std_e

            # Transition contrast Delta Z_E(t) = |Z_E(t) - Z_E(t - delta)|
            delta_frames = max(1, int(round(self.delta_sec / self.hop_sec)))
            shifted_z = np.pad(self.z_energy, (delta_frames, 0), mode="edge")[:len(self.z_energy)]
            self.delta_z = np.abs(self.z_energy - shifted_z).astype(np.float32)

            self.is_available = True
        except Exception:
            self.is_available = False

    def evaluate_interval(self, start_sec: float, end_sec: float) -> float:
        """
        Maps acoustic features within [start_sec, end_sec] to [0.0, 10.0] using:
        Score_audio = 10.0 * sigmoid(1.5 * max(Z_E) + 1.0 * max(Delta Z_E) - 1.0)
        Falls back gracefully to baseline 7.0 if audio is unavailable or invalid.
        """
        if not self.is_available or len(self.frame_times) == 0:
            return 7.0

        if start_sec >= end_sec or end_sec <= 0.0:
            return 7.0

        if start_sec > self.frame_times[-1] or end_sec < self.frame_times[0]:
            return 7.0

        mask = (self.frame_times >= start_sec) & (self.frame_times <= end_sec)
        if not np.any(mask):
            # Interval narrower than hop step; find closest single frame
            idx = int(np.searchsorted(self.frame_times, (start_sec + end_sec) / 2.0))
            idx = min(max(0, idx), len(self.frame_times) - 1)
            max_z = float(self.z_energy[idx])
            max_delta_z = float(self.delta_z[idx])
        else:
            max_z = float(np.max(self.z_energy[mask]))
            max_delta_z = float(np.max(self.delta_z[mask]))

        # Non-linear sigmoid audio highlight formula
        activation = 1.5 * max_z + 1.0 * max_delta_z - 1.0
        clamped_act = max(-20.0, min(20.0, activation))
        sig = 1.0 / (1.0 + math.exp(-clamped_act))

        score = 10.0 * sig
        return round(float(max(0.0, min(10.0, score))), 1)


class MotionEnergyAnalyzer:
    """
    Evaluates visual motion dynamics using 1fps downscaled inter-frame pixel changes.
    Falls back gracefully to baseline 8.0 if video stream is unavailable or corrupted.
    """

    def __init__(
        self,
        video_path: Optional[str] = None,
        frame_diffs: Optional[np.ndarray] = None,
        fps: int = 1,
    ):
        self.fps = fps
        self.is_available: bool = False
        self.frame_times: np.ndarray = np.array([], dtype=np.float32)
        self.motion_diffs: np.ndarray = np.array([], dtype=np.float32)
        self.mean_motion: float = 8.0
        self.std_motion: float = 3.0

        if frame_diffs is not None and len(frame_diffs) > 0:
            self.motion_diffs = frame_diffs.astype(np.float32)
            self.frame_times = np.arange(len(frame_diffs), dtype=np.float32) / float(self.fps)
            self.mean_motion = float(np.mean(self.motion_diffs))
            self.std_motion = max(float(np.std(self.motion_diffs)), 1.0)
            self.is_available = True
        elif video_path is not None:
            frames = extract_motion_frames_from_file(video_path, fps=self.fps)
            if frames is not None and len(frames) >= 2:
                diffs = np.mean(np.abs(np.diff(frames.astype(np.float32), axis=0)), axis=(1, 2))
                self.motion_diffs = diffs.astype(np.float32)
                self.frame_times = np.arange(1, len(frames), dtype=np.float32) / float(self.fps)
                self.mean_motion = float(np.mean(self.motion_diffs))
                self.std_motion = max(float(np.std(self.motion_diffs)), 1.0)
                self.is_available = True

    def evaluate_interval(self, start_sec: float, end_sec: float) -> float:
        """
        Maps inter-frame visual motion dynamics to [0.0, 10.0].
        Moderate dynamic motion earns ~8.0-9.5; static slides earn ~6.5-7.5.
        Falls back gracefully to baseline 8.0 if motion analysis is unavailable.
        """
        if not self.is_available or len(self.motion_diffs) == 0 or start_sec >= end_sec:
            return 8.0

        if start_sec > self.frame_times[-1] or end_sec < self.frame_times[0]:
            return 8.0

        mask = (self.frame_times >= start_sec) & (self.frame_times <= end_sec)
        if not np.any(mask):
            idx = int(np.searchsorted(self.frame_times, (start_sec + end_sec) / 2.0))
            idx = min(max(0, idx), len(self.frame_times) - 1)
            interval_motion = float(self.motion_diffs[idx])
        else:
            interval_motion = float(np.mean(self.motion_diffs[mask]))

        z_motion = (interval_motion - self.mean_motion) / self.std_motion
        # Soft sigmoid around baseline 8.0
        score = 8.0 + 1.8 * math.tanh(z_motion * 0.7)
        return round(float(max(1.0, min(10.0, score))), 1)


def compute_words_speech_rate(words: List[WordTimestamp]) -> Tuple[float, float]:
    """
    Computes speech rate in WPM and active speech duration (excluding inter-word pauses > 0.25s).
    Properly handles word overlapping and variable timestamps via interval merging.
    Returns (wpm, active_speech_seconds).
    """
    if not words:
        return 0.0, 0.0

    n_words = len(words)
    if n_words == 1:
        span = max(words[0].end - words[0].start, 0.15)
        return (1.0 / span) * 60.0, span

    sorted_words = sorted(words, key=lambda w: (w.start, w.end))
    speech_start = sorted_words[0].start

    # Interval merging to compute true active speech and pauses without overestimating due to overlap
    pauses = 0.0
    cur_end = sorted_words[0].end
    for w in sorted_words[1:]:
        if w.start > cur_end:
            gap = w.start - cur_end
            if gap > 0.25:
                pauses += gap
            cur_end = w.end
        else:
            cur_end = max(cur_end, w.end)

    speech_end = max(cur_end, speech_start + 0.15)
    total_span = max(speech_end - speech_start, 0.15)
    active_speech = max(total_span - pauses, 0.2)
    wpm = (float(n_words) / active_speech) * 60.0
    return wpm, active_speech


class AdaptiveCadenceScorer:
    """
    Evaluates video-relative speaking rate deviation Z_R(i) = (R_i - mu_R) / sigma_R.
    Replaces static 135-185 WPM brackets with relational pacing dynamics:
    - F_fluency = exp(-Z_R^2 / (2 * 1.8^2))
    - M_dynamic = (max(Z_R) - min(Z_R)) / 2.5
    - Score_cadence = 10.0 * (0.65 * F_fluency + 0.35 * min(M_dynamic, 1.0))
    Falls back gracefully to static logic if transcript lacks word timestamps or duration.
    """

    def __init__(self, transcript: Optional[Transcript] = None):
        self.is_available: bool = False
        self.mu_r: float = 160.0
        self.sigma_r: float = 20.0
        self.has_word_timestamps: bool = False

        if transcript is not None and transcript.segments and transcript.duration_seconds > 0.0:
            self._calibrate_baseline(transcript)

    def _calibrate_baseline(self, transcript: Transcript) -> None:
        """Calibrates speaker baseline mean rate mu_R and standard deviation sigma_R across transcript."""
        rates: List[float] = []
        any_words = False

        for seg in transcript.segments:
            if seg.words and len(seg.words) >= 2:
                any_words = True
                if len(seg.words) > 20:
                    step = 10
                    for w_i in range(0, len(seg.words), step):
                        sub_w = seg.words[w_i : w_i + step]
                        if len(sub_w) >= 3:
                            wpm, _ = compute_words_speech_rate(sub_w)
                            if 20.0 <= wpm <= 600.0:
                                rates.append(wpm)
                else:
                    wpm, _ = compute_words_speech_rate(seg.words)
                    if 20.0 <= wpm <= 600.0:
                        rates.append(wpm)

        self.has_word_timestamps = any_words

        if len(rates) >= 2:
            self.mu_r = float(statistics.mean(rates))
            raw_stdev = float(statistics.stdev(rates))
            # Floor stdev at 10.0 WPM to avoid hyper-sensitivity in highly uniform speech
            self.sigma_r = max(raw_stdev, 10.0)
            self.is_available = True
        elif len(rates) == 1:
            self.mu_r = rates[0]
            self.sigma_r = 20.0
            self.is_available = True
        else:
            self.is_available = False

    def fallback_score(self, num_words: int, duration: float) -> float:
        """Static 135-185 WPM heuristic bracket fallback."""
        eff_dur = max(duration, 0.5)
        wpm = (num_words / eff_dur) * 60.0
        if 135.0 <= wpm <= 185.0:
            return 9.5
        elif 110.0 <= wpm < 135.0 or 185.0 < wpm <= 210.0:
            return 7.5
        elif 90.0 <= wpm < 110.0 or 210.0 < wpm <= 240.0:
            return 5.5
        else:
            return 3.5

    def score_cadence(
        self,
        words: Optional[List[WordTimestamp]] = None,
        duration: float = 0.0,
        sentences: Optional[List[Any]] = None,
        num_words: Optional[int] = None,
    ) -> float:
        """
        Computes adaptive relative cadence score for a candidate.
        If word timestamps or baseline are unavailable, falls back to static bracket logic.
        """
        w_count = num_words if num_words is not None else (len(words) if words else 0)

        if not self.is_available or not words or duration <= 0.0 or len(words) < 2:
            return self.fallback_score(w_count, duration)

        # 1. Candidate overall speaking rate and Z_R deviation
        cand_wpm, _ = compute_words_speech_rate(words)
        z_cand = (cand_wpm - self.mu_r) / self.sigma_r

        # Fluency baseline: F_fluency = exp(-Z_R^2 / (2 * 1.8^2))
        f_fluency = math.exp(-(z_cand ** 2) / (2.0 * (1.8 ** 2)))

        # 2. Modulation dynamic: M_dynamic = (max Z_R - min Z_R) / 2.5
        z_rates: List[float] = []

        if sentences and len(sentences) >= 2:
            for s in sentences:
                s_words = getattr(s, "words", None)
                if not s_words:
                    s_words = [w for w in words if getattr(s, "start", 0.0) <= w.start < getattr(s, "end", 0.0)]
                if s_words:
                    r, _ = compute_words_speech_rate(s_words)
                    z_rates.append((r - self.mu_r) / self.sigma_r)
        elif len(words) >= 6 and duration >= 5.0:
            # Divide into 3 chronological sub-acts to evaluate internal modulation
            third = duration / 3.0
            t0 = words[0].start
            w1 = [w for w in words if w.start < t0 + third]
            w2 = [w for w in words if t0 + third <= w.start < t0 + 2.0 * third]
            w3 = [w for w in words if w.start >= t0 + 2.0 * third]
            for act_w in (w1, w2, w3):
                if act_w:
                    r, _ = compute_words_speech_rate(act_w)
                    z_rates.append((r - self.mu_r) / self.sigma_r)

        if len(z_rates) >= 2:
            span = max(z_rates) - min(z_rates)
            m_dynamic = span / 2.5
        else:
            m_dynamic = 0.35  # Moderate default dynamic for single sentence

        # Cadence score: 10.0 * (0.65 * F_fluency + 0.35 * min(M_dynamic, 1.0))
        score = 10.0 * (0.65 * f_fluency + 0.35 * min(max(m_dynamic, 0.0), 1.0))
        return round(float(max(1.0, min(10.0, score))), 1)

    def score_candidate_cadence(self, candidate: HighlightCandidate, transcript: Optional[Transcript] = None) -> float:
        """Evaluates cadence score for a HighlightCandidate against transcript baseline."""
        text = candidate.transcript_text or ""
        words_count = len(text.split())

        if not self.is_available:
            return self.fallback_score(words_count, candidate.duration_seconds)

        cand_words: List[WordTimestamp] = []
        cand_segments: List[TranscriptSegment] = []
        if transcript and transcript.segments:
            for seg in transcript.segments:
                if seg.end > candidate.start_seconds and seg.start < candidate.end_seconds:
                    cand_segments.append(seg)
                if seg.words:
                    for w in seg.words:
                        if w.end > candidate.start_seconds and w.start < candidate.end_seconds:
                            cand_words.append(w)

        return self.score_cadence(
            words=cand_words,
            duration=candidate.duration_seconds,
            sentences=cand_segments if len(cand_segments) >= 2 else None,
            num_words=words_count,
        )
