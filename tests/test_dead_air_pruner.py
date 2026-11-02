"""
Unit tests for DeadAirPruner:
- Dead air gap trimming (> 0.35s)
- Standalone filler token detection and pruning ('um', 'uh', 'so yeah', 'basically', 'you know')
- Sentence restart detection (first 3-5 normalized words matching)
- Pacing tightness score computation
- Micro-jump-cut keep interval and FFmpeg filter generation
"""

import pytest
from src.yt_clipping.contracts.models import (
    WordTimestamp,
    TranscriptSegment,
    Transcript,
    HighlightCandidate,
    ScoreBreakdown,
)
from src.yt_clipping.detection.deadair import (
    DeadAirPruner,
    DeadAirGap,
    FillerOccurrence,
    SentenceRestart,
    PruneResult,
)


def test_dead_air_gap_detection_threshold():
    pruner = DeadAirPruner(dead_air_threshold=0.35)

    words = [
        WordTimestamp(word="First", start=0.0, end=0.5),
        WordTimestamp(word="word", start=0.6, end=1.0),    # Gap: 0.1s <= 0.35s (normal pause)
        WordTimestamp(word="then", start=1.5, end=2.0),    # Gap: 0.5s > 0.35s (DEAD AIR)
        WordTimestamp(word="silence", start=2.1, end=2.5), # Gap: 0.1s <= 0.35s
        WordTimestamp(word="again", start=3.5, end=4.0),   # Gap: 1.0s > 0.35s (DEAD AIR)
    ]

    gaps = pruner.detect_dead_air_gaps(words)
    assert len(gaps) == 2
    assert gaps[0].start == 1.0
    assert gaps[0].end == 1.5
    assert abs(gaps[0].duration - 0.5) < 0.01

    assert gaps[1].start == 2.5
    assert gaps[1].end == 3.5
    assert abs(gaps[1].duration - 1.0) < 0.01


def test_filler_token_detection():
    pruner = DeadAirPruner()

    words = [
        WordTimestamp(word="Um", start=0.0, end=0.3),
        WordTimestamp(word="I", start=0.4, end=0.6),
        WordTimestamp(word="think", start=0.6, end=0.9),
        WordTimestamp(word="uh", start=1.0, end=1.2),
        WordTimestamp(word="this", start=1.3, end=1.5),
        WordTimestamp(word="is", start=1.5, end=1.7),
        WordTimestamp(word="so", start=1.8, end=2.0),
        WordTimestamp(word="yeah", start=2.0, end=2.2),
        WordTimestamp(word="basically", start=2.3, end=2.7),
        WordTimestamp(word="cool", start=2.8, end=3.1),
        WordTimestamp(word="you", start=3.2, end=3.4),
        WordTimestamp(word="know?", start=3.4, end=3.7),
    ]

    fillers = pruner.detect_fillers(words)
    # Expected: "Um", "uh", "so yeah", "basically", "you know?"
    assert len(fillers) == 5

    phrases = [f.phrase.lower().replace("?", "") for f in fillers]
    assert "um" in phrases
    assert "uh" in phrases
    assert "so yeah" in phrases
    assert "basically" in phrases
    assert "you know" in phrases


def test_sentence_restart_detection():
    pruner = DeadAirPruner()

    cues = [
        TranscriptSegment(
            segment_id=1,
            start=0.0,
            end=2.5,
            text="We wanted to build this new engine",
        ),
        TranscriptSegment(
            segment_id=2,
            start=2.8,
            end=6.0,
            text="We wanted to build this new engine from scratch because it failed.",
        ),
        TranscriptSegment(
            segment_id=3,
            start=6.5,
            end=9.0,
            text="And that solved the whole bottleneck.",
        ),
    ]

    restarts = pruner.detect_restarts(cues, min_prefix_words=3, max_prefix_words=5)
    assert len(restarts) == 1
    restart = restarts[0]
    assert restart.matching_prefix == ["we", "wanted", "to", "build", "this"]
    assert restart.prefix_length == 5
    assert restart.prev_text == "We wanted to build this new engine"
    assert "from scratch" in restart.curr_text


def test_pacing_tightness_score_calculation():
    pruner = DeadAirPruner()

    # Perfectly tight delivery: 0s dead air, 0 fillers, 0 restarts
    clean_score = pruner.calculate_pacing_tightness_score(
        duration=30.0,
        dead_air_duration=0.0,
        filler_count=0,
        restart_count=0,
    )
    assert clean_score == 10.0

    # Sloppy delivery: 8s dead air in 20s, 3 fillers, 1 restart
    sloppy_score = pruner.calculate_pacing_tightness_score(
        duration=20.0,
        dead_air_duration=8.0,
        filler_count=3,
        restart_count=1,
    )
    # 10.0 - (8/20 * 12.0) - (3 * 0.6) - (1 * 1.5) = 10.0 - 4.8 - 1.8 - 1.5 = 1.9
    assert sloppy_score < 4.0
    assert sloppy_score > 0.0


def test_micro_jump_cuts_and_keep_intervals():
    pruner = DeadAirPruner(dead_air_threshold=0.35, target_pause=0.15)

    words = [
        WordTimestamp(word="Here", start=0.0, end=0.4),
        WordTimestamp(word="is", start=0.45, end=0.7),
        # Gap: 2.0s - 0.7s = 1.3s (> 0.35s dead air)
        WordTimestamp(word="the", start=2.0, end=2.3),
        WordTimestamp(word="payoff.", start=2.35, end=2.8),
    ]

    res = pruner.prune_words(words, clip_start=0.0, clip_end=2.8)
    assert len(res.dead_air_gaps) == 1
    assert res.original_duration == 2.8
    # Keep intervals should compress the pause:
    # First chunk keeps [0.0, 0.7 + 0.15 = 0.85]
    # Second chunk keeps [2.0, 2.8]
    assert len(res.keep_intervals) == 2
    assert res.keep_intervals[0][0] == 0.0
    assert abs(res.keep_intervals[0][1] - 0.85) < 0.05
    assert abs(res.keep_intervals[1][0] - 2.0) < 0.05
    assert abs(res.keep_intervals[1][1] - 2.8) < 0.05

    # FFmpeg filter check
    ffmpeg_filter = pruner.generate_ffmpeg_select_filter(res.keep_intervals)
    assert "between(t,0.000," in ffmpeg_filter
    assert "between(t,2.000,2.800)" in ffmpeg_filter
    assert "aselect" in ffmpeg_filter
    assert "select" in ffmpeg_filter


def test_edge_cases_empty_and_single_word():
    pruner = DeadAirPruner()

    # Empty words
    res_empty = pruner.prune_words([])
    assert res_empty.original_duration == 0.0
    assert len(res_empty.keep_intervals) == 0

    # Single word
    w_single = [WordTimestamp(word="Hello", start=1.0, end=1.5)]
    res_single = pruner.prune_words(w_single, clip_start=1.0, clip_end=1.5)
    assert len(res_single.dead_air_gaps) == 0
    assert len(res_single.keep_intervals) == 1
    assert res_single.pacing_tightness_score == 10.0


def test_leading_and_trailing_dead_air_trimming():
    pruner = DeadAirPruner(dead_air_threshold=0.35, target_pause=0.15)
    # Clip from 0.0 to 10.0 with 3.0s leading silence and 3.0s trailing silence
    words = [
        WordTimestamp(word="Hello", start=3.0, end=3.5),
        WordTimestamp(word="World", start=3.6, end=7.0),
    ]
    res = pruner.prune_words(words, clip_start=0.0, clip_end=10.0)
    assert len(res.dead_air_gaps) == 2  # Leading + trailing
    assert res.dead_air_duration >= 5.5
    # Tightness score should be heavily penalized for 60% silence
    assert res.pacing_tightness_score < 5.0
    # Keep intervals should trim leading silence to (3.0 - 0.15) and trailing silence to (7.0 + 0.15)
    assert len(res.keep_intervals) == 1
    k_start, k_end = res.keep_intervals[0]
    assert abs(k_start - 2.85) < 0.05
    assert abs(k_end - 7.15) < 0.05


def test_restarts_outside_clip_bounds_do_not_corrupt_keep_intervals():
    pruner = DeadAirPruner()
    words = [WordTimestamp("hello", 10.0, 10.5), WordTimestamp("world", 10.6, 11.0)]
    cues = [
        TranscriptSegment(1, 10.0, 11.0, "hello world", []),
        TranscriptSegment(2, 50.0, 52.0, "we wanted to", []),
        TranscriptSegment(3, 52.5, 56.0, "we wanted to build this", []),
    ]
    res = pruner.prune_words(words, cues=cues, clip_start=10.0, clip_end=15.0)
    # Crucial: Keep intervals must NOT expand beyond 15.0
    for s, e in res.keep_intervals:
        assert s >= 10.0
        assert e <= 15.0


def test_select_filter_with_relative_offset():
    pruner = DeadAirPruner()
    keep_intervals = [(100.0, 105.0), (110.0, 115.0)]
    # With offset_seconds = 100.0, output should shift to 0.0 and 10.0
    v_expr, a_expr = pruner.generate_select_expressions(keep_intervals, offset_seconds=100.0)
    assert "between(t,0.000,5.000)" in v_expr
    assert "between(t,10.000,15.000)" in v_expr
    assert "between(t,0.000,5.000)" in a_expr
    assert "between(t,10.000,15.000)" in a_expr

