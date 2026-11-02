"""
Tests for Gemini Multimodal Highlight Discovery Provider:
GeminiHighlightDiscoveryProvider, CandidateClip alias, get_highlight_detector, get_highlight_scorer.
"""

import pytest
import os
import json
import socket
import urllib.error
from unittest.mock import MagicMock, patch

from src.yt_clipping.contracts.models import (
    Transcript,
    TranscriptSegment,
    WordTimestamp,
    HighlightCandidate,
    ScoreBreakdown,
    HeatmapData,
    HeatmapPeak,
)
from src.yt_clipping.contracts.interfaces import HighlightDetector, HighlightScorer
from src.yt_clipping.detection.segmenter import ContextAwareSegmenter
from src.yt_clipping.scoring.scorecard import ExplainableScorecardScorer
from src.yt_clipping.scoring.gemini_provider import (
    GeminiHighlightDiscoveryProvider,
    CandidateClip,
    get_highlight_detector,
    get_highlight_scorer,
)


@pytest.fixture
def mock_transcript():
    words_1 = [
        WordTimestamp("The", 0.0, 0.3),
        WordTimestamp("secret", 0.4, 0.8),
        WordTimestamp("to", 0.9, 1.1),
        WordTimestamp("scaling", 1.2, 1.8),
        WordTimestamp("startups", 1.9, 2.5),
        WordTimestamp("is", 2.6, 2.8),
        WordTimestamp("extreme", 2.9, 3.4),
        WordTimestamp("focus.", 3.5, 4.0),
    ]
    words_2 = [
        WordTimestamp("Most", 4.5, 4.8),
        WordTimestamp("founders", 4.9, 5.5),
        WordTimestamp("fail", 5.6, 6.0),
        WordTimestamp("because", 6.1, 6.6),
        WordTimestamp("they", 6.7, 6.9),
        WordTimestamp("build", 7.0, 7.4),
        WordTimestamp("ten", 7.5, 7.8),
        WordTimestamp("features", 7.9, 8.4),
        WordTimestamp("instead", 8.5, 9.0),
        WordTimestamp("of", 9.1, 9.2),
        WordTimestamp("one.", 9.3, 9.8),
    ]
    words_3 = [
        WordTimestamp("At", 10.0, 10.2),
        WordTimestamp("the", 10.3, 10.5),
        WordTimestamp("end", 10.6, 10.8),
        WordTimestamp("of", 10.9, 11.0),
        WordTimestamp("the", 11.1, 11.3),
        WordTimestamp("day,", 11.4, 11.8),
        WordTimestamp("simplicity", 12.0, 12.8),
        WordTimestamp("wins", 13.0, 13.5),
        WordTimestamp("every", 13.6, 14.0),
        WordTimestamp("time.", 14.1, 14.5),
    ]
    words_4 = [
        WordTimestamp("This", 15.0, 15.3),
        WordTimestamp("changes", 15.4, 15.9),
        WordTimestamp("everything", 16.0, 16.8),
        WordTimestamp("for", 16.9, 17.1),
        WordTimestamp("modern", 17.2, 17.7),
        WordTimestamp("founders", 17.8, 18.5),
        WordTimestamp("competing", 18.6, 19.3),
        WordTimestamp("today.", 19.4, 20.0),
        WordTimestamp("Remember", 20.2, 20.8),
        WordTimestamp("that.", 20.9, 21.5),
    ]
    segments = [
        TranscriptSegment(1, 0.0, 4.0, "The secret to scaling startups is extreme focus.", words_1),
        TranscriptSegment(2, 4.5, 9.8, "Most founders fail because they build ten features instead of one.", words_2),
        TranscriptSegment(3, 10.0, 14.5, "At the end of the day, simplicity wins every time.", words_3),
        TranscriptSegment(4, 15.0, 21.5, "This changes everything for modern founders competing today. Remember that.", words_4),
    ]
    return Transcript(
        video_id="startup_growth_01",
        language="en",
        duration_seconds=22.0,
        text="The secret to scaling startups is extreme focus. Most founders fail because they build ten features instead of one. At the end of the day, simplicity wins every time. This changes everything for modern founders competing today. Remember that.",
        segments=segments,
    )


@pytest.fixture
def mock_heatmap():
    peak = HeatmapPeak(
        peak_id="pk_01",
        start_time=2.0,
        end_time=18.0,
        center_time=10.0,
        intensity=0.95,
        prominence=0.8,
        width_seconds=16.0,
        classification="GLOBAL_MAXIMA",
        suggested_clip_start=0.0,
        suggested_clip_end=20.0,
    )
    return HeatmapData(video_id="startup_growth_01", source="YOUTUBE_HEATMAP", peaks=[peak], global_peak=peak)


def test_candidate_clip_alias_contract():
    assert CandidateClip is HighlightCandidate


def test_provider_initialization_precedence():
    # Priority: explicit arg > config > env var > default
    with patch.dict(os.environ, {"GEMINI_API_KEY": "env_key", "GEMINI_MODEL": "gemini-pro"}, clear=False):
        # Explicit arg wins
        p1 = GeminiHighlightDiscoveryProvider(api_key="arg_key", model="arg_model")
        assert p1.api_key == "arg_key"
        assert p1.model == "arg_model"

        # Config wins over env var
        class Cfg:
            gemini_api_key = "cfg_key"
            gemini_model = "cfg_model"

        p2 = GeminiHighlightDiscoveryProvider(config=Cfg())
        assert p2.api_key == "cfg_key"
        assert p2.model == "cfg_model"

        # Env var wins over default
        p3 = GeminiHighlightDiscoveryProvider()
        assert p3.api_key == "env_key"
        assert p3.model == "gemini-pro"


def test_provider_offline_mode_flag(mock_transcript):
    provider = GeminiHighlightDiscoveryProvider(api_key="valid_key", offline_mode=True)
    assert not provider.is_cloud_available

    with patch.object(provider, "_execute_rest_request") as mock_http:
        candidates = provider.detect_candidates(mock_transcript, min_duration=10.0, max_duration=22.0)
        # Should not make any HTTP calls
        mock_http.assert_not_called()
        # Heuristic engine returns candidates
        assert len(candidates) > 0


def test_missing_key_graceful_fallback(mock_transcript):
    with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}, clear=False):
        provider = GeminiHighlightDiscoveryProvider(api_key="")
        assert not provider.is_cloud_available

        candidates = provider.detect_candidates(mock_transcript, min_duration=10.0, max_duration=22.0)
        assert len(candidates) > 0
        assert isinstance(candidates[0], HighlightCandidate)


def test_cloud_detection_successful_mock(mock_transcript, mock_heatmap):
    provider = GeminiHighlightDiscoveryProvider(api_key="valid_key")

    mock_gemini_payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps({
                                "highlights": [
                                    {
                                        "start_seconds": 0.0,
                                        "end_seconds": 21.5,
                                        "hook_title": "Why Simplicity Always Wins in Startups",
                                        "suggested_description": "Stop building 10 features #startups #growth",
                                        "transcript_text": "The secret to scaling startups is extreme focus...",
                                        "hook_score": 9.2,
                                        "moment_score": 9.5,
                                        "coherence_score": 9.0,
                                        "pacing_score": 8.5,
                                        "heatmap_score": 9.5,
                                        "rationale": "Strong opening curiosity hook followed by crisp payoff",
                                    }
                                ]
                            })
                        }
                    ]
                }
            }
        ]
    }

    with patch.object(provider, "_execute_rest_request", return_value=json.dumps(mock_gemini_payload)):
        candidates = provider.detect_candidates(
            mock_transcript,
            min_duration=10.0,
            max_duration=25.0,
            heatmap=mock_heatmap,
            metadata={"title": "Startup Scaling Secrets", "channel": "Founder Hub"},
        )
        assert len(candidates) == 1
        c = candidates[0]
        assert c.hook_title == "Why Simplicity Always Wins in Startups"
        assert c.start_seconds == 0.0
        assert c.end_seconds == 21.5
        assert c.duration_seconds == 21.5
        assert c.breakdown.hook_score == 9.2
        assert c.score > 80.0


def test_structured_prompt_metadata_and_heatmap_injection(mock_transcript, mock_heatmap):
    provider = GeminiHighlightDiscoveryProvider(api_key="valid_key")
    prompt = provider._build_detection_prompt(
        transcript=mock_transcript,
        min_duration=15.0,
        max_duration=30.0,
        heatmap=mock_heatmap,
        metadata={"title": "Viral Formula 101", "channel": "Growth Masters"},
    )
    assert "Viral Formula 101" in prompt
    assert "Growth Masters" in prompt
    assert "GLOBAL_MAXIMA" in prompt
    assert "startup_growth_01" in prompt


def test_network_http_error_graceful_fallback(mock_transcript):
    provider = GeminiHighlightDiscoveryProvider(api_key="valid_key")

    with patch.object(provider, "_execute_rest_request", side_effect=urllib.error.HTTPError(None, 429, "Too Many Requests", None, None)):
        candidates = provider.detect_candidates(mock_transcript, min_duration=10.0, max_duration=22.0)
        assert len(candidates) > 0


def test_network_timeout_and_socket_error_fallback(mock_transcript):
    provider = GeminiHighlightDiscoveryProvider(api_key="valid_key")

    with patch.object(provider, "_execute_rest_request", side_effect=socket.timeout("Connection timed out")):
        candidates = provider.detect_candidates(mock_transcript, min_duration=10.0, max_duration=22.0)
        assert len(candidates) > 0


def test_malformed_json_and_markdown_fences_handling(mock_transcript):
    provider = GeminiHighlightDiscoveryProvider(api_key="valid_key")

    # Wrapped in ```json markdown fence
    fenced_payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": "```json\n" + json.dumps({
                                "highlights": [
                                    {
                                        "start_seconds": 0.0,
                                        "end_seconds": 20.0,
                                        "hook_title": "Fenced Title",
                                        "hook_score": 8.0,
                                        "moment_score": 8.0,
                                    }
                                ]
                            }) + "\n```"
                        }
                    ]
                }
            }
        ]
    }

    with patch.object(provider, "_execute_rest_request", return_value=json.dumps(fenced_payload)):
        candidates = provider.detect_candidates(mock_transcript, min_duration=10.0, max_duration=25.0)
        assert len(candidates) == 1
        assert candidates[0].hook_title == "Fenced Title"

    # Completely broken JSON -> triggers fallback
    broken_payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "INVALID JSON {"}
                    ]
                }
            }
        ]
    }
    with patch.object(provider, "_execute_rest_request", return_value=json.dumps(broken_payload)):
        fallback_candidates = provider.detect_candidates(mock_transcript, min_duration=10.0, max_duration=22.0)
        assert len(fallback_candidates) > 0


def test_candidate_bounds_validation_and_clamping(mock_transcript):
    provider = GeminiHighlightDiscoveryProvider(api_key="valid_key")

    # One valid highlight, one invalid bounds (negative start), one out of duration range
    mixed_payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps({
                                "highlights": [
                                    {
                                        "start_seconds": 0.0,
                                        "end_seconds": 21.0,
                                        "hook_title": "Valid Bounds",
                                    },
                                    {
                                        "start_seconds": -5.0,
                                        "end_seconds": 15.0,
                                        "hook_title": "Negative Start",
                                    },
                                    {
                                        "start_seconds": 0.0,
                                        "end_seconds": 3.0,  # too short (< min_duration)
                                        "hook_title": "Too Short",
                                    },
                                ]
                            })
                        }
                    ]
                }
            }
        ]
    }

    with patch.object(provider, "_execute_rest_request", return_value=json.dumps(mixed_payload)):
        candidates = provider.detect_candidates(mock_transcript, min_duration=10.0, max_duration=25.0)
        assert len(candidates) == 1
        assert candidates[0].hook_title == "Valid Bounds"


def test_score_candidate_contract(mock_transcript):
    provider = GeminiHighlightDiscoveryProvider()

    # Pre-scored candidate (from Gemini) passes through
    pre_scored = HighlightCandidate(
        candidate_id="c_01",
        video_id=mock_transcript.video_id,
        start_seconds=0.0,
        end_seconds=20.0,
        duration_seconds=20.0,
        score=85.0,
        breakdown=ScoreBreakdown(hook_score=9.0, moment_score=8.5),
        hook_title="Pre Scored",
    )
    result = provider.score_candidate(pre_scored, mock_transcript)
    assert result.score == 85.0

    # Un-scored candidate gets scored by fallback scorecard
    unscored = HighlightCandidate(
        candidate_id="c_02",
        video_id=mock_transcript.video_id,
        start_seconds=0.0,
        end_seconds=20.0,
        duration_seconds=20.0,
        score=0.0,
        breakdown=ScoreBreakdown(),
        hook_title="Unscored",
        transcript_text="The secret to scaling startups is extreme focus.",
    )
    result_scored = provider.score_candidate(unscored, mock_transcript)
    assert result_scored.score > 0.0


def test_discover_highlights_contract(mock_transcript):
    provider = GeminiHighlightDiscoveryProvider(api_key="", offline_mode=True)
    highlights = provider.discover_highlights(transcript=mock_transcript, min_duration=10.0, max_duration=22.0)
    assert isinstance(highlights, list)
    assert len(highlights) > 0
    # Sorted descending by score
    scores = [h.score for h in highlights]
    assert scores == sorted(scores, reverse=True)

    with pytest.raises(ValueError, match="Transcript is required"):
        provider.discover_highlights(transcript=None)


def test_factory_get_highlight_detector():
    # Explicit heuristic
    d1 = get_highlight_detector(engine="heuristic")
    assert isinstance(d1, ContextAwareSegmenter)

    # Explicit gemini
    d2 = get_highlight_detector(engine="gemini")
    assert isinstance(d2, GeminiHighlightDiscoveryProvider)

    # Unknown engine
    with pytest.raises(ValueError, match="Unsupported highlight detector engine"):
        get_highlight_detector(engine="non_existent")

    # Auto without key gives heuristic
    with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}, clear=False):
        d3 = get_highlight_detector()
        assert isinstance(d3, ContextAwareSegmenter)

    # Auto with key gives gemini provider
    with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy_key"}, clear=False):
        d4 = get_highlight_detector()
        assert isinstance(d4, GeminiHighlightDiscoveryProvider)


def test_factory_get_highlight_scorer():
    # Explicit heuristic
    s1 = get_highlight_scorer(engine="heuristic")
    assert isinstance(s1, ExplainableScorecardScorer)

    # Explicit gemini
    s2 = get_highlight_scorer(engine="gemini")
    assert isinstance(s2, GeminiHighlightDiscoveryProvider)

    # Unknown engine
    with pytest.raises(ValueError, match="Unsupported highlight scorer engine"):
        get_highlight_scorer(engine="non_existent")

    # Auto without key gives scorecard
    with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}, clear=False):
        s3 = get_highlight_scorer()
        assert isinstance(s3, ExplainableScorecardScorer)


def test_discover_highlights_flexible_signatures(mock_transcript):
    provider = GeminiHighlightDiscoveryProvider(api_key="", offline_mode=True)

    # 1. Positional call: (video_path, metadata_dict_with_transcript)
    meta_with_transcript = {
        "title": "Test Title",
        "transcript": mock_transcript,
        "duration_seconds": 22.0,
    }
    hl1 = provider.discover_highlights("dummy.mp4", meta_with_transcript, min_duration=10.0, max_duration=22.0)
    assert len(hl1) > 0

    # 2. Positional call: (video_path, metadata_dict_with_transcript_as_dict)
    meta_with_dict_transcript = {
        "title": "Test Title",
        "transcript": mock_transcript.to_dict(),
        "duration_seconds": 22.0,
    }
    hl2 = provider.discover_highlights("dummy.mp4", meta_with_dict_transcript, min_duration=10.0, max_duration=22.0)
    assert len(hl2) > 0

    # 3. Positional call: (video_path, metadata_dict_with_transcript_text)
    meta_with_text_transcript = {
        "title": "Test Title",
        "transcript": "The secret to scaling startups is extreme focus. Simplicity wins every time.",
        "duration_seconds": 22.0,
    }
    hl3 = provider.discover_highlights("dummy.mp4", meta_with_text_transcript, min_duration=5.0, max_duration=22.0)
    assert len(hl3) > 0


def test_factory_highlight_detector_and_scorer_non_string_resilience():
    # Int engine
    d1 = get_highlight_detector(config={"highlight_engine": 123})
    assert isinstance(d1, HighlightDetector)

    s1 = get_highlight_scorer(config={"highlight_engine": 123})
    assert isinstance(s1, HighlightScorer)

    # None engine
    d2 = get_highlight_detector(config={"highlight_engine": None})
    assert isinstance(d2, HighlightDetector)

    s2 = get_highlight_scorer(config={"highlight_engine": None})
    assert isinstance(s2, HighlightScorer)

