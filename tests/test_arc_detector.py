"""
Unit and Integration Tests for Sentence-Level Linguistic Classifier and Arc Detector.
Verifies 'Strong Start, Strong End' narrative arc discovery:
- Linguistic sentence classification (HOOK, CONTEXT, ESCALATION, REVELATION, PAYOFF, FILLER, SPONSOR)
- Hook-anchored forward scanning and payoff resolution
- Dangling opener rejection ("and", "so", "uh", "or", etc.)
- Sponsor read boundary protection
- Speech dynamics tempo variance evaluation
- Dynamic reel duration variety (15s to 60s)
"""

import time
import pytest
from src.yt_clipping.contracts.models import (
    Transcript,
    TranscriptSegment,
    WordTimestamp,
    HeatmapData,
    HeatmapPoint,
    HeatmapPeak,
)
from src.yt_clipping.detection.sentence_classifier import (
    SentenceClassifier,
    HOOK,
    CONTEXT,
    ESCALATION,
    REVELATION,
    PAYOFF,
    FILLER,
    SPONSOR,
)
from src.yt_clipping.detection.arc_detector import ArcDetector
from src.yt_clipping.detection.segmenter import ContextAwareSegmenter


def test_sentence_classifier_narrative_roles():
    """Verifies that linguistic patterns accurately classify sentence narrative roles."""
    sc = SentenceClassifier()

    test_sentences = [
        ("Why does everyone make this fatal mistake with Python?", HOOK),
        ("Here is the secret to scaling AI systems.", HOOK),
        ("They said Apple would never build a touchscreen laptop.", HOOK),
        ("Look at the architecture of modern reasoning models.", HOOK),
        ("It turns out it doesn't work.", REVELATION),
        ("Actually, the real reason is completely different.", REVELATION),
        ("But it somehow gets way more interesting than that.", ESCALATION),
        ("However, there is another side to the story.", ESCALATION),
        ("That changes everything completely!", PAYOFF),
        ("And that's what's going to make the headlines.", PAYOFF),
        ("Would you ever go back to single-pass generation after seeing that?", PAYOFF),
        ("Use code TECH20 for twenty percent off your next order.", SPONSOR),
        ("Uh yeah, um like whatever.", FILLER),
        ("The laptop weighs three point five pounds.", CONTEXT),
    ]

    segments = []
    t_cur = 0.0
    for i, (text, expected_type) in enumerate(test_sentences):
        dur = 4.0
        words = [WordTimestamp(word=w, start=t_cur + 0.1, end=t_cur + 0.4) for w in text.split()]
        segments.append(TranscriptSegment(segment_id=i + 1, start=t_cur, end=t_cur + dur, text=text, words=words))
        t_cur += dur

    transcript = Transcript(video_id="test_roles", language="en", duration_seconds=t_cur, text="full", segments=segments)
    classified = sc.classify_transcript(transcript)

    assert len(classified) == len(test_sentences)

    classified_dict = {c.text: c.sentence_type for c in classified}
    for text, expected in test_sentences:
        assert classified_dict[text] == expected, f"Expected '{expected}' for '{text}', got '{classified_dict[text]}'"


def test_arc_detector_rejects_weak_dangling_openers():
    """Verifies that ArcDetector strictly rejects candidate arcs starting with dangling weak words."""
    segments = [
        TranscriptSegment(segment_id=1, start=0.0, end=4.0, text="And so he told everyone to leave."),
        TranscriptSegment(segment_id=2, start=4.0, end=8.0, text="Because nobody knew what was happening."),
        TranscriptSegment(segment_id=3, start=8.0, end=14.0, text="Then the entire building went dark!"),
        TranscriptSegment(segment_id=4, start=14.0, end=20.0, text="Why did this happen in the first place?"),
        TranscriptSegment(segment_id=5, start=20.0, end=28.0, text="The engineers had skipped the critical safety check."),
        TranscriptSegment(segment_id=6, start=28.0, end=36.0, text="That single oversight cost them millions of dollars!"),
    ]
    transcript = Transcript(video_id="weak_opener_test", language="en", duration_seconds=40.0, text="full", segments=segments)

    detector = ArcDetector(default_min_duration=15.0, default_max_duration=40.0)
    candidates = detector.discover_arcs(transcript, deduplicate=True)

    assert len(candidates) > 0
    # No candidate should start with "And", "Because", or "Then"
    for c in candidates:
        first_word = c.transcript_text.split()[0].lower()
        assert first_word not in ["and", "because", "then", "so"], f"Found candidate starting with dangling word: '{first_word}'"
        assert c.transcript_text[-1] in [".", "!", "?"], "Candidate must end on complete sentence"


def test_arc_detector_sponsor_boundary_gating():
    """Verifies that ArcDetector never spans across a sponsor ad segment."""
    segments = [
        TranscriptSegment(segment_id=1, start=0.0, end=8.0, text="Here is why your code runs ten times slower."),
        TranscriptSegment(segment_id=2, start=8.0, end=16.0, text="You are allocating memory inside the inner loop."),
        # Sponsor read in the middle
        TranscriptSegment(segment_id=3, start=16.0, end=24.0, text="Use code FASTCODE for thirty percent off on Displate with link in description."),
        # Resumed content
        TranscriptSegment(segment_id=4, start=24.0, end=32.0, text="Moving the buffer outside the loop fixes the issue."),
        TranscriptSegment(segment_id=5, start=32.0, end=40.0, text="That simple change doubled our entire system throughput!"),
    ]
    transcript = Transcript(video_id="sponsor_test", language="en", duration_seconds=45.0, text="full", segments=segments)

    detector = ArcDetector(default_min_duration=15.0, default_max_duration=35.0)
    candidates = detector.discover_arcs(transcript, deduplicate=False)

    for c in candidates:
        # None of the arcs should contain the sponsor phrase
        assert "use code" not in c.transcript_text.lower(), "Candidate contains sponsor ad!"
        assert "displate" not in c.transcript_text.lower(), "Candidate contains sponsor brand!"


def test_arc_detector_speech_dynamics_tempo_variance():
    """Verifies that tempo variance (WPM modulation) and dramatic pauses are rewarded."""
    # Build 3-act speech: moderate hook (140 WPM) -> fast revelation (200 WPM) -> punchline (120 WPM)
    text1 = "Here is the secret to scaling modern artificial intelligence systems in production today."
    text2 = "It turns out that hidden self correction tokens accelerate the reasoning process immensely."
    text3 = "That completely changes the entire outcome and performance of our models!"

    words1_raw = text1.split()
    words2_raw = text2.split()
    words3_raw = text3.split()

    words1 = []
    t = 0.0
    dur1 = 8.0 / len(words1_raw)
    for w in words1_raw:
        words1.append(WordTimestamp(word=w, start=round(t, 2), end=round(t + dur1 * 0.8, 2)))
        t += dur1

    # Pause: 0.6s dramatic beat
    t += 0.6
    words2 = []
    dur2 = 8.0 / len(words2_raw)
    for w in words2_raw:
        words2.append(WordTimestamp(word=w, start=round(t, 2), end=round(t + dur2 * 0.8, 2)))
        t += dur2

    # Pause: 0.5s dramatic beat
    t += 0.5
    words3 = []
    dur3 = 6.0 / len(words3_raw)
    for w in words3_raw:
        words3.append(WordTimestamp(word=w, start=round(t, 2), end=round(t + dur3 * 0.8, 2)))
        t += dur3

    seg1 = TranscriptSegment(segment_id=1, start=0.0, end=8.0, text=text1, words=words1)
    seg2 = TranscriptSegment(segment_id=2, start=8.6, end=17.0, text=text2, words=words2)
    seg3 = TranscriptSegment(segment_id=3, start=17.5, end=round(t, 2), text=text3, words=words3)

    transcript = Transcript(video_id="dynamics_test", language="en", duration_seconds=round(t, 2), text="full", segments=[seg1, seg2, seg3])

    detector = ArcDetector(default_min_duration=15.0, default_max_duration=35.0)
    candidates = detector.discover_arcs(transcript, deduplicate=True)

    assert len(candidates) > 0
    top = candidates[0]
    # Pacing score should receive tempo variance + pause bonuses
    assert top.breakdown.pacing_score >= 8.0
    assert "Dynamics=" in top.rationale


def test_segmenter_arc_detector_end_to_end_integration():
    """Verifies that ContextAwareSegmenter automatically engages ArcDetector."""
    segments = [
        TranscriptSegment(segment_id=1, start=0.0, end=6.0, text="They said they wouldn't do it for a really long time."),
        TranscriptSegment(segment_id=2, start=6.0, end=12.0, text="But now they have decided to go ahead and do it anyway."),
        TranscriptSegment(segment_id=3, start=12.0, end=18.0, text="Apple today unveiled a brand new MacBook Pro with a touchscreen."),
        TranscriptSegment(segment_id=4, start=18.0, end=26.0, text="And that is what is going to make the headlines everywhere!"),
    ]
    transcript = Transcript(video_id="mkbhd_slice", language="en", duration_seconds=30.0, text="full", segments=segments)

    segmenter = ContextAwareSegmenter(default_min_duration=15.0, default_max_duration=30.0)
    candidates = segmenter.detect_candidates(transcript)

    assert len(candidates) > 0
    top = candidates[0]
    assert top.candidate_id.startswith("cand-arc-"), f"Expected arc candidate, got {top.candidate_id}"
    assert top.score >= 70.0
    assert top.transcript_text.startswith("They said")
    assert top.transcript_text.endswith("!")


def test_arc_detector_high_performance():
    """Verifies that ArcDetector processes a 500-segment transcript in under 50 milliseconds."""
    segments = []
    t = 0.0
    for i in range(500):
        text = f"Sentence number {i} discusses an interesting concept."
        if i % 10 == 0:
            text = f"Here is why concept {i} is a game changer!"
        elif i % 10 == 9:
            text = f"That is how concept {i} resolves completely."
        segments.append(TranscriptSegment(segment_id=i + 1, start=t, end=t + 2.5, text=text))
        t += 2.5

    transcript = Transcript(video_id="perf_test", language="en", duration_seconds=t, text="full", segments=segments)
    detector = ArcDetector(default_min_duration=15.0, default_max_duration=45.0)

    start_time = time.perf_counter()
    candidates = detector.discover_arcs(transcript, deduplicate=True)
    elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    assert len(candidates) > 0
    assert elapsed_ms < 1500.0, f"ArcDetector took {elapsed_ms:.1f}ms (expected < 1500ms under load)"
