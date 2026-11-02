"""
Unit and Integration Tests for Constrained 1D Camera Trajectory Optimization.
Validates mathematical constraints: viewport bounds, kinematic limits (v_max, a_max),
deadband hysteresis, shot discontinuity resets, missing value imputations,
FFmpeg crop expressions, and FaceFocusedFramer integration.
"""

import time
import subprocess
import pytest
import numpy as np

from yt_clipping.rendering.face_tracker import (
    ConstrainedTrajectoryOptimizer,
    TrajectoryConfig,
    KinematicSegment,
    TrajectoryResult,
    FaceFocusedFramer,
)


# 1. Viewport Bounds Clamping
def test_viewport_bounds_clamping():
    config = TrajectoryConfig(canvas_width=1920, crop_width=608, fps=30.0)
    optimizer = ConstrainedTrajectoryOptimizer(config)

    raw_centers = [-500.0, 0.0, 100.0, 1850.0, 2500.0]
    result = optimizer.optimize(raw_centers)

    c_min = 608.0 / 2.0  # 304.0
    c_max = 1920.0 - 608.0 / 2.0  # 1616.0
    x_max = 1920 - 608  # 1312

    for c in result.smoothed_centers:
        assert c_min <= c <= c_max

    for x in result.smoothed_crop_x:
        assert 0 <= x <= x_max
        assert x % 2 == 0


# 2. Velocity Limit Enforcement
def test_velocity_limit_enforcement():
    config = TrajectoryConfig(
        canvas_width=1920,
        crop_width=608,
        fps=30.0,
        max_velocity=450.0,
        scene_cut_threshold=1.0,
        solver_mode="kinematic",
    )
    optimizer = ConstrainedTrajectoryOptimizer(config)

    # Subject jumps across frame within single shot
    raw_centers = [400.0] * 10 + [1500.0] * 40
    result = optimizer.optimize(raw_centers)

    dt = 1.0 / 30.0
    diffs = np.abs(np.diff(result.smoothed_centers))
    vels = diffs / dt

    for v in vels:
        assert v <= 450.0 + 1e-3
    assert result.max_observed_velocity <= 450.0 + 1e-3


# 3. Acceleration Limit & Smooth Ramp
def test_acceleration_limit_smooth_ramp():
    config = TrajectoryConfig(
        canvas_width=1920,
        crop_width=608,
        fps=30.0,
        max_velocity=600.0,
        max_acceleration=750.0,
        scene_cut_threshold=1.0,
        solver_mode="kinematic",
    )
    optimizer = ConstrainedTrajectoryOptimizer(config)

    # Subject starts rapid pan from standstill
    raw_centers = [500.0] * 5 + [1400.0] * 35
    result = optimizer.optimize(raw_centers)

    dt = 1.0 / 30.0
    diffs = np.diff(result.smoothed_centers)
    vels = diffs / dt
    accs = np.abs(np.diff(vels)) / dt

    for a in accs:
        assert a <= 750.0 + 1e-3

    # Initial velocity starts smoothly from near 0
    assert abs(vels[0]) <= 750.0 * dt + 1e-3


# 4. Deadband Suppresses Micro-Jitter
def test_deadband_suppresses_micro_jitter():
    config = TrajectoryConfig(
        canvas_width=1920,
        crop_width=608,
        fps=30.0,
        deadband_px=24.0,
    )
    optimizer = ConstrainedTrajectoryOptimizer(config)

    # Subject fluctuates randomly within +/- 10px around 960
    np.random.seed(42)
    noise = np.random.uniform(-10.0, 10.0, size=60)
    raw_centers = (960.0 + noise).tolist()

    result = optimizer.optimize(raw_centers)

    # All crop positions should be locked to anchor
    first_x = result.smoothed_crop_x[0]
    for x in result.smoothed_crop_x:
        assert x == first_x

    assert result.max_observed_velocity == 0.0
    assert not result.is_dynamic_pan


# 5. Backward Pass Prevents Overshoot
def test_backward_pass_prevents_overshoot():
    config = TrajectoryConfig(
        canvas_width=1920,
        crop_width=608,
        fps=30.0,
        max_velocity=450.0,
        max_acceleration=750.0,
        solver_mode="kinematic",
    )
    optimizer = ConstrainedTrajectoryOptimizer(config)

    # Subject moves from 400 to 1200 and stops abruptly
    raw_centers = [400.0] * 10 + [1200.0] * 50
    result = optimizer.optimize(raw_centers)

    # Camera should decelerate smoothly without crossing target or oscillating
    assert np.max(result.smoothed_centers) <= 1200.0 + 1e-3


# 6. Scene Cut Instant Reset
def test_scene_cut_instant_reset():
    config = TrajectoryConfig(
        canvas_width=1920,
        crop_width=608,
        fps=30.0,
        max_velocity=450.0,
    )
    optimizer = ConstrainedTrajectoryOptimizer(config)

    # Shot 1: 0.0s to 3.0s (90 frames) at x=400
    # Shot 2: 3.0s to 6.0s (90 frames) at x=1500
    raw_centers = [400.0] * 90 + [1500.0] * 90
    timestamps = [i / 30.0 for i in range(180)]
    scene_cuts = [3.0]

    result = optimizer.optimize(raw_centers, timestamps=timestamps, scene_cuts=scene_cuts)

    # At cut frame index 90 (t=3.0s), camera jumps instantaneously
    assert result.smoothed_crop_x[89] == (400 - 304) // 2 * 2  # around 96
    assert result.smoothed_crop_x[90] == (1500 - 304) // 2 * 2  # around 1196

    # Verify a cut segment is recorded
    cut_segments = [s for s in result.segments if s.mode == "cut"]
    assert len(cut_segments) >= 1
    assert cut_segments[0].start_crop_x != cut_segments[0].end_crop_x


# 7. Missing Detection Interpolation
def test_missing_detection_interpolation():
    config = TrajectoryConfig(canvas_width=1920, crop_width=608, fps=30.0)
    optimizer = ConstrainedTrajectoryOptimizer(config)

    # Sequence with intermittent None values (dropouts)
    raw_centers = [500.0] * 10 + [None] * 5 + [700.0] * 15
    result = optimizer.optimize(raw_centers)

    assert len(result.smoothed_centers) == len(raw_centers)
    assert not np.any(np.isnan(result.smoothed_centers))

    # The missing gap (frames 10-14) should interpolate monotonically between 500 and 700
    gap = result.smoothed_centers[10:15]
    assert np.all(np.diff(gap) >= -1e-4)


# 8. Empty and All-None Input Fallback
def test_empty_and_all_none_input():
    config = TrajectoryConfig(canvas_width=1920, crop_width=608, fps=30.0)
    optimizer = ConstrainedTrajectoryOptimizer(config)

    expected_x = (1920 - 608) // 2
    if expected_x % 2 != 0:
        expected_x -= 1

    # Empty list
    res_empty = optimizer.optimize([])
    assert len(res_empty.smoothed_crop_x) == 1
    assert res_empty.smoothed_crop_x[0] == expected_x
    assert f"crop=608:1080:{expected_x}:0" in res_empty.ffmpeg_crop_filter

    # All None
    res_none = optimizer.optimize([None] * 50)
    assert len(res_none.smoothed_crop_x) == 50
    for x in res_none.smoothed_crop_x:
        assert x == expected_x
    assert f"crop=608:1080:{expected_x}:0" in res_none.ffmpeg_crop_filter


# 9. FFmpeg Crop Expression Syntax
def test_ffmpeg_crop_expression_syntax():
    config = TrajectoryConfig(canvas_width=1920, crop_width=608, fps=30.0)
    optimizer = ConstrainedTrajectoryOptimizer(config)

    # Moving sequence generating pan and cuts
    raw_centers = [400.0] * 30 + [1400.0] * 30
    res = optimizer.optimize(raw_centers, scene_cuts=[1.0])

    expr = res.ffmpeg_crop_filter
    assert expr.startswith("crop=608:1080:")

    # Parentheses balance check
    assert expr.count("(") == expr.count(")")
    assert expr.count("'") % 2 == 0


# 10. FaceFocusedFramer Smoothing Mode Switch
def test_framer_smoothing_mode_switch(tmp_path):
    # Create small 2-second test video
    mp4_path = str(tmp_path / "test_framer.mp4")
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=10",
        "-t", "2", "-c:v", "libx264", mp4_path
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    # Constrained mode (default)
    framer_c = FaceFocusedFramer(smoothing_mode="constrained")
    res_c = framer_c.analyze_crop_window(mp4_path, start_seconds=0.0, duration_seconds=2.0)
    assert "trajectory" in res_c
    assert "ffmpeg_crop_filter" in res_c
    assert res_c["crop_w"] > 0
    assert res_c["crop_h"] > 0

    # EMA mode (legacy)
    framer_ema = FaceFocusedFramer(smoothing_mode="ema")
    res_ema = framer_ema.analyze_crop_window(mp4_path, start_seconds=0.0, duration_seconds=2.0)
    assert "trajectory" not in res_ema
    assert "ffmpeg_crop_filter" in res_ema


# 11. Execution Latency and Zero VRAM
def test_execution_latency_and_zero_vram():
    config = TrajectoryConfig(
        canvas_width=1920,
        crop_width=608,
        fps=30.0,
        solver_mode="hybrid",
    )
    optimizer = ConstrainedTrajectoryOptimizer(config)

    # 1000 frames (approx 33 seconds of video)
    np.random.seed(123)
    raw_centers = (960.0 + np.cumsum(np.random.normal(0, 5, 1000))).tolist()

    t_start = time.perf_counter()
    result = optimizer.optimize(raw_centers)
    elapsed_ms = (time.perf_counter() - t_start) * 1000.0

    assert len(result.smoothed_centers) == 1000
    assert elapsed_ms < 150.0  # Must be fast CPU vectorized (< 150ms for 33s video)


# 12. Dense Solver Fallback when solveh_banded is None
def test_dense_solver_fallback_when_solveh_banded_none(monkeypatch):
    import yt_clipping.rendering.face_tracker as ft

    monkeypatch.setattr(ft, "solveh_banded", None)

    config = TrajectoryConfig(
        canvas_width=1920,
        crop_width=608,
        fps=30.0,
        solver_mode="convex",
    )
    optimizer = ConstrainedTrajectoryOptimizer(config)

    raw_centers = [400.0] * 10 + [1500.0] * 40
    result = optimizer.optimize(raw_centers)

    c_min = 608.0 / 2.0  # 304.0
    c_max = 1920.0 - 608.0 / 2.0  # 1616.0
    x_max = 1920 - 608  # 1312

    assert len(result.smoothed_centers) == 50
    for c in result.smoothed_centers:
        assert c_min <= c <= c_max

    for x in result.smoothed_crop_x:
        assert 0 <= x <= x_max
        assert x % 2 == 0

    # Also verify under hybrid mode
    config_hybrid = TrajectoryConfig(
        canvas_width=1920,
        crop_width=608,
        fps=30.0,
        solver_mode="hybrid",
    )
    optimizer_hybrid = ConstrainedTrajectoryOptimizer(config_hybrid)
    result_hybrid = optimizer_hybrid.optimize(raw_centers)
    assert len(result_hybrid.smoothed_centers) == 50
    for c in result_hybrid.smoothed_centers:
        assert c_min <= c <= c_max

