"""
Tests for AI Metadata and Hook Generation (FEATURE-09).
"""

import pytest
from src.yt_clipping.contracts.models import HighlightCandidate, ScoreBreakdown, Transcript, TranscriptSegment
from src.yt_clipping.scoring.metadata_generator import MetadataGenerator, ClipMetadata


def test_metadata_generator_heuristic_fallback():
    generator = MetadataGenerator(llm_api_base=None)
    
    cand = HighlightCandidate(
        candidate_id="c_meta_1",
        video_id="vid_meta_1",
        start_seconds=10.0,
        end_seconds=40.0,
        duration_seconds=30.0,
        score=85.0,
        breakdown=ScoreBreakdown(),
        hook_title="Scaling Machine Learning Pipelines",
        transcript_text="Scaling machine learning pipelines requires deterministic state machines and low latency.",
    )
    
    meta = generator.generate_metadata(cand)
    assert isinstance(meta, ClipMetadata)
    assert len(meta.hooks) == 3
    assert any("?" in h for h in meta.hooks)  # Question hook
    assert len(meta.caption) <= 150
    assert len(meta.hashtags) >= 3
    assert all(tag.startswith("#") for tag in meta.hashtags)
    assert meta.model_used == "heuristic_rule_engine"


def test_metadata_generator_from_transcript_context():
    generator = MetadataGenerator()
    segments = [
        TranscriptSegment(segment_id=0, start=0.0, end=10.0, text="Intro segment."),
        TranscriptSegment(segment_id=1, start=10.0, end=35.0, text="This is the crucial python code optimization section."),
        TranscriptSegment(segment_id=2, start=35.0, end=50.0, text="Outro conclusion."),
    ]
    transcript = Transcript(
        video_id="v_tr_meta",
        language="en",
        duration_seconds=50.0,
        text="Intro segment. This is the crucial python code optimization section. Outro conclusion.",
        segments=segments,
    )
    cand = HighlightCandidate(
        candidate_id="c_tr",
        video_id="v_tr_meta",
        start_seconds=10.0,
        end_seconds=35.0,
        duration_seconds=25.0,
        score=90.0,
        breakdown=ScoreBreakdown(),
        hook_title="",  # Empty hook title, should generate from transcript
    )
    meta = generator.generate_metadata(cand, transcript=transcript)
    assert len(meta.hooks) == 3
    assert "#coding" in meta.hashtags
