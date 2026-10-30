"""
Tests for HeatmapAnalyzer: signal smoothing, topological peak prominence,
sentence boundary snapping, fallback synthesis, and ASCII visualization.
"""

import pytest
import os
import json
import numpy as np

from src.yt_clipping.contracts.models import (
    HeatmapPoint,
    HeatmapPeak,
    HeatmapData,
    Transcript,
    TranscriptSegment,
    WordTimestamp,
)
from src.yt_clipping.discovery.heatmap import HeatmapAnalyzer


def test_topological_peak_detection():
    analyzer = HeatmapAnalyzer(cache_dir="data/heatmaps")

    # Generate synthetic 100-point retention curve with 2 distinct peaks:
    # Baseline ~0.2, Peak 1 at index 25 (val=0.9), Peak 2 at index 75 (val=0.7)
    points = []
    for i in range(100):
        t0 = i * 6.0
        t1 = (i + 1) * 6.0
        # Peak 1 around index 25 (t=150s)
        val1 = 0.7 * math_exp(-0.5 * ((i - 25) / 2.5) ** 2)
        # Peak 2 around index 75 (t=450s)
        val2 = 0.5 * math_exp(-0.5 * ((i - 75) / 3.0) ** 2)
        val = 0.2 + val1 + val2
        points.append(HeatmapPoint(start_time=t0, end_time=t1, value=val))

    peaks = analyzer.detect_peaks(points, total_duration=600.0)

    assert len(peaks) >= 2
    # First detected peak should be Global Maxima near index 25 (150s)
    top_peak = peaks[0]
    assert top_peak.classification == "GLOBAL_MAXIMA"
    assert abs(top_peak.center_time - 153.0) < 15.0
    assert top_peak.intensity > 0.8
    assert top_peak.prominence > 0.4

    # Second peak near index 75 (450s)
    second_peak = peaks[1]
    assert abs(second_peak.center_time - 453.0) < 15.0
    assert second_peak.intensity > 0.6


def math_exp(x: float) -> float:
    import math
    return math.exp(x)


def test_sentence_boundary_snapping():
    analyzer = HeatmapAnalyzer(cache_dir="data/heatmaps")

    # Mock transcript with sentences starting at 120s, 140s, 175s, 200s
    seg1 = TranscriptSegment(segment_id=1, start=120.0, end=138.0, text="First point here.")
    seg2 = TranscriptSegment(segment_id=2, start=140.0, end=172.0, text="This is the main viral sentence.")
    seg3 = TranscriptSegment(segment_id=3, start=175.0, end=195.0, text="And that is the punchline!")
    transcript = Transcript(
        video_id="test_vid",
        language="en",
        duration_seconds=600.0,
        text="All text",
        segments=[seg1, seg2, seg3],
    )

    # Peak centered at 155s (inside seg2)
    start, end = analyzer.snap_peak_to_window(
        center_time=155.0,
        transcript=transcript,
        total_duration=600.0,
        target_duration=35.0,
    )

    # Should snap start to ~140s and end to ~172s or ~195s
    assert start == 140.0
    assert end in [172.0, 195.0]
    assert 20.0 <= (end - start) <= 60.0


def test_ascii_waveform_rendering():
    analyzer = HeatmapAnalyzer(cache_dir="data/heatmaps")
    pts = [
        HeatmapPoint(start_time=0.0, end_time=10.0, value=0.2),
        HeatmapPoint(start_time=10.0, end_time=20.0, value=0.9),
        HeatmapPoint(start_time=20.0, end_time=30.0, value=0.3),
    ]
    pk = HeatmapPeak(
        peak_id="pk1",
        start_time=10.0,
        end_time=20.0,
        center_time=15.0,
        intensity=0.9,
        prominence=0.7,
        width_seconds=10.0,
        classification="GLOBAL_MAXIMA",
        suggested_clip_start=5.0,
        suggested_clip_end=25.0,
    )
    hm_data = HeatmapData(video_id="v_ascii", source="YOUTUBE_HEATMAP", points=pts, peaks=[pk], global_peak=pk)

    waveform = analyzer.render_ascii_curve(hm_data, width=20)
    assert "Viewer Replay Retention Waveform" in waveform
    assert "GLOBAL_MAXIMA" in waveform
    assert "Intensity: 90.0%" in waveform


def test_disk_cache_roundtrip(tmp_path):
    cache_dir = str(tmp_path / "heatmaps")
    analyzer = HeatmapAnalyzer(cache_dir=cache_dir)

    pts = [HeatmapPoint(start_time=0.0, end_time=1.0, value=0.5)]
    hm = HeatmapData(video_id="cached_vid", source="TEST_SOURCE", points=pts, peaks=[])
    
    # Save to disk
    os.makedirs(cache_dir, exist_ok=True)
    with open(os.path.join(cache_dir, "cached_vid.json"), "w", encoding="utf-8") as f:
        json.dump(hm.to_dict(), f)

    loaded = analyzer.extract_heatmap("cached_vid")
    assert loaded.video_id == "cached_vid"
    assert loaded.source == "TEST_SOURCE"
    assert len(loaded.points) == 1
    assert loaded.points[0].value == 0.5
