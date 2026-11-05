"""Explainable multi-signal highlight scoring."""
from .scorecard import ExplainableScorecardScorer
from .gemini_provider import (
    GeminiHighlightDiscoveryProvider,
    get_highlight_detector,
    get_highlight_scorer,
)
from .metadata_generator import MetadataGenerator, ClipMetadata
from .packaging_linter import PackagingLinter, LintIssue, PackagingLintReport

__all__ = [
    "ExplainableScorecardScorer",
    "GeminiHighlightDiscoveryProvider",
    "get_highlight_detector",
    "get_highlight_scorer",
    "MetadataGenerator",
    "ClipMetadata",
    "PackagingLinter",
    "LintIssue",
    "PackagingLintReport",
    "CaptionSynthesizer",
    "ShortCaptionPackage",
    "ClipIntelligence",
]

from .caption_synthesizer import (
    CaptionSynthesizer,
    ShortCaptionPackage,
    ClipIntelligence,
)
