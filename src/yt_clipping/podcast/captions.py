"""
Podcast Caption & Kinetic Subtitle Generator.
Generates word-synced ASS subtitles positioned precisely at the center divider
of stacked podcast split-screens, ensuring readability across both speaker frames.
"""

from typing import List, Optional, Tuple, Dict, Any
import os
import re

from ..contracts.models import HighlightCandidate, ScoreBreakdown, Transcript, TranscriptSegment, WordTimestamp
from ..rendering.captions import escape_ass_text, SubtitleGenerator
from .config import PodcastLayoutConfig


class PodcastSubtitleGenerator:
    """
    Generates ASS subtitle files for podcast shorts with center-aligned margins.
    """

    def __init__(self, config: Optional[PodcastLayoutConfig] = None):
        self.config = config or PodcastLayoutConfig()
        # Internal base generator
        self.base_generator = SubtitleGenerator(
            style_preset=self.config.subtitle_preset,
            font_name=self.config.font_name,
            font_size=self.config.font_size,
            word_highlight=True,
            bounce_animation=True,
            uppercase=True,
        )
        # Override margin_v to center line
        self.base_generator.margin_v = self.config.margin_v

    def generate_subtitles(
        self,
        candidate: HighlightCandidate,
        transcript: Transcript,
        output_path: str
    ) -> str:
        """
        Generates center-aligned ASS subtitle script for the candidate interval.
        """
        return self.base_generator.generate_ass(candidate, transcript, output_path)

    def generate_from_words(
        self,
        words_data: List[Tuple[str, float, float]],
        start_sec: float,
        duration_sec: float,
        output_path: str
    ) -> str:
        """
        Convenience generator from a list of (word, start, end) tuples.
        """
        words = [
            WordTimestamp(word=w[0], start=w[1], end=w[2], confidence=0.99)
            for w in words_data
        ]
        segment = TranscriptSegment(
            segment_id=0,
            start=start_sec,
            end=start_sec + duration_sec,
            text=" ".join(w[0] for w in words_data),
            words=words
        )
        transcript = Transcript(
            video_id="podcast_clip",
            language="en",
            duration_seconds=duration_sec,
            text=segment.text,
            segments=[segment]
        )
        candidate = HighlightCandidate(
            candidate_id="podcast_highlight",
            video_id="podcast_clip",
            start_seconds=start_sec,
            end_seconds=start_sec + duration_sec,
            duration_seconds=duration_sec,
            score=95.0,
            breakdown=ScoreBreakdown(hook_score=90.0, moment_score=90.0),
            hook_title="Podcast Highlight"
        )
        return self.generate_subtitles(candidate, transcript, output_path)
