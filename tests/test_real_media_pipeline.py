"""
Integration test for genuine media rendering and verification (no synthetic fallbacks).
Validates that FFmpeg genuinely renders 1080x1920 portrait video from source media,
probes streams, and passes strict QA verifier.
"""

import os
import subprocess
import pytest
from src.yt_clipping.contracts.models import (
    HighlightCandidate,
    ScoreBreakdown,
    RenderProfile,
    Transcript,
    TranscriptSegment,
    WordTimestamp,
)
from src.yt_clipping.rendering.renderer import FFmpegRenderer
from src.yt_clipping.qa.verifier import MediaQualityVerifier
from src.yt_clipping.ingestion.asset_provider import LocalAssetProvider


def test_genuine_ffmpeg_render_and_strict_qa(tmp_path):
    output_dir = str(tmp_path / "rendered")
    os.makedirs(output_dir, exist_ok=True)
    source_mp4 = str(tmp_path / "source.mp4")

    # 1. Generate real 3-second 1280x720 video with audio using FFmpeg
    cmd = [
        "ffmpeg",
        "-f", "lavfi", "-i", "testsrc=duration=3:size=1280x720:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=3",
        "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
        source_mp4, "-y",
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert res.returncode == 0, f"FFmpeg failed to create test source: {res.stderr.decode()}"

    # 2. Probe genuine source asset
    provider = LocalAssetProvider(allow_mock_fallback=False)
    probe_info = provider.probe_asset(source_mp4)
    assert probe_info["has_video"] is True
    assert probe_info["has_audio"] is True
    assert probe_info["width"] == 1280
    assert probe_info["height"] == 720
    assert abs(probe_info["duration"] - 3.0) < 0.2

    # 3. Setup candidate and real transcript
    cand = HighlightCandidate(
        candidate_id="c_real_01",
        video_id="v_real_01",
        start_seconds=0.5,
        end_seconds=2.5,
        duration_seconds=2.0,
        score=92.0,
        breakdown=ScoreBreakdown(),
        hook_title="Real Highlight Moment",
    )
    transcript = Transcript(
        video_id="v_real_01",
        language="en",
        duration_seconds=3.0,
        text="Real highlight moment in action.",
        segments=[
            TranscriptSegment(
                segment_id=0,
                start=0.5,
                end=2.5,
                text="Real highlight moment in action.",
                words=[
                    WordTimestamp(word="Real", start=0.5, end=0.9),
                    WordTimestamp(word="highlight", start=0.9, end=1.5),
                    WordTimestamp(word="moment", start=1.5, end=2.0),
                    WordTimestamp(word="in", start=2.0, end=2.2),
                    WordTimestamp(word="action.", start=2.2, end=2.5),
                ],
            )
        ],
    )

    # 4. Render with allow_synthetic=False (strict genuine rendering!)
    renderer = FFmpegRenderer(allow_synthetic=False)
    profile = RenderProfile(
        name="vertical_9_16",
        width=1080,
        height=1920,
        layout_mode="blur_background",
        burn_subtitles=True,
    )
    rendered = renderer.render_clip(
        source_path=source_mp4,
        candidate=cand,
        profile=profile,
        output_dir=output_dir,
        transcript=transcript,
    )

    assert rendered is not None
    assert os.path.exists(rendered.file_path)
    assert os.path.getsize(rendered.file_path) > 1000
    assert len(rendered.file_hash) == 64

    # 5. Strict QA verification (no mock fallback)
    verifier = MediaQualityVerifier(strict=True)
    report = verifier.verify_clip(rendered, cand)

    assert report.status == "PASSED", f"QA failed: errors={report.errors}, warnings={report.warnings}"
    assert report.video_stream_ok is True
    assert report.duration_ok is True
    assert report.aspect_ratio_ok is True
    assert report.actual_aspect_ratio == "1080:1920"
    assert rendered.width == 1080
    assert rendered.height == 1920
