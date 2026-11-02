"""
Tests for forced-alignment subsystem: FasterWhisperAlignmentAdapter,
WhisperXAlignmentAdapter, and get_alignment_engine factory.
"""

import pytest
import math
from unittest.mock import MagicMock, patch
from src.yt_clipping.contracts.models import Transcript, TranscriptSegment, WordTimestamp
from src.yt_clipping.transcription.alignment import (
    AlignmentEngine,
    FasterWhisperAlignmentAdapter,
    WhisperXAlignmentAdapter,
    get_alignment_engine,
)


@pytest.fixture
def sample_transcript():
    words = [
        WordTimestamp(word="Hello", start=0.5, end=0.3, confidence=0.9),  # Inverted
        WordTimestamp(word="world", start=0.7, end=1.2, confidence=0.95), # Overlapping / valid
    ]
    seg = TranscriptSegment(
        segment_id=1,
        start=0.0,
        end=1.5,
        text="Hello world",
        words=words,
        speaker_tag="SPEAKER_00",
    )
    return Transcript(
        video_id="v_test_01",
        language="en",
        duration_seconds=10.0,
        text="Hello world",
        segments=[seg],
        provider="faster-whisper",
    )


def test_alignment_engine_abc_interface():
    # Attempting to instantiate ABC directly should raise TypeError
    with pytest.raises(TypeError):
        AlignmentEngine()  # type: ignore


def test_faster_whisper_adapter_monotonicity_and_bounds(sample_transcript):
    adapter = FasterWhisperAlignmentAdapter()
    aligned = adapter.align_words("fake_audio.mp3", sample_transcript)

    assert isinstance(aligned, Transcript)
    seg = aligned.segments[0]
    w1, w2 = seg.words[0], seg.words[1]

    # Inversion fixed
    assert w1.start < w1.end
    # Monotonicity
    assert w1.end <= w2.start or math.isclose(w1.end, w2.start, abs_tol=0.01)
    assert w2.start < w2.end
    assert w2.end <= seg.end
    assert w1.speaker_tag == "SPEAKER_00"
    assert "aligned" in aligned.provider


def test_faster_whisper_adapter_synthesizes_missing_words():
    seg = TranscriptSegment(
        segment_id=1,
        start=2.0,
        end=5.0,
        text="This is an unsynced segment",
        words=[],
        speaker_tag="SPEAKER_01",
    )
    t = Transcript(
        video_id="v_test_02",
        language="en",
        duration_seconds=10.0,
        text="This is an unsynced segment",
        segments=[seg],
    )
    adapter = FasterWhisperAlignmentAdapter()
    aligned = adapter.align_words("fake_audio.mp3", t)

    words = aligned.segments[0].words
    assert len(words) == 5
    assert [w.word for w in words] == ["This", "is", "an", "unsynced", "segment"]
    assert words[0].start >= 2.0
    assert words[-1].end >= words[-1].start
    for i in range(len(words) - 1):
        assert words[i].start < words[i].end
        assert words[i].end <= words[i + 1].start
        assert words[i].speaker_tag == "SPEAKER_01"


def test_faster_whisper_adapter_speaker_tag_preservation():
    words = [
        WordTimestamp(word="SpeakerOne", start=0.0, end=0.5, speaker_tag="SPEAKER_01"),
        WordTimestamp(word="SpeakerTwo", start=0.6, end=1.0, speaker_tag="SPEAKER_02"),
    ]
    seg = TranscriptSegment(
        segment_id=1,
        start=0.0,
        end=1.2,
        text="SpeakerOne SpeakerTwo",
        words=words,
        speaker_tag="SPEAKER_01",
    )
    t = Transcript(
        video_id="v_test_03",
        language="en",
        duration_seconds=5.0,
        text="SpeakerOne SpeakerTwo",
        segments=[seg],
    )
    adapter = FasterWhisperAlignmentAdapter()
    aligned = adapter.align_words("dummy.mp3", t)
    assert aligned.segments[0].words[0].speaker_tag == "SPEAKER_01"
    assert aligned.segments[0].words[1].speaker_tag == "SPEAKER_02"


def test_faster_whisper_adapter_dict_polymorphism(sample_transcript):
    adapter = FasterWhisperAlignmentAdapter()
    t_dict = sample_transcript.to_dict()

    aligned_dict = adapter.align_words("fake_audio.mp3", t_dict)
    assert isinstance(aligned_dict, dict)
    assert "segments" in aligned_dict
    assert aligned_dict["segments"][0]["words"][0]["start"] < aligned_dict["segments"][0]["words"][0]["end"]


def test_whisperx_adapter_graceful_degradation_when_uninstalled(sample_transcript):
    adapter = WhisperXAlignmentAdapter()
    with patch.object(adapter, "is_available", return_value=False):
        aligned = adapter.align_words("non_existent_audio.wav", sample_transcript)
        assert isinstance(aligned, Transcript)
        assert aligned.segments[0].words[0].start < aligned.segments[0].words[0].end


def test_whisperx_adapter_cuda_oom_cascade_fallback(sample_transcript, tmp_path):
    dummy_audio = tmp_path / "audio.wav"
    dummy_audio.write_bytes(b"\x00" * 2048)

    adapter = WhisperXAlignmentAdapter(device="cuda")
    with patch.object(adapter, "is_available", return_value=True):
        with patch.object(adapter, "_determine_execution_device", return_value="cuda"):
            with patch.object(adapter, "_try_whisperx_align", side_effect=[None, None]):
                # CUDA fails, CPU fails -> falls back to FasterWhisper
                aligned = adapter.align_words(str(dummy_audio), sample_transcript)
                assert isinstance(aligned, Transcript)
                assert len(aligned.segments) == 1
                assert aligned.segments[0].words[0].start < aligned.segments[0].words[0].end


def test_whisperx_adapter_mocked_success(sample_transcript, tmp_path):
    dummy_audio = tmp_path / "audio.wav"
    dummy_audio.write_bytes(b"\x00" * 2048)

    adapter = WhisperXAlignmentAdapter(device="cpu")
    mock_result = Transcript(
        video_id=sample_transcript.video_id,
        language="en",
        duration_seconds=10.0,
        text="Hello world",
        segments=[
            TranscriptSegment(
                segment_id=1,
                start=0.0,
                end=1.5,
                text="Hello world",
                words=[
                    WordTimestamp(word="Hello", start=0.1, end=0.4, confidence=0.98),
                    WordTimestamp(word="world", start=0.45, end=1.0, confidence=0.99),
                ],
                speaker_tag="SPEAKER_00",
            )
        ],
        provider="whisperx-aligned-cpu",
    )

    with patch.object(adapter, "is_available", return_value=True):
        with patch.object(adapter, "_try_whisperx_align", return_value=mock_result):
            aligned = adapter.align_words(str(dummy_audio), sample_transcript)
            assert isinstance(aligned, Transcript)
            assert aligned.provider == "whisperx-aligned-cpu"
            assert aligned.segments[0].words[0].word == "Hello"
            assert aligned.segments[0].words[0].start == 0.1
            assert aligned.segments[0].words[1].end == 1.0


def test_whisperx_adapter_nan_timestamp_repair(sample_transcript, tmp_path):
    dummy_audio = tmp_path / "audio.wav"
    dummy_audio.write_bytes(b"\x00" * 2048)

    adapter = WhisperXAlignmentAdapter(device="cpu")

    # Simulate whisperx returning NaN/None timestamps
    fake_wx_result = {
        "segments": [
            {
                "start": 0.0,
                "end": 2.0,
                "text": "Hello world test",
                "words": [
                    {"word": "Hello", "start": 0.1, "end": 0.5, "score": 0.95},
                    {"word": "world", "start": None, "end": float("nan"), "score": 0.5},
                    {"word": "test", "start": 0.8, "end": 1.5, "score": 0.92},
                ],
            }
        ]
    }

    mock_whisperx = MagicMock()
    mock_whisperx.load_audio.return_value = MagicMock()
    mock_whisperx.load_align_model.return_value = (MagicMock(), MagicMock())
    mock_whisperx.align.return_value = fake_wx_result

    with patch.object(adapter, "is_available", return_value=True):
        with patch.dict("sys.modules", {"whisperx": mock_whisperx}):
            aligned = adapter.align_words(str(dummy_audio), sample_transcript)
            assert isinstance(aligned, Transcript)
            words = aligned.segments[0].words
            # Unaligned NaN word was skipped, remaining words sanitized
            assert len(words) == 2
            assert words[0].word == "Hello"
            assert words[1].word == "test"
            assert words[0].end <= words[1].start


def test_whisperx_adapter_vram_safety_threshold():
    adapter = WhisperXAlignmentAdapter(device="auto", vram_safety_threshold_mb=1024.0)
    mock_torch = MagicMock()
    mock_torch.cuda.is_available.return_value = True
    # Return 500 MB free (500 * 1024 * 1024 bytes)
    mock_torch.cuda.mem_get_info.return_value = (500 * 1024 * 1024, 4096 * 1024 * 1024)

    with patch.dict("sys.modules", {"torch": mock_torch}):
        chosen_device = adapter._determine_execution_device()
        assert chosen_device == "cpu"


def test_whisperx_adapter_vram_sufficient():
    adapter = WhisperXAlignmentAdapter(device="auto", vram_safety_threshold_mb=1024.0)
    mock_torch = MagicMock()
    mock_torch.cuda.is_available.return_value = True
    # Return 2500 MB free
    mock_torch.cuda.mem_get_info.return_value = (2500 * 1024 * 1024, 4096 * 1024 * 1024)

    with patch.dict("sys.modules", {"torch": mock_torch}):
        chosen_device = adapter._determine_execution_device()
        assert chosen_device == "cuda"


def test_alignment_engine_coerce_error():
    adapter = FasterWhisperAlignmentAdapter()
    with pytest.raises(TypeError, match="Unsupported transcript type"):
        adapter.align_words("fake.mp3", 12345)  # type: ignore


def test_factory_get_alignment_engine():
    e_fw = get_alignment_engine("faster-whisper")
    assert isinstance(e_fw, FasterWhisperAlignmentAdapter)

    e_wx = get_alignment_engine("whisperx")
    assert isinstance(e_wx, WhisperXAlignmentAdapter)

    e_dict = get_alignment_engine({"alignment_engine": "faster-whisper"})
    assert isinstance(e_dict, FasterWhisperAlignmentAdapter)

    class DummyConfig:
        alignment_engine = "whisperx"
        alignment_device = "cpu"

    e_cfg = get_alignment_engine(DummyConfig())
    assert isinstance(e_cfg, WhisperXAlignmentAdapter)
    assert e_cfg.device == "cpu"

    e_auto = get_alignment_engine("auto")
    assert isinstance(e_auto, AlignmentEngine)


def test_factory_get_alignment_engine_resilience_to_non_string():
    from types import SimpleNamespace

    # Integer engine in dict
    e1 = get_alignment_engine({"alignment_engine": 123})
    assert isinstance(e1, AlignmentEngine)

    # None engine in dict
    e2 = get_alignment_engine({"alignment_engine": None})
    assert isinstance(e2, AlignmentEngine)

    # Scalar integer config
    e3 = get_alignment_engine(123)
    assert isinstance(e3, AlignmentEngine)

    # Object with integer engine
    e4 = get_alignment_engine(SimpleNamespace(alignment_engine=1))
    assert isinstance(e4, AlignmentEngine)

    # Direct integer engine argument
    e5 = get_alignment_engine(engine=456)
    assert isinstance(e5, AlignmentEngine)


def test_sanitize_segment_words_none_and_corrupt_timestamps():
    adapter = FasterWhisperAlignmentAdapter()

    # Segment with None timestamps, NaN, string, and inverted values
    corrupt_words = [
        WordTimestamp(word="word1", start=None, end=1.0), # start is None
        WordTimestamp(word="word2", start=float("nan"), end=None), # start is NaN, end is None
        {"word": "word3", "start": "invalid", "end": "2.5", "confidence": "0.8"}, # string values
        {"word": "word4", "start": 3.0, "end": 2.0}, # inverted
    ]

    seg = TranscriptSegment(
        segment_id=1,
        start=0.0,
        end=5.0,
        text="word1 word2 word3 word4",
        words=corrupt_words, # type: ignore
        speaker_tag="SPEAKER_00",
    )

    sanitized = adapter.sanitize_segment_words(seg)
    assert len(sanitized) == 4

    last_end = 0.0
    for w in sanitized:
        assert isinstance(w, WordTimestamp)
        assert not math.isnan(w.start)
        assert not math.isnan(w.end)
        assert not math.isinf(w.start)
        assert not math.isinf(w.end)
        assert w.start >= last_end or math.isclose(w.start, last_end, abs_tol=0.01)
        assert w.end > w.start
        last_end = w.end

