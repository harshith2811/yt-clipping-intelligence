"""
Comprehensive test suite for CaptionSynthesizer and ClipIntelligence.
Tests model cascading, JSON markdown cleaning, missing field recovery,
offline deterministic fallback, and platform-specific caption formatting.
"""

import pytest
import json
from unittest.mock import patch, MagicMock
from yt_clipping.contracts.models import HighlightCandidate, ScoreBreakdown
from yt_clipping.discovery.video_metadata import EnrichedVideoInfo
from yt_clipping.scoring.caption_synthesizer import (
    CaptionSynthesizer,
    ShortCaptionPackage,
    ClipIntelligence,
    DEFAULT_LEGAL_DISCLAIMER,
)


@pytest.fixture
def sample_candidate():
    return HighlightCandidate(
        candidate_id="cand_1",
        video_id="nEaJMdM1djM",
        start_seconds=12.5,
        end_seconds=42.5,
        duration_seconds=30.0,
        score=88.5,
        breakdown=ScoreBreakdown(
            hook_score=9.0,
            moment_score=8.5,
            coherence_score=8.0,
            pacing_score=8.2,
        ),
        hook_title="The Unseen Future of Generative AI",
        suggested_description="Why everything we know about neural scaling is shifting.",
        transcript_text="So when you look at the fundamental economics of compute, models are getting exponentially cheaper to run.",
    )


@pytest.fixture
def sample_video_info():
    return EnrichedVideoInfo(
        video_id="nEaJMdM1djM",
        title="The State of AI 2026",
        description="A deep dive into frontier AI systems.",
        channel_title="Lex Fridman",
        channel_handle="@lexfridman",
        canonical_url="https://www.youtube.com/watch?v=nEaJMdM1djM",
        tags=["ai", "technology", "compute"],
    )


def test_explain_clip(sample_candidate, sample_video_info):
    synthesizer = CaptionSynthesizer()
    intelligence = synthesizer.explain_clip(sample_candidate, sample_video_info)

    assert isinstance(intelligence, ClipIntelligence)
    assert intelligence.hook_strength == 9.0
    assert intelligence.narrative_quality == 8.5
    assert intelligence.context_completeness > 0
    assert intelligence.information_density > 0
    assert intelligence.estimated_engagement_potential > 0
    assert "cand_1" in intelligence.selection_reason or "12.5s" in intelligence.selection_reason
    assert "Captures viewer interest immediately" in intelligence.why_it_works

    # Verify serialization
    data = intelligence.to_dict()
    restored = ClipIntelligence.from_dict(data)
    assert restored.hook_strength == intelligence.hook_strength


def test_offline_deterministic_package(sample_candidate, sample_video_info):
    synthesizer = CaptionSynthesizer(api_key="")
    package = synthesizer.generate_caption_package(
        sample_candidate, sample_video_info, force_offline=True
    )

    assert isinstance(package, ShortCaptionPackage)
    assert package.generation_provider == "offline_deterministic"
    assert package.generation_status == "offline_fallback"
    assert "Lex Fridman" in package.creator_credit
    assert "@lexfridman" in package.creator_credit
    assert DEFAULT_LEGAL_DISCLAIMER in package.full_copy_caption
    assert "youtube_shorts" in package.platform_variants
    assert "instagram_reels" in package.platform_variants
    assert "tiktok" in package.platform_variants
    assert len(package.targeted_hashtags) >= 6

    # Verify dict roundtrip
    d = package.to_dict()
    restored = ShortCaptionPackage.from_dict(d)
    assert restored.hook_title == package.hook_title


def test_ai_generation_primary_model_success(sample_candidate, sample_video_info):
    synthesizer = CaptionSynthesizer(
        api_key="mock_key",
        primary_model="gemini-3.5-flash-lite",
        fallback_model="gemini-flash-latest",
    )

    ai_json = {
        "hook_title": "AI Compute Is Collapsing in Cost",
        "hook_opening": "When you look at the fundamental economics of compute...",
        "core_summary": "Frontier models are becoming exponentially cheaper to run, transforming software.",
        "targeted_hashtags": ["#AI", "#TechTrends", "#Future", "#NeuralNetworks", "#Compute", "#Innovation"],
        "why_it_works": "Immediate hook that challenges existing economic assumptions about AI scale.",
    }

    mock_resp_body = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": f"```json\n{json.dumps(ai_json)}\n```"}
                    ]
                }
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(mock_resp_body).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        pkg = synthesizer.generate_caption_package(sample_candidate, sample_video_info)
        assert pkg.generation_provider == "gemini-3.5-flash-lite"
        assert pkg.generation_status == "primary_model"
        assert pkg.hook_title == "AI Compute Is Collapsing in Cost"
        assert "#AI" in pkg.targeted_hashtags


def test_ai_generation_cascading_to_fallback_model(sample_candidate, sample_video_info):
    synthesizer = CaptionSynthesizer(
        api_key="mock_key",
        primary_model="gemini-3.5-flash-lite",
        fallback_model="gemini-flash-latest",
    )

    fallback_ai_json = {
        "hook_title": "Fallback Model Insight",
        "hook_opening": "Listen to this economic reality:",
        "core_summary": "A breakthrough summary from the fallback model.",
        "targeted_hashtags": ["#FallbackTag1", "#FallbackTag2"],
        "why_it_works": "Captures interest through fallback AI analysis.",
    }

    fallback_resp_body = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": json.dumps(fallback_ai_json)}
                    ]
                }
            }
        ]
    }

    mock_fallback_resp = MagicMock()
    mock_fallback_resp.status = 200
    mock_fallback_resp.read.return_value = json.dumps(fallback_resp_body).encode("utf-8")
    mock_fallback_resp.__enter__.return_value = mock_fallback_resp

    call_count = 0

    def mock_urlopen_dispatch(req, timeout):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call (primary model) fails with 404 or 500
            import urllib.error
            raise urllib.error.HTTPError(req.full_url, 404, "Model Not Found", {}, None)
        return mock_fallback_resp

    with patch("urllib.request.urlopen", side_effect=mock_urlopen_dispatch):
        pkg = synthesizer.generate_caption_package(sample_candidate, sample_video_info)
        assert pkg.generation_provider == "gemini-flash-latest"
        assert pkg.generation_status == "fallback_model"
        assert pkg.hook_title == "Fallback Model Insight"


def test_ai_generation_cascading_both_fail_to_offline(sample_candidate, sample_video_info):
    synthesizer = CaptionSynthesizer(
        api_key="mock_key",
        primary_model="gemini-3.5-flash-lite",
        fallback_model="gemini-flash-latest",
    )

    with patch("urllib.request.urlopen", side_effect=RuntimeError("Connection Refused")):
        pkg = synthesizer.generate_caption_package(sample_candidate, sample_video_info)
        assert pkg.generation_provider == "offline_deterministic"
        assert pkg.generation_status == "offline_fallback"
        assert pkg.hook_title == sample_candidate.hook_title


def test_no_invented_channel_handle(sample_candidate):
    """Verifies that when channel_handle is None, no fake '@Handle' is invented."""
    info_no_handle = EnrichedVideoInfo(
        video_id="test1234567",
        title="Uncut Science",
        description="",
        channel_title="Science With Dr Smith",
        channel_handle=None,  # No handle
        canonical_url="https://www.youtube.com/watch?v=test1234567",
    )
    synthesizer = CaptionSynthesizer()
    pkg = synthesizer.generate_caption_package(sample_candidate, info_no_handle, force_offline=True)

    # Must NOT contain invented handle @ScienceWithDrSmith
    assert "@ScienceWithDrSmith" not in pkg.creator_credit
    assert "Original video and content by: Science With Dr Smith" in pkg.creator_credit
    assert "@ScienceWithDrSmith" not in pkg.platform_variants["instagram_reels"]
    assert "Credit: Science With Dr Smith" in pkg.platform_variants["instagram_reels"]

    # Verify copyright awareness dictionary
    assert "copyright_awareness" in pkg.to_dict()
    ca = pkg.copyright_awareness
    assert ca["creator_identity"] == "Science With Dr Smith"
    assert ca["creator_handle"] is None
    assert ca["original_source_url"] == "https://www.youtube.com/watch?v=test1234567"
    assert "commentary_transformative_fair_use" in ca["permission_status"]


def test_hashtag_robust_string_and_comma_parsing(sample_candidate, sample_video_info):
    """Verifies that string and comma-separated hashtags from AI are parsed correctly without char splitting."""
    synthesizer = CaptionSynthesizer(api_key="mock_key")
    ai_raw = {
        "hook_title": "Hashtag Test",
        "hook_opening": "Opening",
        "core_summary": "Summary",
        "targeted_hashtags": "#AI, #MachineLearning #DeepLearning, #Tech",
        "why_it_works": "Engaging hook",
    }
    pkg = synthesizer._build_package_from_ai(ai_raw, sample_candidate, sample_video_info, "mock_model", "primary")
    assert isinstance(pkg.targeted_hashtags, list)
    assert "#AI" in pkg.targeted_hashtags
    assert "#MachineLearning" in pkg.targeted_hashtags
    assert "#DeepLearning" in pkg.targeted_hashtags
    assert "#Tech" in pkg.targeted_hashtags
    # Ensure characters weren't split into '#', '#A', '#I'
    for tag in pkg.targeted_hashtags:
        assert len(tag) > 2

