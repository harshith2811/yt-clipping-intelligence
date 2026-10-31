"""
Unit and integration tests for Product Audit Synergy Wins,
Executive HTML Reporting, Heatmap Peak-Anchoring, Auto-Layout, and Autoprobe CLI.
"""

import os
import sys
import subprocess
import pytest
from datetime import datetime, timezone

from src.yt_clipping.contracts.models import (
    ClipJob,
    JobStage,
    JobStatus,
    HighlightCandidate,
    ScoreBreakdown,
    RenderProfile,
    RenderedClip,
    QAReport,
    RightsManifest,
    RightsBasis,
    RightsStatus,
    HeatmapData,
    HeatmapPeak,
    HeatmapPoint,
    Transcript,
    TranscriptSegment,
    WordTimestamp,
)
from src.yt_clipping.reporting.html_report import ExecutiveReportGenerator
from src.yt_clipping.detection.segmenter import ContextAwareSegmenter
from src.yt_clipping.rendering.renderer import FFmpegRenderer


def test_executive_report_html_generation(tmp_path):
    """Verifies standalone HTML report generation with all metric cards and sparklines."""
    breakdown = ScoreBreakdown(
        hook_score=9.0,
        moment_score=8.5,
        coherence_score=8.0,
        pacing_score=9.0,
        heatmap_score=9.5,
        confidence=0.92,
        rationale="Exceptional opening question, high-retention audience peak, crisp cadence.",
    )
    score = breakdown.compute_composite_score()

    cand = HighlightCandidate(
        candidate_id="cand-report-test-01",
        video_id="test_vid_123",
        start_seconds=12.5,
        end_seconds=44.0,
        duration_seconds=31.5,
        score=score,
        breakdown=breakdown,
        hook_title="Why Most Systems Fail Under Peak Load",
        suggested_description="Original Content by: @TechVisionary. Watch full video: https://youtu.be/test_vid_123",
        rationale=breakdown.rationale,
    )

    rendered_clip = RenderedClip(
        clip_id="clip-test-01",
        job_id="job-test_vid_123-01",
        candidate_id="cand-report-test-01",
        file_path=str(tmp_path / "test_clip.mp4"),
        file_hash="abcdef1234567890",
        duration_seconds=31.5,
        width=1080,
        height=1920,
        manifest_path=str(tmp_path / "manifest.json"),
        rendered_at=datetime.now(timezone.utc).isoformat(),
    )

    qa_report = QAReport(
        qa_id="qa-01",
        clip_id="clip-test-01",
        status="PASSED",
        video_stream_ok=True,
        audio_stream_ok=True,
        duration_ok=True,
        actual_duration=31.5,
        expected_duration=31.5,
        aspect_ratio_ok=True,
        actual_aspect_ratio="9:16",
        file_size_bytes=1048576,
        errors=[],
        warnings=[],
    )

    rights_manifest = RightsManifest(
        rights_id="rights-test_vid_123-affiliate",
        video_id="test_vid_123",
        basis=RightsBasis.EXPLICIT_PERMISSION,
        status=RightsStatus.VERIFIED,
        owner_name="TechVisionary",
    )

    job = ClipJob(
        job_id="job-test_vid_123-01",
        video_id="test_vid_123",
        current_stage=JobStage.QA_VERIFIED,
        status=JobStatus.SUCCEEDED,
        rights_manifest=rights_manifest,
        candidate=cand,
        rendered_clip=rendered_clip,
        qa_report=qa_report,
    )

    # Mock heatmap points
    pts = [HeatmapPoint(start_time=float(i), end_time=float(i + 1), value=float(i % 10) / 10.0) for i in range(50)]
    heatmap = HeatmapData(
        video_id="test_vid_123",
        source="YOUTUBE_HEATMAP",
        points=pts,
    )

    out_file = str(tmp_path / "executive_report.html")
    generated_path = ExecutiveReportGenerator.generate_html_report(job, heatmap_data=heatmap, output_path=out_file)

    assert os.path.exists(generated_path)
    assert os.path.getsize(generated_path) > 1000

    with open(generated_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "Executive Media Report" in content
    assert "test_vid_123" in content
    assert "Why Most Systems Fail Under Peak Load" in content
    assert "VIRAL READY" in content
    assert "Audience Retention Curve" in content
    assert "Original Content by: @TechVisionary" in content


def test_segmenter_heatmap_peak_anchoring():
    """Verifies that ContextAwareSegmenter synthesizes candidates anchored directly to heatmap peaks."""
    segmenter = ContextAwareSegmenter(default_min_duration=15.0, default_max_duration=45.0, target_duration=30.0)

    # 10 segments of 5 seconds each (50s total)
    segments = [
        TranscriptSegment(
            segment_id=i,
            start=float(i * 5),
            end=float((i + 1) * 5),
            text=f"This is segment number {i} talking about complex topics.",
            words=[
                WordTimestamp(word=w, start=float(i * 5 + j), end=float(i * 5 + j + 0.8))
                for j, w in enumerate(["This", "is", "segment", f"{i}"])
            ]
        )
        for i in range(10)
    ]
    transcript = Transcript(
        video_id="peak_anchor_vid",
        language="en",
        duration_seconds=50.0,
        text="Full text summary here.",
        segments=segments,
    )

    # Heatmap with prominent spike payoff from 15.0s to 40.0s (25.0s duration)
    peak = HeatmapPeak(
        peak_id="peak-01-25s",
        start_time=15.0,
        end_time=35.0,
        center_time=25.0,
        intensity=0.95,
        prominence=0.45,
        width_seconds=20.0,
        classification="GLOBAL_MAXIMA",
        suggested_clip_start=15.0,
        suggested_clip_end=40.0,
    )
    heatmap = HeatmapData(
        video_id="peak_anchor_vid",
        source="YOUTUBE_HEATMAP",
        peaks=[peak],
        global_peak=peak,
    )

    candidates = segmenter.detect_candidates(transcript, heatmap=heatmap)
    assert len(candidates) > 0

    # Verify that a peak-anchored candidate was discovered
    peak_cands = [c for c in candidates if "peak-01-25s" in c.candidate_id or "Audience replay peak" in c.breakdown.rationale]
    assert len(peak_cands) >= 1
    top_peak = peak_cands[0]
    assert abs(top_peak.start_seconds - 15.0) < 0.1
    assert abs(top_peak.end_seconds - 40.0) < 0.1
    assert top_peak.breakdown.heatmap_score >= 9.0


def test_renderer_auto_layout_resolution(tmp_path):
    """Verifies that RenderProfile with layout_mode='auto' resolves dynamic framing without crashing."""
    renderer = FFmpegRenderer(allow_synthetic=True)
    profile = RenderProfile(layout_mode="auto")

    cand = HighlightCandidate(
        candidate_id="cand-auto-01",
        video_id="dummy_vid",
        start_seconds=0.0,
        end_seconds=10.0,
        duration_seconds=10.0,
        score=75.0,
        breakdown=ScoreBreakdown(hook_score=7.0),
        hook_title="Auto Layout Test",
    )

    clip = renderer.render_clip(
        source_path="dummy.mp4",
        candidate=cand,
        profile=profile,
        output_dir=str(tmp_path),
    )

    assert clip is not None
    assert os.path.exists(clip.file_path)
    assert clip.duration_seconds == 10.0


def test_autoprobe_cli_syntax(tmp_path):
    """Verifies that yt-clip autoprobe resolves handle and registers affiliate rights."""
    db_file = str(tmp_path / "test_autoprobe.db")
    cmd = [
        sys.executable,
        "-m",
        "src.yt_clipping.cli.master_cli",
        "autoprobe",
        "--channel",
        "@HubermanLab",
        "--max-videos",
        "1",
        "--db",
        db_file,
        "--dry-run",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert res.returncode == 0
    assert "Autoprobing YouTube creator channel" in res.stdout
    assert "Affiliate Rights Manifest Verified" in res.stdout


def test_dynamic_reel_timestamping_and_durations():
    """
    Verifies that clip duration is completely dynamic:
    - Semantic thought windowing produces varied durations (e.g. 18s, 27s, 50s) matching sentence payoffs.
    - Candidates are NOT forced or penalized towards an arbitrary ~35.0s window.
    - Heatmap peaks derive clip durations dynamically from peak prominence width (FWHM).
    """
    from src.yt_clipping.discovery.heatmap import HeatmapAnalyzer, HeatmapPoint

    # 1. Test Semantic Thought Windowing with varying thought lengths
    # Thought 1: 0 to 18s (punchline payoff)
    # Thought 2: 18 to 44s (26s comparison)
    # Thought 3: 44 to 92s (48s comprehensive breakdown)
    segments = [
        TranscriptSegment(segment_id=1, start=0.0, end=6.0, text="Here is the one mistake everyone makes with AI."),
        TranscriptSegment(segment_id=2, start=6.0, end=12.0, text="They treat it like a search engine instead of an intern."),
        TranscriptSegment(segment_id=3, start=12.0, end=18.0, text="Give it clear instructions and it will blow your mind!"),  # 18.0s complete thought
        TranscriptSegment(segment_id=4, start=18.0, end=27.0, text="Look at the architecture of modern reasoning models."),
        TranscriptSegment(segment_id=5, start=27.0, end=36.0, text="They generate hundreds of hidden tokens before answering."),
        TranscriptSegment(segment_id=6, start=36.0, end=44.0, text="That self-correction loop changes everything completely."),  # 26.0s complete thought (18-44)
        TranscriptSegment(segment_id=7, start=44.0, end=56.0, text="When we tested this across ten thousand production requests."),
        TranscriptSegment(segment_id=8, start=56.0, end=68.0, text="The failure rate dropped from twenty percent down to zero point one percent."),
        TranscriptSegment(segment_id=9, start=68.0, end=80.0, text="And the latency increase was less than forty milliseconds overall."),
        TranscriptSegment(segment_id=10, start=80.0, end=92.0, text="Would you ever go back to single-pass generation after seeing that?"),  # 48.0s complete thought (44-92)
    ]
    transcript = Transcript(
        video_id="dynamic_dur_vid",
        language="en",
        duration_seconds=95.0,
        text="Full transcript text.",
        segments=segments,
    )

    segmenter = ContextAwareSegmenter(default_min_duration=15.0, default_max_duration=60.0, dynamic_windowing=True)
    candidates = segmenter.detect_candidates(transcript, deduplicate=True)

    assert len(candidates) > 0
    durations = [c.duration_seconds for c in candidates]

    # Verify that we have dynamic durations ranging from under 20s to over 40s
    has_short = any(15.0 <= d <= 22.0 for d in durations)
    has_medium = any(23.0 <= d <= 32.0 for d in durations)
    has_long = any(40.0 <= d <= 55.0 for d in durations)

    assert has_short, f"Expected a dynamic short candidate (~18s), got durations: {durations}"
    assert has_medium or has_long, f"Expected varied dynamic durations, got: {durations}"

    # Verify candidates are snapped strictly to sentence completions
    for c in candidates:
        assert c.transcript_text[-1] in [".", "!", "?"], f"Candidate '{c.candidate_id}' does not end on sentence completion"

    # 2. Test Dynamic Heatmap Peak Duration Snapping
    analyzer = HeatmapAnalyzer(cache_dir="data/heatmaps")

    # Sharp 15s spike
    spike_points = [
        HeatmapPoint(start_time=float(i * 2), end_time=float((i + 1) * 2), value=0.2)
        for i in range(50)
    ]
    # Inject spike between 20s and 34s (center 27s)
    for i in range(10, 17):
        spike_points[i] = HeatmapPoint(start_time=float(i * 2), end_time=float((i + 1) * 2), value=0.9)

    spike_peaks = analyzer.detect_peaks(spike_points, total_duration=100.0, transcript=transcript)
    assert len(spike_peaks) > 0
    sharp_pk = spike_peaks[0]
    sharp_dur = sharp_pk.suggested_clip_end - sharp_pk.suggested_clip_start
    # Dynamic sharp peak duration should be around 18-28s, NOT hardcoded 35.0s
    assert 15.0 <= sharp_dur <= 28.0, f"Expected dynamic sharp peak duration ~20s, got {sharp_dur}s"
    assert sharp_dur != 35.0

    # Wide 46s sustained wave
    wide_points = [
        HeatmapPoint(start_time=float(i * 2), end_time=float((i + 1) * 2), value=0.2)
        for i in range(60)
    ]
    for i in range(15, 38):  # 30s to 76s (46s wide)
        wide_points[i] = HeatmapPoint(start_time=float(i * 2), end_time=float((i + 1) * 2), value=0.85)

    wide_peaks = analyzer.detect_peaks(wide_points, total_duration=120.0, transcript=transcript)
    assert len(wide_peaks) > 0
    wide_pk = wide_peaks[0]
    wide_dur = wide_pk.suggested_clip_end - wide_pk.suggested_clip_start
    # Dynamic wide peak duration should naturally encompass the engagement zone (~45-55s), NOT forced to 35.0s
    assert 40.0 <= wide_dur <= 58.0, f"Expected dynamic wide peak duration ~48s, got {wide_dur}s"
    assert wide_dur != 35.0
