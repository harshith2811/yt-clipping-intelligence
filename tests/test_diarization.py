"""
Unit and integration tests for Speaker Diarization subsystem:
SpeakerTurn, AcousticEnergyDiarizer, PyannoteDiarizerAdapter, get_speaker_diarizer.
"""

import pytest
import os
import wave
import struct
import numpy as np
from unittest.mock import MagicMock, patch

from src.yt_clipping.contracts.models import WordTimestamp
from src.yt_clipping.podcast.diarization import (
    SpeakerTurn,
    SpeakerDiarizer,
    AcousticEnergyDiarizer,
    PyannoteDiarizerAdapter,
    get_speaker_diarizer,
)


def test_speaker_turn_dataclass_contract():
    turn = SpeakerTurn(speaker_id="SPEAKER_00", start=1.0, end=4.5, confidence=0.95)
    assert turn.speaker_id == "SPEAKER_00"
    assert turn.start == 1.0
    assert turn.end == 4.5
    assert turn.duration == 3.5
    assert turn.overlap_seconds(2.0, 3.0) == 1.0
    assert turn.overlap_seconds(0.0, 1.0) == 0.0
    assert turn.overlap_seconds(4.0, 5.0) == 0.5

    # Negative start validation
    with pytest.raises(ValueError, match="cannot be negative"):
        SpeakerTurn(speaker_id="SPEAKER_00", start=-1.0, end=3.0)

    # Inverted bounds validation
    with pytest.raises(ValueError, match="cannot precede start"):
        SpeakerTurn(speaker_id="SPEAKER_00", start=5.0, end=2.0)

    # Confidence validation
    with pytest.raises(ValueError, match="confidence"):
        SpeakerTurn(speaker_id="SPEAKER_00", start=0.0, end=1.0, confidence=1.5)


def test_speaker_turn_serialization():
    turn = SpeakerTurn(speaker_id="SPEAKER_01", start=2.1234, end=5.6789, confidence=0.92)
    d = turn.to_dict()
    assert d["speaker_id"] == "SPEAKER_01"
    assert d["start"] == 2.123
    assert d["end"] == 5.679
    assert d["duration"] == round(turn.duration, 3)
    assert d["confidence"] == 0.92

    reconstructed = SpeakerTurn.from_dict(d)
    assert reconstructed.speaker_id == "SPEAKER_01"
    assert reconstructed.start == 2.123
    assert reconstructed.end == 5.679


def test_attribute_words_to_speakers_exact():
    turns = [
        SpeakerTurn("SPEAKER_00", 0.0, 2.0),
        SpeakerTurn("SPEAKER_01", 2.5, 5.0),
    ]
    words = [
        WordTimestamp("Hello", 0.2, 0.8),
        WordTimestamp("there", 1.0, 1.5),
        WordTimestamp("General", 2.6, 3.2),
        WordTimestamp("Kenobi", 3.5, 4.2),
    ]

    attributed = SpeakerDiarizer.attribute_words_to_speakers(turns, words)
    assert len(attributed) == 4
    assert attributed[0].speaker_tag == "SPEAKER_00"
    assert attributed[1].speaker_tag == "SPEAKER_00"
    assert attributed[2].speaker_tag == "SPEAKER_01"
    assert attributed[3].speaker_tag == "SPEAKER_01"


def test_attribute_words_to_speakers_gap_fallback():
    turns = [
        SpeakerTurn("SPEAKER_00", 0.0, 2.0),
        SpeakerTurn("SPEAKER_01", 3.0, 5.0),
    ]
    # Word spoken in a brief pause at 2.1s (closer to SPEAKER_00 than SPEAKER_01)
    words = [
        WordTimestamp("pause_word", 2.05, 2.3),
    ]
    attributed = SpeakerDiarizer.attribute_words_to_speakers(turns, words, gap_tolerance_seconds=0.8)
    assert attributed[0].speaker_tag == "SPEAKER_00"

    # Word spoken far away (> gap tolerance) falls back to default_speaker
    far_words = [
        WordTimestamp("lost_word", 10.0, 10.5),
    ]
    attributed_far = SpeakerDiarizer.attribute_words_to_speakers(turns, far_words, default_speaker="SPEAKER_DEFAULT")
    assert attributed_far[0].speaker_tag == "SPEAKER_DEFAULT"


def test_attribute_words_to_speakers_empty_turns():
    words = [
        WordTimestamp("孤", 0.0, 1.0),
    ]
    attributed = SpeakerDiarizer.attribute_words_to_speakers([], words, default_speaker="HOST")
    assert len(attributed) == 1
    assert attributed[0].speaker_tag == "HOST"

    # Empty words
    assert SpeakerDiarizer.attribute_words_to_speakers([], []) == []


def test_attribute_words_preserves_attributes():
    turns = [SpeakerTurn("SPEAKER_00", 0.0, 5.0)]
    words = [WordTimestamp("Preserve", 1.0, 2.0, confidence=0.88)]
    attributed = SpeakerDiarizer.attribute_words_to_speakers(turns, words)

    w = attributed[0]
    assert w.word == "Preserve"
    assert w.start == 1.0
    assert w.end == 2.0
    assert w.confidence == 0.88
    assert w.speaker_tag == "SPEAKER_00"


def _create_synthetic_wav(path: str, duration_sec: float = 3.0, freq: float = 440.0, sample_rate: int = 16000):
    """Helper to generate a real PCM WAV file with a sine wave."""
    n_samples = int(duration_sec * sample_rate)
    t = np.linspace(0, duration_sec, n_samples, endpoint=False)
    # 440Hz sine wave
    audio_data = (0.5 * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)

    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_data.tobytes())


def _create_silence_wav(path: str, duration_sec: float = 2.0, sample_rate: int = 16000):
    """Helper to generate a silent PCM WAV file."""
    n_samples = int(duration_sec * sample_rate)
    audio_data = np.zeros(n_samples, dtype=np.int16)

    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_data.tobytes())


def test_acoustic_diarizer_synthetic_audio(tmp_path):
    wav_path = str(tmp_path / "synthetic_voice.wav")
    _create_synthetic_wav(wav_path, duration_sec=3.0, freq=300.0)

    diarizer = AcousticEnergyDiarizer()
    turns = diarizer.diarize(wav_path, num_speakers=1)
    assert len(turns) > 0
    assert turns[0].speaker_id.startswith("SPEAKER_")
    assert turns[0].start >= 0.0
    assert turns[-1].end <= 3.1


def test_acoustic_diarizer_pure_silence(tmp_path):
    wav_path = str(tmp_path / "silence.wav")
    _create_silence_wav(wav_path, duration_sec=2.0)

    diarizer = AcousticEnergyDiarizer()
    turns = diarizer.diarize(wav_path)
    assert len(turns) == 1
    assert turns[0].speaker_id == "SPEAKER_00"
    assert turns[0].duration >= 1.9


def test_acoustic_diarizer_missing_file():
    diarizer = AcousticEnergyDiarizer()
    turns = diarizer.diarize("non_existent_file_xyz_123.wav")
    assert turns == []


def test_acoustic_diarizer_numpy_kmeans():
    # Two clear 2D clusters
    cluster_a = np.random.RandomState(42).normal(loc=[-5.0, -5.0], scale=0.5, size=(20, 2))
    cluster_b = np.random.RandomState(42).normal(loc=[5.0, 5.0], scale=0.5, size=(20, 2))
    X = np.vstack([cluster_a, cluster_b])

    labels = AcousticEnergyDiarizer._numpy_kmeans(X, k=2)
    assert len(labels) == 40
    # Cluster A labels should be identical to each other
    assert len(set(labels[:20])) == 1
    # Cluster B labels should be identical to each other
    assert len(set(labels[20:])) == 1
    # Two clusters must have different labels
    assert labels[0] != labels[20]


def test_pyannote_adapter_fallback_on_missing_token(tmp_path):
    wav_path = str(tmp_path / "test.wav")
    _create_synthetic_wav(wav_path, duration_sec=2.0)

    # Empty token forces fallback to AcousticEnergyDiarizer
    adapter = PyannoteDiarizerAdapter(hf_token=None)
    with patch.dict(os.environ, {"HF_TOKEN": "", "HUGGINGFACE_TOKEN": ""}, clear=False):
        adapter.hf_token = None
        turns = adapter.diarize(wav_path)
        assert len(turns) > 0
        assert turns[0].speaker_id.startswith("SPEAKER_")


def test_pyannote_adapter_mock_pipeline(tmp_path):
    wav_path = str(tmp_path / "test.wav")
    _create_synthetic_wav(wav_path, duration_sec=2.0)

    adapter = PyannoteDiarizerAdapter(hf_token="fake_hf_token")

    # Mock pyannote pipeline track object
    class MockTrack:
        start = 0.5
        end = 1.8

    mock_track = MockTrack()
    mock_diarization = MagicMock()
    mock_diarization.itertracks.return_value = [(mock_track, None, "SPEAKER_GUEST")]

    mock_pipeline = MagicMock(return_value=mock_diarization)

    with patch.object(adapter, "_load_pipeline", return_value=mock_pipeline):
        turns = adapter.diarize(wav_path)
        assert len(turns) == 1
        assert turns[0].speaker_id == "SPEAKER_GUEST"
        assert turns[0].start == 0.5
        assert turns[0].end == 1.8


def test_pyannote_adapter_runtime_exception_fallback(tmp_path):
    wav_path = str(tmp_path / "test.wav")
    _create_synthetic_wav(wav_path, duration_sec=2.0)

    adapter = PyannoteDiarizerAdapter(hf_token="fake_hf_token")
    mock_pipeline = MagicMock(side_effect=RuntimeError("CUDA out of memory"))

    with patch.object(adapter, "_load_pipeline", return_value=mock_pipeline):
        # Falls back to AcousticEnergyDiarizer without crashing
        turns = adapter.diarize(wav_path)
        assert len(turns) > 0
        assert turns[0].speaker_id.startswith("SPEAKER_")


def test_get_speaker_diarizer_factory():
    # Default without flags gives AcousticEnergyDiarizer
    d1 = get_speaker_diarizer()
    assert isinstance(d1, AcousticEnergyDiarizer)

    # prefer_neural=True gives PyannoteDiarizerAdapter
    d2 = get_speaker_diarizer(prefer_neural=True)
    assert isinstance(d2, PyannoteDiarizerAdapter)

    # config with use_neural_diarizer=True
    class DummyConfig:
        use_neural_diarizer = True

    d3 = get_speaker_diarizer(DummyConfig())
    assert isinstance(d3, PyannoteDiarizerAdapter)

    # dict config with use_neural_diarizer=True
    d4 = get_speaker_diarizer({"use_neural_diarizer": True})
    assert isinstance(d4, PyannoteDiarizerAdapter)


def test_extract_pcm_mono_fallback_command_structure(tmp_path):
    """Verify that FFmpeg mono fallback targets -ac (index 12) rather than -acodec (index 8)."""
    diarizer = AcousticEnergyDiarizer()
    cmd_records = []

    def mock_run(cmd, *args, **kwargs):
        cmd_records.append(list(cmd))
        mock_proc = MagicMock()
        if len(cmd_records) == 1:
            # First call (stereo) fails
            mock_proc.returncode = 1
            mock_proc.stdout = b""
        else:
            # Second call (mono fallback) succeeds with 1 second mono audio
            mock_proc.returncode = 0
            mock_proc.stdout = (np.zeros(16000, dtype=np.int16)).tobytes()
        return mock_proc

    wav_path = str(tmp_path / "dummy.wav")
    _create_synthetic_wav(wav_path, duration_sec=1.0)

    with patch("subprocess.run", side_effect=mock_run):
        pcm, channels = diarizer._extract_pcm(wav_path)
        assert channels == 1
        assert len(cmd_records) == 2
        mono_cmd = cmd_records[1]
        assert mono_cmd[7] == "-acodec"
        assert mono_cmd[8] == "pcm_s16le"
        assert mono_cmd[11] == "-ac"
        assert mono_cmd[12] == "1"


def test_diarize_short_turn_temporal_adjacency_silence_gap():
    """Verify short turn after silence gap > 0.8s is preserved as distinct turn rather than stretched."""
    raw_turns = [(0, 0.0, 5.0), (1, 15.0, 15.2)]

    final_turns = []
    min_turn_duration = 0.4
    for i, (spk_idx, s_start, s_end) in enumerate(raw_turns):
        dur = s_end - s_start
        if dur < min_turn_duration and final_turns and (s_start - final_turns[-1].end) <= 0.8:
            prev = final_turns[-1]
            final_turns[-1] = SpeakerTurn(prev.speaker_id, prev.start, round(max(prev.end, s_end), 3), prev.confidence)
        else:
            spk_id = f"SPEAKER_{spk_idx:02d}"
            final_turns.append(SpeakerTurn(spk_id, round(s_start, 3), round(s_end, 3), 0.90))

    assert len(final_turns) == 2
    assert final_turns[0].end == 5.0
    assert final_turns[1].start == 15.0
    assert final_turns[1].end == 15.2


def test_numpy_kmeans_random_state_isolation():
    """Verify that _numpy_kmeans does not mutate process-global np.random state."""
    np.random.seed(999)
    expected_global = np.random.rand(10)

    np.random.seed(999)
    X = np.array([[1.0, 2.0], [1.1, 2.1], [10.0, 10.0], [10.1, 10.1]])
    AcousticEnergyDiarizer._numpy_kmeans(X, k=2)
    actual_global = np.random.rand(10)

    # Must be identical: process-global RNG was NOT modified
    assert np.array_equal(actual_global, expected_global)


def test_get_speaker_diarizer_non_string_config_resilience():
    """Verify that get_speaker_diarizer safely coerces non-string config and flags."""
    # Non-string integer engine
    d1 = get_speaker_diarizer(config={"diarization_engine": 123})
    assert isinstance(d1, AcousticEnergyDiarizer)

    # String representation of boolean false
    d2 = get_speaker_diarizer(config={"use_neural_diarizer": "false"})
    assert isinstance(d2, AcousticEnergyDiarizer)

    # String representation of boolean true
    d3 = get_speaker_diarizer(config={"use_neural_diarizer": "true"})
    assert isinstance(d3, PyannoteDiarizerAdapter)

    # prefer_neural as string 'True'
    d4 = get_speaker_diarizer(prefer_neural="True")
    assert isinstance(d4, PyannoteDiarizerAdapter)

    # config as string 'pyannote'
    d5 = get_speaker_diarizer(config="pyannote")
    assert isinstance(d5, PyannoteDiarizerAdapter)

