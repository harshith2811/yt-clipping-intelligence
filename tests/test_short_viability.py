"""
Unit tests for ShortViabilityValidator ('yt-shorts' rule):
- Complete Thought Opening (rejecting dangling pronouns without context)
- The Narrative Turn (claim followed by proof, complication, or emotional shift)
- Clean Resolution (rejecting trailing fragments and unfinished sentences)
- Loop Hook continuity (syntactic and thematic loops)
"""

import pytest
from src.yt_clipping.contracts.models import (
    HighlightCandidate,
    ScoreBreakdown,
    Transcript,
    TranscriptSegment,
)
from src.yt_clipping.detection.short_viability import (
    ShortViabilityValidator,
    ViabilityCheckResult,
)


def test_complete_thought_opening_validation():
    validator = ShortViabilityValidator()

    # 1. Dangling pronoun without referent -> FAIL
    ok_he, crit_he = validator.validate_complete_thought_opening("He told me that we needed to rewrite everything.")
    assert ok_he is False
    assert "dangling pronoun 'he'" in crit_he

    # 2. Dangling demonstrative -> FAIL
    ok_that, crit_that = validator.validate_complete_thought_opening("That thing caused an unexpected memory leak.")
    assert ok_that is False
    assert "dangling demonstrative 'that thing'" in crit_that

    # 3. Complete standalone opening -> PASS
    ok_sub, crit_sub = validator.validate_complete_thought_opening("Docker containers often encounter thread contention under heavy load.")
    assert ok_sub is True

    # 4. Intentional provocative collective hook ("They said you couldn't...") -> PASS
    ok_they, crit_they = validator.validate_complete_thought_opening("They said you couldn't run a 70B model on a single GPU.")
    assert ok_they is True


def test_narrative_turn_validation():
    validator = ShortViabilityValidator()

    # 1. Monotonic statement lacking proof or complication -> FAIL
    boring_text = "Python is a programming language created by Guido van Rossum many years ago."
    ok_mono, crit_mono = validator.validate_narrative_turn(boring_text)
    assert ok_mono is False

    # 2. Setup with complication and proof -> PASS
    turn_text = (
        "Most engineers think indexing every database column speeds up queries. "
        "The problem is write performance plummets, because every insert requires updating B-trees."
    )
    ok_turn, crit_turn = validator.validate_narrative_turn(turn_text)
    assert ok_turn is True
    assert "Narrative turn present" in crit_turn


def test_clean_resolution_validation():
    validator = ShortViabilityValidator()

    # 1. Trailing conjunction fragment -> FAIL
    bad_trailing = "We realized that the cache wasn't persisting and so"
    ok_trail, crit_trail = validator.validate_clean_resolution(bad_trailing)
    assert ok_trail is False
    assert "trailing conjunction/fragment 'so'" in crit_trail

    # 2. Trailing ellipsis -> FAIL
    bad_ellipsis = "The final result was completely unexpected..."
    ok_ell, crit_ell = validator.validate_clean_resolution(bad_ellipsis)
    assert ok_ell is False
    assert "unfinished ellipsis" in crit_ell

    # 3. Clean declarative resolution -> PASS
    good_resolution = "That simple one-line configuration change cut our cloud bill by forty percent."
    ok_clean, crit_clean = validator.validate_clean_resolution(good_resolution)
    assert ok_clean is True

    # 4. Definitive punchline payoff -> PASS
    good_payoff = "And that is why you never store raw passwords."
    ok_pay, crit_pay = validator.validate_clean_resolution(good_payoff)
    assert ok_pay is True


def test_loop_hook_continuity():
    validator = ShortViabilityValidator()

    # Seamless loop: ending leads directly into opening
    opening = "Python is dramatically slower than C++ for matrix multiplication."
    closing = "And here is the reason why..."

    score, critique, suggestion = validator.evaluate_loop_hook(opening, closing)
    assert score >= 8.5
    assert "syntactic loop" in critique.lower() or "seamless" in critique.lower()


def test_candidate_viability_full_audit():
    validator = ShortViabilityValidator()

    # Valid standalone Short candidate
    valid_cand = HighlightCandidate(
        candidate_id="c_viable",
        video_id="v_viable",
        start_seconds=10.0,
        end_seconds=40.0,
        duration_seconds=30.0,
        score=88.0,
        breakdown=ScoreBreakdown(),
        hook_title="Postgres Indexing Trap",
        transcript_text=(
            "PostgreSQL index bloat is the most common reason production servers crash. "
            "Everyone assumes adding indexes always speeds up queries, but our benchmarks proved "
            "write throughput dropped by fifty percent. That is why partial indexes are essential."
        ),
    )

    audit = validator.validate_candidate(valid_cand)
    assert audit.is_viable is True
    assert audit.complete_thought_opening is True
    assert audit.narrative_turn is True
    assert audit.clean_resolution is True
    assert audit.overall_viability_score >= 80.0
    assert len(audit.reasons_for_rejection) == 0

    # Non-viable candidate (dangling pronoun start and trailing fragment end)
    invalid_cand = HighlightCandidate(
        candidate_id="c_invalid",
        video_id="v_invalid",
        start_seconds=0.0,
        end_seconds=20.0,
        duration_seconds=20.0,
        score=75.0,
        breakdown=ScoreBreakdown(),
        hook_title="Uncontextual Clip",
        transcript_text="He told us that the cache had a bug and so",
    )

    audit_inv = validator.validate_candidate(invalid_cand)
    assert audit_inv.is_viable is False
    assert audit_inv.complete_thought_opening is False
    assert audit_inv.clean_resolution is False
    assert len(audit_inv.reasons_for_rejection) >= 2


def test_dangling_demonstrative_after_connectors():
    validator = ShortViabilityValidator()
    # Opens with "And that thing..."
    ok_and_that, crit = validator.validate_complete_thought_opening("And that thing broke our servers.")
    assert ok_and_that is False
    assert "dangling demonstrative 'that thing'" in crit

    # Opens with "So those people..."
    ok_so_those, crit_those = validator.validate_complete_thought_opening("So those people refused to merge the PR.")
    assert ok_so_those is False
    assert "dangling demonstrative 'those people'" in crit_those


def test_trailing_multi_word_filler_rejection():
    validator = ShortViabilityValidator()
    # Ends with "you know."
    ok, crit = validator.validate_clean_resolution("We were trying to build a cluster, you know.")
    assert ok is False
    assert "trailing filler phrase 'you know'" in crit

    # Ends with "kind of."
    ok_kind, crit_kind = validator.validate_clean_resolution("The database collapsed, kind of.")
    assert ok_kind is False
    assert "trailing filler phrase 'kind of'" in crit_kind


def test_question_mark_loop_hook_preserved_in_validate_candidate():
    validator = ShortViabilityValidator()
    cand = HighlightCandidate(
        candidate_id="c_q",
        video_id="v_q",
        start_seconds=0.0,
        end_seconds=15.0,
        duration_seconds=15.0,
        score=92.0,
        breakdown=ScoreBreakdown(),
        hook_title="Loop Question Hook",
        transcript_text="PostgreSQL index bloat is the primary bottleneck. But did we benchmark the partial index?",
    )
    audit = validator.validate_candidate(cand)
    # Final sentence ends with ? -> syntactic bridge loop score = 9.5
    assert audit.loop_hook_score >= 9.0
    assert "Seamless loop: final question" in audit.loop_hook_suggestion or "Seamless loop" in audit.narrative_critique or audit.loop_hook_score == 9.5

