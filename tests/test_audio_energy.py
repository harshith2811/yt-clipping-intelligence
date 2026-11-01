"""
Unit and Integration Tests for Real Acoustic Energy, Motion Signal Grounding, and Adaptive Cadence.
Verifies Phase 1 and Phase 2 Implementation:
- Fast FFmpeg 16kHz PCM audio extraction and continuous short-time RMS energy envelope.
- Normalized energy Z_E, transition contrast Delta Z_E, dynamic range DR_E = p90 - p10.
- Non-linear sigmoid audio scoring [0.0, 10.0] and graceful 7.0 fallback.
- Downscaled 1fps inter-frame motion analyzer and graceful 8.0 fallback.
- Adaptive relative cadence deviation Z_R, fluency baseline F_fluency, and modulation dynamic M_dynamic.
- Conversational boundary repair (acoustic pause > 0.35s).
- Zodiac keyword purging in captions sentiment dictionary.
- Measured acoustic and motion score propagation into ArcDetector and ExplainableScorecardScorer.
"""

import os
import math
import numpy as np
import pytest

from src.yt_clipping.contracts.models import (
    Transcript,
    TranscriptSegment,
    WordTimestamp,
    HighlightCandidate,
    ScoreBreakdown,
)
from src.yt_clipping.detection.audio_energy import (
    AudioEnergyAnalyzer,
    MotionEnergyAnalyzer,
    AdaptiveCadenceScorer,
    extract_pcm_from_file,
    compute_words_speech_rate,
)
from src.yt_clipping.detection.arc_detector import ArcDetector
from src.yt_clipping.scoring.scorecard import ExplainableScorecardScorer
from src.yt_clipping.rendering.captions import (
    DANGER_KEYWORDS,
    MYSTERY_KEYWORDS,
    EMOJI_KEYWORDS,
)


def test_audio_energy_synthetic_pcm_envelope():
    """Verifies continuous RMS energy, Z_E, transition contrast, and sigmoid scoring on synthetic PCM."""
    sr = 16000
    dur = 6.0
    total_samples = int(sr * dur)
    t = np.linspace(0, dur, total_samples, endpoint=False)

    # Signal structure:
    # 0.0s - 2.0s: quiet tone (amplitude 0.05)
    # 2.0s - 2.5s: silence (amplitude 0.0001)
    # 2.5s - 4.5s: loud tone / explosive burst (amplitude 0.90)
    # 4.5s - 6.0s: moderate tone (amplitude 0.20)
    samples = np.zeros(total_samples, dtype=np.float32)
    samples[: int(2.0 * sr)] = 0.05 * np.sin(2 * np.pi * 440 * t[: int(2.0 * sr)])
    samples[int(2.0 * sr) : int(2.5 * sr)] = 0.0001
    samples[int(2.5 * sr) : int(4.5 * sr)] = 0.90 * np.sin(2 * np.pi * 880 * t[int(2.5 * sr) : int(4.5 * sr)])
    samples[int(4.5 * sr) :] = 0.20 * np.sin(2 * np.pi * 440 * t[int(4.5 * sr) :])

    pcm_bytes = (samples * 32767.0).astype(np.int16).tobytes()

    analyzer = AudioEnergyAnalyzer(pcm_data=pcm_bytes, sample_rate=sr, hop_sec=0.05, win_sec=0.10, delta_sec=0.50)

    assert analyzer.is_available is True
    assert len(analyzer.energy_db) > 50
    assert len(analyzer.z_energy) == len(analyzer.energy_db)
    assert len(analyzer.delta_z) == len(analyzer.energy_db)

    # Dynamic range (p90 - p10) must be significant
    assert analyzer.dynamic_range_e > 10.0
    assert analyzer.std_e > 1.0

    # Quiet section [0.5s - 1.5s] vs explosive burst [2.5s - 4.0s]
    quiet_score = analyzer.evaluate_interval(0.5, 1.5)
    burst_score = analyzer.evaluate_interval(2.5, 4.0)

    assert 0.0 <= quiet_score <= 10.0
    assert 0.0 <= burst_score <= 10.0
    assert burst_score > quiet_score
    assert burst_score >= 8.0, f"Expected high score for explosive burst, got {burst_score}"


def test_audio_energy_ffmpeg_real_media_pipeline():
    """Verifies sub-second FFmpeg 16kHz PCM extraction from a real media asset."""
    real_sample = "data/assets/real_test_sample.mp4"
    if not os.path.exists(real_sample):
        pytest.skip(f"Test media file {real_sample} not found on local disk.")

    analyzer = AudioEnergyAnalyzer(media_path=real_sample)
    assert analyzer.is_available is True
    assert len(analyzer.energy_db) > 0
    assert analyzer.mean_e < 0.0  # dBFS is negative

    score = analyzer.evaluate_interval(0.0, 2.0)
    assert 0.0 <= score <= 10.0


def test_audio_energy_graceful_fallback():
    """Verifies graceful fallback to 7.0 for missing, empty, or corrupted media."""
    missing_analyzer = AudioEnergyAnalyzer(media_path="nonexistent_corrupted_video.mp4")
    assert missing_analyzer.is_available is False
    assert missing_analyzer.evaluate_interval(0.0, 10.0) == 7.0

    empty_analyzer = AudioEnergyAnalyzer(pcm_data=b"")
    assert empty_analyzer.is_available is False
    assert empty_analyzer.evaluate_interval(0.0, 5.0) == 7.0

    # Invalid interval bounds on initialized analyzer
    sr = 16000
    dummy_samples = (np.zeros(sr * 2, dtype=np.int16)).tobytes()
    valid_analyzer = AudioEnergyAnalyzer(pcm_data=dummy_samples)
    assert valid_analyzer.evaluate_interval(5.0, 2.0) == 7.0  # start >= end
    assert valid_analyzer.evaluate_interval(-1.0, -0.5) == 7.0  # negative end


def test_motion_energy_analyzer_and_fallback():
    """Verifies visual motion energy analysis and graceful 8.0 fallback."""
    # Synthetic frame diffs
    diffs = np.array([2.0, 3.5, 15.0, 22.0, 5.0, 4.0], dtype=np.float32)
    analyzer = MotionEnergyAnalyzer(frame_diffs=diffs, fps=1)

    assert analyzer.is_available is True
    assert analyzer.mean_motion > 0.0

    score_action = analyzer.evaluate_interval(2.0, 4.0)  # High motion spike
    score_static = analyzer.evaluate_interval(0.0, 2.0)  # Low motion

    assert 0.0 <= score_action <= 10.0
    assert 0.0 <= score_static <= 10.0
    assert score_action > score_static

    # Fallback when video is missing
    missing_motion = MotionEnergyAnalyzer(video_path="nonexistent_video.mp4")
    assert missing_motion.is_available is False
    assert missing_motion.evaluate_interval(0.0, 10.0) == 8.0


def test_adaptive_cadence_scorer_fast_speaker():
    """
    Verifies that a fast creator (e.g. Marques Brownlee at ~226 WPM)
    is rewarded for relational fluency rather than penalized by static 135-185 brackets.
    """
    # 5 segments at ~220-230 WPM
    segments = []
    t = 0.0
    target_wpm = 225.0
    words_per_sec = target_wpm / 60.0  # 3.75 words/sec

    for i in range(5):
        num_w = 15
        dur = num_w / words_per_sec  # 4.0 sec
        words = []
        for w_idx in range(num_w):
            w_start = round(t + (w_idx / words_per_sec), 2)
            w_end = round(w_start + 0.22, 2)
            words.append(WordTimestamp(word=f"word{w_idx}", start=w_start, end=w_end))
        segments.append(
            TranscriptSegment(
                segment_id=i + 1,
                start=round(t, 2),
                end=round(t + dur, 2),
                text=f"Fast segment {i} speaking at creator baseline rate.",
                words=words,
            )
        )
        t += dur + 0.1  # small gap

    transcript = Transcript(
        video_id="mkbhd_fast",
        language="en",
        duration_seconds=round(t, 2),
        text="Fast speech",
        segments=segments,
    )

    scorer = AdaptiveCadenceScorer(transcript)
    assert scorer.is_available is True
    assert 210.0 <= scorer.mu_r <= 240.0

    # Candidate at speaker's own baseline (~225 WPM)
    cand_words = segments[1].words + segments[2].words
    cand_dur = segments[2].end - segments[1].start
    cand_score = scorer.score_cadence(words=cand_words, duration=cand_dur)

    # Under static bracket (210-240 WPM), score would be 5.5.
    # Under adaptive relative model, score must be >= 7.5 (fluency is 1.0)
    assert cand_score >= 7.5, f"Expected high relational cadence score, got {cand_score}"


def test_adaptive_cadence_scorer_slow_speaker_and_stutter_penalty():
    """
    Verifies that a slow conversational speaker (e.g. Lex Fridman at ~140 WPM)
    scores high with natural modulation, but is penalized for extreme stutter/hesitation deviation.
    """
    segments = []
    t = 0.0
    durs = [6.0, 5.0, 6.5, 5.2, 5.8]  # Natural pacing variations (~130 - 160 WPM)

    for i, dur in enumerate(durs):
        num_w = 14
        words = []
        w_step = (dur - 0.5) / num_w
        for w_idx in range(num_w):
            w_start = round(t + (w_idx * w_step), 2)
            w_end = round(w_start + 0.25, 2)
            words.append(WordTimestamp(word=f"slow{w_idx}", start=w_start, end=w_end))
        segments.append(
            TranscriptSegment(
                segment_id=i + 1,
                start=round(t, 2),
                end=round(t + dur, 2),
                text=f"Slow thoughtful segment {i}.",
                words=words,
            )
        )
        t += dur + 0.4  # thoughtful pause

    transcript = Transcript(
        video_id="lex_slow",
        language="en",
        duration_seconds=round(t, 2),
        text="Slow thoughtful speech",
        segments=segments,
    )

    scorer = AdaptiveCadenceScorer(transcript)
    assert scorer.is_available is True
    assert 120.0 <= scorer.mu_r <= 180.0

    # Normal candidate at baseline
    normal_words = segments[0].words + segments[1].words
    normal_dur = segments[1].end - segments[0].start
    normal_score = scorer.score_cadence(words=normal_words, duration=normal_dur)
    assert normal_score >= 7.5

    # Stutter / extreme hesitation candidate (only 3 words across 10 seconds -> 18 WPM)
    stutter_words = [
        WordTimestamp(word="uh", start=10.0, end=10.4),
        WordTimestamp(word="maybe", start=14.0, end=14.6),
        WordTimestamp(word="yeah", start=18.0, end=18.5),
    ]
    stutter_score = scorer.score_cadence(words=stutter_words, duration=10.0)
    # Fluency is heavily penalized for ~18 WPM against 140 WPM baseline
    assert stutter_score < normal_score
    assert stutter_score <= 5.0, f"Expected penalized score for stutter, got {stutter_score}"


def test_adaptive_cadence_fallback_without_timestamps():
    """Verifies graceful fallback to static brackets when transcript lacks word timestamps."""
    transcript_no_words = Transcript(
        video_id="no_words",
        language="en",
        duration_seconds=60.0,
        text="Some text without word timestamps.",
        segments=[
            TranscriptSegment(segment_id=1, start=0.0, end=30.0, text="First half without words", words=[]),
            TranscriptSegment(segment_id=2, start=30.0, end=60.0, text="Second half without words", words=[]),
        ],
    )

    scorer = AdaptiveCadenceScorer(transcript_no_words)
    assert scorer.is_available is False

    # 150 WPM should hit 9.5 static fallback
    # 50 words in 20s = 150 WPM
    score_optimal = scorer.score_cadence(words=[], duration=20.0, num_words=50)
    assert score_optimal == 9.5

    # 300 WPM should hit 3.5 static fallback
    score_too_fast = scorer.score_cadence(words=[], duration=10.0, num_words=50)
    assert score_too_fast == 3.5


def test_conversational_boundary_repair_with_pause():
    """
    Verifies that ArcDetector permits conversational openings (e.g. starting with 'so')
    when preceded by an acoustic pause boundary (> 0.35s silence), while pruning them without pause.
    """
    # 1. Transcript with 1.0s acoustic pause before conversational 'so'
    segments_with_pause = [
        TranscriptSegment(segment_id=1, start=0.0, end=4.0, text="Uh yeah ok."),  # FILLER prefix
        # 1.0s pause (4.0 to 5.0)
        TranscriptSegment(segment_id=2, start=5.0, end=14.0, text="So they finally redesigned the entire propulsion system."),
        TranscriptSegment(segment_id=3, start=14.0, end=22.0, text="The new engine delivered unprecedented thermal efficiency."),
        TranscriptSegment(segment_id=4, start=22.0, end=30.0, text="That single innovation changed commercial aviation completely!"),
    ]
    transcript_pause = Transcript(
        video_id="conversational_pause_test",
        language="en",
        duration_seconds=32.0,
        text="full",
        segments=segments_with_pause,
    )

    detector = ArcDetector(default_min_duration=15.0, default_max_duration=30.0)
    candidates_with_pause = detector.discover_arcs(transcript_pause, deduplicate=True)

    assert len(candidates_with_pause) > 0
    so_cands = [c for c in candidates_with_pause if c.transcript_text.lower().startswith("so ")]
    assert len(so_cands) > 0, "Expected ArcDetector to accept 'So' opener when preceded by > 0.35s pause"

    # 2. Same transcript WITHOUT pause (pause = 0.0s)
    segments_no_pause = [
        TranscriptSegment(segment_id=1, start=0.0, end=4.0, text="Uh yeah ok."),
        # 0.0s pause (starts immediately at 4.0)
        TranscriptSegment(segment_id=2, start=4.0, end=14.0, text="So they finally redesigned the entire propulsion system."),
        TranscriptSegment(segment_id=3, start=14.0, end=22.0, text="The new engine delivered unprecedented thermal efficiency."),
        TranscriptSegment(segment_id=4, start=22.0, end=30.0, text="That single innovation changed commercial aviation completely!"),
    ]
    transcript_no_pause = Transcript(
        video_id="conversational_no_pause_test",
        language="en",
        duration_seconds=32.0,
        text="full",
        segments=segments_no_pause,
    )

    candidates_no_pause = detector.discover_arcs(transcript_no_pause, deduplicate=True)
    so_cands_no_pause = [c for c in candidates_no_pause if c.transcript_text.lower().startswith("so ")]
    assert len(so_cands_no_pause) == 0, "ArcDetector should prune dangling 'So' opener without pause boundary"


def test_captions_zodiac_keywords_purged():
    """Verifies that Zodiac-specific test keywords are purged from caption styling tables."""
    assert "ZODIAC" not in DANGER_KEYWORDS
    assert "ZODIAC" not in MYSTERY_KEYWORDS
    assert "CIPHER" not in MYSTERY_KEYWORDS
    assert "ENVELOPE" not in MYSTERY_KEYWORDS
    assert "CIPHER" not in EMOJI_KEYWORDS


def test_measured_audio_and_visual_scorecard_propagation():
    """
    Verifies that measured acoustic and motion scores propagate directly into
    ExplainableScorecardScorer and ArcDetector ScoreBreakdown.
    """
    # Create synthetic audio analyzer that produces 9.2
    sr = 16000
    dur = 4.0
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    samples = 0.9 * np.sin(2 * np.pi * 880 * t)
    pcm = (samples * 32767.0).astype(np.int16).tobytes()
    audio_analyzer = AudioEnergyAnalyzer(pcm_data=pcm, sample_rate=sr)

    # Synthetic motion analyzer that produces ~9.0
    motion_analyzer = MotionEnergyAnalyzer(frame_diffs=np.array([12.0, 18.0, 24.0, 16.0]))

    scorer = ExplainableScorecardScorer(audio_analyzer=audio_analyzer, motion_analyzer=motion_analyzer)

    transcript = Transcript(
        video_id="measure_test",
        language="en",
        duration_seconds=30.0,
        text="The secret to scaling AI models is surprisingly simple.",
    )
    candidate = HighlightCandidate(
        candidate_id="c_prop",
        video_id="measure_test",
        start_seconds=1.0,
        end_seconds=20.0,
        duration_seconds=19.0,
        score=0.0,
        breakdown=ScoreBreakdown(),
        hook_title="Opening hook",
        transcript_text="The secret to scaling AI models is surprisingly simple. Most teams fail because they rush.",
    )

    scored = scorer.score_candidate(candidate, transcript)

    # Measured scores should be used instead of dummy 7.0 and 8.0
    assert scored.breakdown.audio_energy_score != 7.0 or not audio_analyzer.is_available
    assert scored.breakdown.audio_energy_score > 0.0
    assert scored.breakdown.visual_score != 8.0 or not motion_analyzer.is_available
    assert scored.breakdown.visual_score > 0.0


def test_audio_energy_odd_buffer_and_out_of_bounds():
    """Verifies that odd PCM buffers do not raise exceptions and out-of-bounds intervals return 7.0 fallback."""
    sr = 16000
    dur = 2.0
    samples = (0.5 * np.sin(2 * np.pi * 440 * np.linspace(0, dur, int(sr * dur))) * 32767.0).astype(np.int16).tobytes()
    # Create odd buffer by appending 1 trailing byte
    odd_pcm = samples + b"\x01"
    assert len(odd_pcm) % 2 == 1

    analyzer = AudioEnergyAnalyzer(pcm_data=odd_pcm, sample_rate=sr)
    assert analyzer.is_available is True

    # Interval completely past audio stream duration
    score_past = analyzer.evaluate_interval(10.0, 15.0)
    assert score_past == 7.0, f"Expected fallback 7.0 for interval past audio, got {score_past}"

    # Interval completely before audio stream
    score_before = analyzer.evaluate_interval(-5.0, -1.0)
    assert score_before == 7.0, f"Expected fallback 7.0 for interval before audio, got {score_before}"

    # Sub-hop interval inside audio (e.g. 0.02s < 0.05s hop)
    score_subhop = analyzer.evaluate_interval(0.50, 0.52)
    assert 0.0 <= score_subhop <= 10.0


def test_motion_energy_subframe_interval_and_out_of_bounds():
    """Verifies motion evaluation for subframe intervals and out-of-bounds fallback."""
    diffs = np.array([2.0, 10.0, 20.0, 15.0, 3.0], dtype=np.float32)
    # 5 frames at 1fps: frame_times are 0, 1, 2, 3, 4
    analyzer = MotionEnergyAnalyzer(frame_diffs=diffs, fps=1)

    # Completely outside video duration
    assert analyzer.evaluate_interval(10.0, 15.0) == 8.0
    assert analyzer.evaluate_interval(-5.0, -2.0) == 8.0

    # Narrow interval falling between integer seconds (e.g. 1.2s to 1.8s)
    # Should evaluate closest frame (frame 1 or 2) rather than dropping to 8.0 fallback
    score_between = analyzer.evaluate_interval(1.2, 1.8)
    assert 0.0 <= score_between <= 10.0
    # Frame 1 and 2 have high motion (10 and 20), so score should reflect high motion
    assert score_between > 8.0


def test_speech_rate_overlapping_words():
    """Verifies that compute_words_speech_rate merges overlapping word intervals without inflating pauses."""
    # Word 0: 0.0 to 1.5
    # Word 1: 1.0 to 2.0 (overlaps word 0)
    # Word 2: 3.0 to 4.0 (gap of 1.0s after word 1 ends at 2.0)
    words = [
        WordTimestamp(word="hello", start=0.0, end=1.5),
        WordTimestamp(word="world", start=1.0, end=2.0),
        WordTimestamp(word="testing", start=3.0, end=4.0),
    ]
    wpm, active_speech = compute_words_speech_rate(words)

    # Total span = 4.0 - 0.0 = 4.0s
    # Active speech should be [0.0, 2.0] (2.0s) + [3.0, 4.0] (1.0s) = 3.0s
    # Pause is [2.0, 3.0] = 1.0s (> 0.25s)
    assert abs(active_speech - 3.0) < 0.1
    # 3 words in 3.0s active speech = 1 word/sec = 60 WPM
    assert abs(wpm - 60.0) < 2.0


def test_cadence_single_long_segment_calibration():
    """Verifies that AdaptiveCadenceScorer subdivides long segments into windows to calibrate true baseline."""
    # Create 1 long segment with 30 words
    words = []
    t = 0.0
    for i in range(30):
        words.append(WordTimestamp(word=f"word{i}", start=round(t, 2), end=round(t + 0.25, 2)))
        t += 0.35  # ~170 WPM

    long_seg = TranscriptSegment(
        segment_id=1,
        start=0.0,
        end=round(t, 2),
        text=" ".join(f"word{i}" for i in range(30)),
        words=words,
    )
    transcript = Transcript(
        video_id="long_seg_test",
        language="en",
        duration_seconds=round(t, 2),
        text="full",
        segments=[long_seg],
    )

    scorer = AdaptiveCadenceScorer(transcript)
    assert scorer.is_available is True
    assert 140.0 <= scorer.mu_r <= 200.0


def test_media_path_constructor_and_scorecard_auto_init():
    """Verifies that ExplainableScorecardScorer and ArcDetector accept media_path and auto-initialize analyzers."""
    real_sample = "data/assets/real_test_sample.mp4"
    if not os.path.exists(real_sample):
        pytest.skip(f"Test media {real_sample} not found.")

    detector = ArcDetector(media_path=real_sample)
    assert detector.audio_analyzer is not None
    assert detector.audio_analyzer.is_available is True
    assert detector.motion_analyzer is not None
    assert detector.motion_analyzer.is_available is True

    scorer = ExplainableScorecardScorer(media_path=real_sample)
    assert scorer.audio_analyzer is not None
    assert scorer.audio_analyzer.is_available is True
    assert scorer.motion_analyzer is not None
    assert scorer.motion_analyzer.is_available is True

