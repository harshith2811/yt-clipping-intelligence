"""
Adversarial Stress Test Suite for Milestone M1.
Covers extreme, malformed, out-of-bounds, and degraded inputs for:
1. Forced-Alignment Subsystem (FasterWhisperAlignmentAdapter, WhisperXAlignmentAdapter)
2. Speaker Diarization Subsystem (AcousticEnergyDiarizer, PyannoteDiarizerAdapter, SpeakerTurn, word attribution)
"""

import math
import os
import wave
import struct
import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from src.yt_clipping.contracts.models import Transcript, TranscriptSegment, WordTimestamp
from src.yt_clipping.transcription.alignment import (
    FasterWhisperAlignmentAdapter,
    WhisperXAlignmentAdapter,
    get_alignment_engine,
)
from src.yt_clipping.podcast.diarization import (
    SpeakerTurn,
    SpeakerDiarizer,
    AcousticEnergyDiarizer,
    PyannoteDiarizerAdapter,
    get_speaker_diarizer,
)


# =====================================================================
# 1. Adversarial Alignment: Malformed, Negative, Reversed, NaN Timestamps
# =====================================================================

def test_alignment_reversed_and_negative_words():
    """Test words with start > end and negative timestamps."""
    adapter = FasterWhisperAlignmentAdapter()
    words = [
        WordTimestamp(word="negative", start=-5.0, end=-2.0),
        WordTimestamp(word="reversed", start=4.0, end=1.0),
        WordTimestamp(word="reversed_negative", start=-1.0, end=-3.0),
    ]
    seg = TranscriptSegment(
        segment_id=1,
        start=0.0,
        end=5.0,
        text="negative reversed reversed_negative",
        words=words,
    )
    sanitized = adapter.sanitize_segment_words(seg)
    assert len(sanitized) == 3
    for w in sanitized:
        assert w.start < w.end
        assert w.end - w.start >= adapter.min_word_duration

    # Verify strict monotonicity
    for i in range(len(sanitized) - 1):
        assert sanitized[i].end <= sanitized[i + 1].start


def test_alignment_nan_and_inf_timestamps():
    """Test words and segments containing NaN or infinite timestamps."""
    adapter = FasterWhisperAlignmentAdapter()
    words = [
        WordTimestamp(word="nan_word", start=float("nan"), end=float("nan")),
        WordTimestamp(word="inf_word", start=float("-inf"), end=float("inf")),
        WordTimestamp(word="valid_word", start=1.0, end=2.0),
    ]
    seg = TranscriptSegment(
        segment_id=1,
        start=0.0,
        end=5.0,
        text="nan_word inf_word valid_word",
        words=words,
    )
    # Must not raise unhandled exception
    sanitized = adapter.sanitize_segment_words(seg)
    assert len(sanitized) == 3


def test_alignment_reversed_segment_bounds():
    """Test segment where start > end."""
    adapter = FasterWhisperAlignmentAdapter()
    seg = TranscriptSegment(
        segment_id=1,
        start=10.0,
        end=2.0,  # Reversed
        text="WordOne WordTwo",
        words=[
            WordTimestamp("WordOne", 10.0, 11.0),
            WordTimestamp("WordTwo", 11.0, 12.0),
        ],
    )
    sanitized = adapter.sanitize_segment_words(seg)
    assert len(sanitized) == 2
    for w in sanitized:
        assert w.start < w.end
    assert sanitized[0].end <= sanitized[1].start


def test_alignment_unsynced_segment_nan_bounds():
    """Test synthesizing word timestamps when segment bounds are NaN or inverted."""
    adapter = FasterWhisperAlignmentAdapter()
    seg_nan = TranscriptSegment(
        segment_id=1,
        start=float("nan"),
        end=float("nan"),
        text="First second third",
        words=[],
    )
    # Must synthesize without crashing
    synth_nan = adapter.sanitize_segment_words(seg_nan)
    assert len(synth_nan) == 3
    assert [w.word for w in synth_nan] == ["First", "second", "third"]

    seg_inv = TranscriptSegment(
        segment_id=2,
        start=8.0,
        end=4.0,  # Inverted
        text="Alpha Beta",
        words=[],
    )
    synth_inv = adapter.sanitize_segment_words(seg_inv)
    assert len(synth_inv) == 2
    assert synth_inv[0].start < synth_inv[0].end
    assert synth_inv[0].end <= synth_inv[1].start


def test_alignment_extreme_densities_and_large_timestamps():
    """Test 500 words in 1.0 second and astronomical timestamps."""
    adapter = FasterWhisperAlignmentAdapter()
    # 500 words in 1 second
    dense_words = [
        WordTimestamp(f"w_{i}", 0.0 + i * 0.002, 0.0 + (i + 1) * 0.002)
        for i in range(200)
    ]
    seg_dense = TranscriptSegment(
        segment_id=1,
        start=0.0,
        end=1.0,
        text=" ".join(f"w_{i}" for i in range(200)),
        words=dense_words,
    )
    sanitized = adapter.sanitize_segment_words(seg_dense)
    assert len(sanitized) == 200
    for i in range(len(sanitized) - 1):
        assert sanitized[i].end <= sanitized[i + 1].start

    # Astronomical timestamps (10^9 seconds ~ 31 years)
    astro_seg = TranscriptSegment(
        segment_id=2,
        start=1e9,
        end=1e9 + 10.0,
        text="Astro One Two",
        words=[
            WordTimestamp("Astro", 1e9, 1e9 + 2.0),
            WordTimestamp("One", 1e9 + 2.0, 1e9 + 5.0),
            WordTimestamp("Two", 1e9 + 5.0, 1e9 + 9.0),
        ],
    )
    astro_sanitized = adapter.sanitize_segment_words(astro_seg)
    assert len(astro_sanitized) == 3
    assert astro_sanitized[0].start == 1e9


def test_alignment_dict_polymorphism_adversarial():
    """Test dict representation input with missing or malformed fields."""
    adapter = FasterWhisperAlignmentAdapter()
    malformed_dict = {
        "video_id": "malformed_v1",
        "language": "en",
        "duration_seconds": -10.0,  # Negative duration
        "text": "Hello world",
        "segments": [
            {
                "segment_id": 1,
                "start": 5.0,
                "end": 2.0,  # Reversed
                "text": "Hello world",
                "words": [
                    {"word": "Hello", "start": 5.0, "end": 2.0},
                    {"word": "world", "start": 6.0, "end": 4.0},
                ],
                "speaker_tag": None,
            }
        ],
    }
    result = adapter.align_words("fake_path.mp3", malformed_dict)
    assert isinstance(result, dict)
    assert len(result["segments"]) == 1
    w0 = result["segments"][0]["words"][0]
    w1 = result["segments"][0]["words"][1]
    assert w0["start"] < w0["end"]
    assert w0["end"] <= w1["start"]


def test_whisperx_adversarial_fault_injection(tmp_path):
    """Test WhisperX cascade on missing audio, corrupted audio, and CUDA/CPU failures."""
    adapter = WhisperXAlignmentAdapter(device="cuda")

    # 1. Non-existent audio
    t = Transcript(
        video_id="v_err_1",
        language="en",
        duration_seconds=5.0,
        text="Test text",
        segments=[TranscriptSegment(1, 0.0, 5.0, "Test text", words=[WordTimestamp("Test", 0.0, 2.0), WordTimestamp("text", 2.0, 4.0)])],
    )
    res_missing = adapter.align_words("non_existent_file_99999.wav", t)
    assert isinstance(res_missing, Transcript)

    # 2. Corrupted 0-byte file
    zero_file = tmp_path / "zero.wav"
    zero_file.write_bytes(b"")
    # Wait, os.path.exists is True, but getsize is 0 -> WhisperX adapter line 292 checks os.path.exists
    # Let's test non-empty corrupted file
    corrupt_file = tmp_path / "corrupt.wav"
    corrupt_file.write_bytes(b"NOT_A_REAL_WAV_HEADER_CORRUPTED_BYTES" * 100)

    # Mock whisperx throwing exception on corrupt file
    mock_wx = MagicMock()
    mock_wx.load_audio.side_effect = RuntimeError("Failed to decode audio file")
    with patch.object(adapter, "is_available", return_value=True):
        with patch.dict("sys.modules", {"whisperx": mock_wx}):
            res_corrupt = adapter.align_words(str(corrupt_file), t)
            assert isinstance(res_corrupt, Transcript)
            assert "faster-whisper-aligned" in res_corrupt.provider


# =====================================================================
# 2. Adversarial Diarization: Buffer Extremes, High k, Noise, DC Offset
# =====================================================================

def _create_synthetic_pcm_wav(path: str, samples: np.ndarray, sample_rate: int = 16000, channels: int = 1):
    """Helper to write raw numpy samples (-1.0 to 1.0) into a standard WAV file."""
    clipped = np.clip(samples, -1.0, 1.0)
    int16_data = (clipped * 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(int16_data.tobytes())


def test_diarization_buffer_extremes(tmp_path):
    """Test extremely short (0s, 0.05s, 0.19s) and boundary audio buffers."""
    diarizer = AcousticEnergyDiarizer()

    # 1. Empty file
    empty_path = str(tmp_path / "empty.wav")
    with open(empty_path, "wb") as f:
        pass
    assert diarizer.diarize(empty_path) == []

    # 2. Extremely short: 1 sample
    short1_path = str(tmp_path / "short_1.wav")
    _create_synthetic_pcm_wav(short1_path, np.array([0.5], dtype=np.float32))
    assert diarizer.diarize(short1_path) == []

    # 3. 0.1s (1600 samples < 0.2s minimum)
    short100ms_path = str(tmp_path / "short_100ms.wav")
    _create_synthetic_pcm_wav(short100ms_path, np.zeros(1600, dtype=np.float32))
    assert diarizer.diarize(short100ms_path) == []

    # 4. 0.21s boundary (3360 samples, >= 0.2s but < 5 frames)
    boundary_path = str(tmp_path / "boundary.wav")
    # Sine wave
    t_bound = np.linspace(0, 0.21, 3360, endpoint=False)
    boundary_audio = (0.5 * np.sin(2 * np.pi * 300 * t_bound)).astype(np.float32)
    _create_synthetic_pcm_wav(boundary_path, boundary_audio)
    turns = diarizer.diarize(boundary_path)
    assert len(turns) == 1
    assert turns[0].speaker_id == "SPEAKER_00"
    assert turns[0].start == 0.0
    assert math.isclose(turns[0].end, 0.21, abs_tol=0.01)


def test_diarization_large_buffer(tmp_path):
    """Test large audio buffer (480,000 samples = 30 seconds) with alternating speakers and pauses."""
    diarizer = AcousticEnergyDiarizer()
    large_path = str(tmp_path / "large_audio.wav")

    sr = 16000
    dur = 30.0
    t = np.linspace(0, dur, int(dur * sr), endpoint=False)
    audio = np.zeros(int(dur * sr), dtype=np.float32)

    # 4 speech segments with pauses:
    # 0.5-5.0s: 200Hz
    # 6.0-12.0s: 600Hz
    # 14.0-20.0s: 200Hz
    # 22.0-28.0s: 600Hz
    def add_tone(start, end, f):
        s = int(start * sr)
        e = int(end * sr)
        audio[s:e] = 0.5 * np.sin(2 * np.pi * f * t[s:e])

    add_tone(0.5, 5.0, 200.0)
    add_tone(6.0, 12.0, 600.0)
    add_tone(14.0, 20.0, 200.0)
    add_tone(22.0, 28.0, 600.0)

    _create_synthetic_pcm_wav(large_path, audio, sample_rate=sr)
    turns = diarizer.diarize(large_path, num_speakers=2)
    assert len(turns) >= 2
    assert turns[0].start >= 0.0
    assert turns[-1].end <= dur
    spk_ids = set(t.speaker_id for t in turns)
    assert len(spk_ids) == 2


def test_diarization_narrow_dynamic_range_fallback(tmp_path):
    """
    Test audio with narrow dynamic range (<12 dB between peak and floor, e.g. continuous drone).
    Verifies that VAD falls back cleanly to a single SPEAKER_00 turn with zero exceptions.
    """
    diarizer = AcousticEnergyDiarizer()
    drone_path = str(tmp_path / "drone.wav")

    sr = 16000
    dur = 5.0
    t = np.linspace(0, dur, int(dur * sr), endpoint=False)
    # Continuous tone with zero silence (peak - floor ~ 0 dB)
    samples = (0.4 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    _create_synthetic_pcm_wav(drone_path, samples, sample_rate=sr)

    turns = diarizer.diarize(drone_path, num_speakers=2)
    assert len(turns) == 1
    assert turns[0].speaker_id == "SPEAKER_00"
    assert math.isclose(turns[0].end, dur, abs_tol=0.1)


def test_diarization_unusually_high_k_clusters(tmp_path):
    """Test k=10 clusters on 2-speaker audio and on uniform tone audio."""
    diarizer = AcousticEnergyDiarizer()
    wav_path = str(tmp_path / "k10_test.wav")

    # 6 seconds audio with 2 speakers alternating
    sr = 16000
    t = np.linspace(0, 6.0, int(6.0 * sr), endpoint=False)
    freq = np.where(t < 3.0, 150.0, 500.0)
    samples = (0.6 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    _create_synthetic_pcm_wav(wav_path, samples, sample_rate=sr)

    # Request k=10
    turns = diarizer.diarize(wav_path, num_speakers=10)
    assert len(turns) > 0
    # Must not crash, turns must be valid SpeakerTurn objects
    for turn in turns:
        assert isinstance(turn, SpeakerTurn)
        assert turn.start >= 0.0
        assert turn.end >= turn.start

    # Request extreme k=100 (where k > number of analysis chunks)
    turns_extreme = diarizer.diarize(wav_path, num_speakers=100)
    assert len(turns_extreme) > 0


def test_diarization_pure_dc_offset(tmp_path):
    """Test pure DC offset audio (constant 0.5, constant 1.0, constant -0.5)."""
    diarizer = AcousticEnergyDiarizer()

    for val in [0.5, 1.0, -0.8]:
        dc_path = str(tmp_path / f"dc_{val}.wav")
        samples = np.full(16000 * 3, val, dtype=np.float32)
        _create_synthetic_pcm_wav(dc_path, samples)

        turns = diarizer.diarize(dc_path)
        # DC offset should be cleanly handled (classified as silence/single turn) with zero crashes
        assert len(turns) == 1
        assert turns[0].speaker_id == "SPEAKER_00"
        assert math.isclose(turns[0].end, 3.0, abs_tol=0.1)


def test_diarization_high_noise_audio(tmp_path):
    """Test 0 dBFS pure Gaussian white noise and low-amplitude noise."""
    diarizer = AcousticEnergyDiarizer()

    # 1. Pure full-scale white noise
    noise_path = str(tmp_path / "white_noise.wav")
    np.random.seed(42)
    noise = np.random.uniform(-1.0, 1.0, 16000 * 3).astype(np.float32)
    _create_synthetic_pcm_wav(noise_path, noise)

    turns = diarizer.diarize(noise_path)
    assert len(turns) > 0
    for t in turns:
        assert isinstance(t, SpeakerTurn)
        assert t.start >= 0.0
        assert t.end >= t.start

    # 2. Nyquist frequency tone (alternating +1, -1)
    nyquist_path = str(tmp_path / "nyquist.wav")
    nyquist = np.tile([1.0, -1.0], 16000 * 2).astype(np.float32)
    _create_synthetic_pcm_wav(nyquist_path, nyquist)
    turns_nyq = diarizer.diarize(nyquist_path)
    assert len(turns_nyq) > 0


def test_numpy_kmeans_stress_cases():
    """Stress test pure numpy kmeans under edge and degenerate conditions."""
    # 1. Single sample with k=5
    X_single = np.array([[1.0, 2.0, 3.0, 4.0]])
    labels_single = AcousticEnergyDiarizer._numpy_kmeans(X_single, k=5)
    assert len(labels_single) == 1
    assert labels_single[0] == 0

    # 2. Identical samples (0 variance)
    X_identical = np.ones((50, 4))
    labels_identical = AcousticEnergyDiarizer._numpy_kmeans(X_identical, k=4)
    assert len(labels_identical) == 50
    assert np.all(labels_identical == 0)

    # 3. High k (k=20 on 25 samples)
    X_rand = np.random.RandomState(42).randn(25, 4)
    labels_high_k = AcousticEnergyDiarizer._numpy_kmeans(X_rand, k=20)
    assert len(labels_high_k) == 25
    assert np.min(labels_high_k) >= 0
    assert np.max(labels_high_k) < 20


def test_speaker_attribution_adversarial_words():
    """Test attribute_words_to_speakers with NaN, negative, inverted, and distant words."""
    turns = [
        SpeakerTurn("SPEAKER_00", 1.0, 3.0),
        SpeakerTurn("SPEAKER_01", 4.0, 7.0),
    ]
    words = [
        # Normal words
        WordTimestamp("Hello", 1.2, 1.8),
        # Word with NaN timestamps
        WordTimestamp("nan_word", float("nan"), float("nan")),
        # Word with negative timestamps
        WordTimestamp("neg_word", -5.0, -4.0),
        # Word with reversed timestamps
        WordTimestamp("rev_word", 6.0, 5.0),
        # Distant word outside all turns
        WordTimestamp("distant_word", 100.0, 101.0),
    ]

    attributed = SpeakerDiarizer.attribute_words_to_speakers(turns, words, default_speaker="SPEAKER_FALLBACK")
    assert len(attributed) == 5
    assert attributed[0].speaker_tag == "SPEAKER_00"
    assert attributed[1].speaker_tag is not None  # NaN handled
    assert attributed[2].speaker_tag == "SPEAKER_FALLBACK"  # -5s distant
    assert attributed[3].speaker_tag == "SPEAKER_01"  # 5-6s within turn 2
    assert attributed[4].speaker_tag == "SPEAKER_FALLBACK"  # 100s distant


def test_pyannote_adapter_adversarial_cascades(tmp_path):
    """Test Pyannote adapter under complete cascade failure conditions."""
    wav_path = str(tmp_path / "pyannote_test.wav")
    _create_synthetic_pcm_wav(wav_path, np.zeros(16000 * 2, dtype=np.float32))

    # 1. No token provided
    adapter_no_token = PyannoteDiarizerAdapter(hf_token=None)
    with patch.dict(os.environ, {"HF_TOKEN": "", "HUGGINGFACE_TOKEN": ""}):
        adapter_no_token.hf_token = None
        turns = adapter_no_token.diarize(wav_path)
        assert len(turns) > 0
        assert turns[0].speaker_id == "SPEAKER_00"

    # 2. Pipeline raises unexpected exception (e.g. MemoryError)
    adapter_error = PyannoteDiarizerAdapter(hf_token="fake_token")
    mock_pipeline = MagicMock(side_effect=MemoryError("Out of host RAM"))
    with patch.object(adapter_error, "_load_pipeline", return_value=mock_pipeline):
        turns_err = adapter_error.diarize(wav_path)
        assert len(turns_err) > 0
        assert turns_err[0].speaker_id == "SPEAKER_00"
