"""
Unit tests for PackagingLinter:
- Mobile truncation safety (40 char primary hook, 60 char title ceiling)
- Front-loading validation (rejecting 'the', 'how to', 'this is' in first 3 words)
- Click-surface non-duplication (rejecting thumbnail text repeating title)
- Vague buzzword elimination ('insane', 'mindblowing', 'crazy')
"""

import pytest
from src.yt_clipping.scoring.packaging_linter import (
    PackagingLinter,
    PackagingLintReport,
    LintIssue,
)


def test_mobile_truncation_limits():
    linter = PackagingLinter()

    # 1. Compliant punchy title (< 40 chars hook, < 60 chars total)
    good_title = "PyTorch 2.0: Zero Memory Overhead"
    rep_good = linter.lint_title(good_title)
    assert rep_good.is_valid is True
    assert rep_good.passed_mobile_truncation is True
    assert rep_good.primary_hook_chars <= 40
    assert rep_good.total_chars <= 60

    # 2. Hard ceiling exceeded (> 60 chars)
    long_title = "This Brand New Comprehensive Tutorial Explains Scaling High-Concurrency Microservices"
    assert len(long_title) > 60
    rep_long = linter.lint_title(long_title)
    assert rep_long.is_valid is False
    assert any(i.rule == "mobile_ceiling_exceeded" and i.severity == "ERROR" for i in rep_long.issues)

    # 3. Primary hook exceeds 40 characters
    long_hook_title = "Comprehensive Distributed Machine Learning Architectures: Key Takeaway"
    rep_hook = linter.lint_title(long_hook_title)
    assert rep_hook.primary_hook_chars > 40
    assert any(i.rule == "primary_hook_mobile_truncation" for i in rep_hook.issues)


def test_front_loading_validation():
    linter = PackagingLinter()

    # Generic stop phrase openings:
    # 1. "The ..."
    rep_the = linter.lint_title("The Ultimate Python Secret")
    assert rep_the.passed_front_loading is False
    assert any(i.rule == "generic_stop_phrase_front" for i in rep_the.issues)

    # 2. "How to ..."
    rep_how = linter.lint_title("How to Optimize Docker Containers")
    assert rep_how.passed_front_loading is False
    assert any(i.rule == "generic_stop_phrase_front" for i in rep_how.issues)

    # 3. "This is ..."
    rep_this = linter.lint_title("This is Why Microservices Fail")
    assert rep_this.passed_front_loading is False
    assert any(i.rule == "generic_stop_phrase_front" for i in rep_this.issues)

    # Compliant front-loaded title (leads with subject/metric)
    rep_pass = linter.lint_title("PostgreSQL Scaling: 5 Bottlenecks")
    assert rep_pass.passed_front_loading is True


def test_click_surface_duplication():
    linter = PackagingLinter()

    title = "Scaling PyTorch Fast"

    # Exact duplicate thumbnail text -> REJECT
    passed_exact, issues_exact = linter.check_click_surface_duplication(title, "Scaling PyTorch Fast")
    assert passed_exact is False
    assert any(i.rule == "click_surface_exact_duplicate" for i in issues_exact)

    # Repetitive phrase thumbnail text -> REJECT
    passed_phrase, issues_phrase = linter.check_click_surface_duplication(title, "Scaling PyTorch")
    assert passed_phrase is False
    assert any(i.rule == "click_surface_phrase_repetition" for i in issues_phrase)

    # High word overlap -> REJECT
    passed_overlap, issues_overlap = linter.check_click_surface_duplication(title, "Fast PyTorch Scaling")
    assert passed_overlap is False

    # Complementary click surface -> PASS
    passed_clean, issues_clean = linter.check_click_surface_duplication(title, "Zero GPU Memory Bottlenecks")
    assert passed_clean is True
    assert len(issues_clean) == 0


def test_vague_buzzword_elimination():
    linter = PackagingLinter()

    title = "Insane Mindblowing Trick for Crazy Speed"
    rep = linter.lint_title(title)

    assert rep.passed_buzzword_check is False
    assert set(rep.detected_buzzwords) == {"insane", "mindblowing", "crazy"}
    # Cleaned title should substitute lazy buzzwords with concrete alternatives
    assert "insane" not in rep.cleaned_title.lower()
    assert "mindblowing" not in rep.cleaned_title.lower()
    assert "crazy" not in rep.cleaned_title.lower()
    assert "10x" in rep.cleaned_title or "counterintuitive" in rep.cleaned_title


def test_sanitize_title_full_pipeline():
    linter = PackagingLinter()

    raw_title = "The Insane Python Optimization Trick That Changes Everything"
    cleaned = linter.sanitize_title(raw_title, max_chars=40)

    # Strips "The", replaces "Insane", clamps to <= 40 chars
    assert not cleaned.lower().startswith("the ")
    assert "insane" not in cleaned.lower()
    assert len(cleaned) <= 40


def test_mobile_hook_limit_enforcement():
    linter = PackagingLinter()
    # 59 chars total (< 60 ceiling), but hook is 59 chars (> 40 limit)
    single_clause = "This Super Long Single Clause Title Without Delimiters Here"
    assert len(single_clause) == 59
    rep = linter.lint_title(single_clause)
    assert rep.passed_mobile_truncation is False
    assert rep.is_valid is False
    assert any(i.rule == "primary_hook_mobile_truncation" and i.severity == "ERROR" for i in rep.issues)


def test_front_loading_with_colons_and_punctuation():
    linter = PackagingLinter()
    # Colon after stop phrase
    rep_how = linter.lint_title("How to: 10x Your Database")
    assert rep_how.passed_front_loading is False
    assert rep_how.is_valid is False
    # Sanitization strips colon prefix
    cleaned = linter.sanitize_title("How to: 10x Your Database")
    assert cleaned == "10x Your Database"

    rep_the = linter.lint_title("The: Ultimate Production Setup")
    assert rep_the.passed_front_loading is False
    cleaned_the = linter.sanitize_title("The: Ultimate Production Setup")
    assert cleaned_the == "Ultimate Production Setup"


def test_symmetric_click_surface_duplication():
    linter = PackagingLinter()
    # Title contained in thumbnail text
    passed, issues = linter.check_click_surface_duplication("Zero Overhead", "Zero Overhead Today")
    assert passed is False
    assert len(issues) > 0


def test_buzzword_inflections():
    linter = PackagingLinter()
    title = "Insanely Craziest Trick Ever Unbelievably Proven"
    rep = linter.lint_title(title)
    assert rep.passed_buzzword_check is False
    assert "insanely" not in rep.cleaned_title.lower()
    assert "craziest" not in rep.cleaned_title.lower()
    assert "unbelievably" not in rep.cleaned_title.lower()

