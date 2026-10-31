"""
Root entrypoint for TrendScorer.
Allows direct execution or import via `import trend_scorer`.
"""

from src.yt_clipping.discovery.trend_scorer import (
    TrendScorer,
    ViralityClassification,
    VelocityTelemetry,
)

__all__ = ["TrendScorer", "ViralityClassification", "VelocityTelemetry"]

if __name__ == "__main__":
    scorer = TrendScorer()
    res = scorer.evaluate_video(
        video_id="demo-test",
        channel_id="demo-channel",
        title="Sample Breakout Upload",
        published_at_iso="2026-10-31T12:00:00Z",
        view_count=45000,
        like_count=3200,
        comment_count=410,
        baseline_views=15000.0,
    )
    print("TrendScorer Evaluation:")
    for k, v in res.to_dict().items():
        print(f"  {k:<22}: {v}")
