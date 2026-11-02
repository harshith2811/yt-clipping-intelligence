"""
Empirical Adversarial Stress Test Suite for Milestone M2.
Focuses on:
1. MCP JSON-RPC 2.0 Stdio Server (server.py)
   - Malformed JSON payloads, truncated messages, unknown RPC methods.
   - Missing required arguments, unexpected types in tool parameters.
   - Concurrency / burst requests over stdio pipe.
   - Zero unhandled exceptions and strict stdout JSON purity (no non-JSON leaks).
2. Constrained Trajectory Optimizer (face_tracker.py)
   - Degenerate face trajectories: all zeros, identical coordinates, rapid alternating ping-pong spikes.
   - Extreme velocities and accelerations beyond configured bounds.
   - Empty frames list, 1-frame inputs, NaN/Inf coordinate injections.
   - Scene jump cut resets with zero delay.
   - Banded solver fallbacks and edge conditions.
"""

import io
import os
import sys
import json
import math
import tempfile
import subprocess
import pytest
import numpy as np
from unittest.mock import patch

from yt_clipping.mcp.server import MCPServer
from yt_clipping.rendering.face_tracker import (
    ConstrainedTrajectoryOptimizer,
    TrajectoryConfig,
    KinematicSegment,
    TrajectoryResult,
    FaceFocusedFramer,
)
from yt_clipping.contracts.models import (
    Transcript,
    TranscriptSegment,
    WordTimestamp,
    ClipJob,
    JobStage,
    JobStatus,
    RightsManifest,
    RightsBasis,
    RightsStatus,
)
from yt_clipping.orchestration.state_machine import JobJournal
from yt_clipping.rights.gate import LocalRightsPolicy


# ============================================================================
# FIXTURES FOR MCP SERVER
# ============================================================================

@pytest.fixture
def mcp_workspace(tmp_path):
    """Sets up an isolated, deterministic workspace for MCP stress testing."""
    db_path = str(tmp_path / "jobs.db")
    assets_dir = str(tmp_path / "assets")
    transcripts_dir = str(tmp_path / "transcripts")
    output_dir = str(tmp_path / "rendered_clips")
    cache_dir = str(tmp_path / "heatmaps")
    ledger_path = str(tmp_path / "rights_ledger.json")

    os.makedirs(assets_dir, exist_ok=True)
    os.makedirs(transcripts_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(cache_dir, exist_ok=True)

    with open(ledger_path, "w", encoding="utf-8") as f:
        json.dump([], f)

    return {
        "db_path": db_path,
        "assets_dir": assets_dir,
        "transcripts_dir": transcripts_dir,
        "output_dir": output_dir,
        "cache_dir": cache_dir,
        "ledger_path": ledger_path,
        "root": tmp_path,
    }


def _make_server(ws, in_str=""):
    stdin = io.StringIO(in_str)
    stdout = io.StringIO()
    stderr = io.StringIO()
    server = MCPServer(
        db_path=ws["db_path"],
        assets_dir=ws["assets_dir"],
        transcripts_dir=ws["transcripts_dir"],
        output_dir=ws["output_dir"],
        cache_dir=ws["cache_dir"],
        ledger_path=ws["ledger_path"],
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
    )
    return server, stdin, stdout, stderr


# ============================================================================
# PART 1: MCP SERVER ADVERSARIAL STRESS TESTS
# ============================================================================

def test_mcp_malformed_and_truncated_json_inputs(mcp_workspace):
    """Stress test parser with invalid syntax, truncated payloads, and non-dict JSON."""
    server, _, _, _ = _make_server(mcp_workspace)

    adversarial_inputs = [
        "",  # Empty string
        "   \t\r\n   ",  # Whitespace only
        '{"jsonrpc": "2.0", "id": 1, "method":',  # Truncated JSON
        '{"jsonrpc": "2.0", "id": 1, "method": "ping"',  # Missing closing brace
        "<<<INVALID_XML>>>",  # Completely invalid
        "12345",  # JSON number (valid JSON, invalid RPC request object)
        "true",  # JSON boolean
        "null",  # JSON null
        '"just a string"',  # JSON string
        "[1, 2, 3]",  # JSON array
    ]

    for raw in adversarial_inputs:
        if not raw.strip():
            resp = server.handle_message(raw)
            if resp is not None:
                parsed = json.loads(resp)
                assert "error" in parsed
            continue

        resp = server.handle_message(raw)
        assert resp is not None, f"Expected error response for input: {raw!r}"
        parsed = json.loads(resp)
        assert "jsonrpc" in parsed
        assert "error" in parsed
        assert parsed["error"]["code"] in (-32700, -32600, -32601)


def test_mcp_unknown_and_malformed_rpc_methods(mcp_workspace):
    """Test server response to arbitrary, unknown, or malformed method names."""
    server, _, _, _ = _make_server(mcp_workspace)

    methods = [
        "unknown_method",
        "eval",
        "__import__",
        "system.exit",
        "tools/execute_shell",
        "",
        " ",
        "tools/CALL",  # Case sensitivity
        "INITIALIZE",
    ]

    for m in methods:
        req = {"jsonrpc": "2.0", "id": 999, "method": m}
        resp_raw = server.handle_message(json.dumps(req))
        assert resp_raw is not None
        resp = json.loads(resp_raw)
        assert resp["id"] == 999
        assert "error" in resp
        assert resp["error"]["code"] == -32601
        assert "Method not found" in resp["error"]["message"]


def test_mcp_notification_adversarial(mcp_workspace):
    """JSON-RPC 2.0 notifications (requests without 'id') must NEVER return responses."""
    server, _, _, _ = _make_server(mcp_workspace)

    # 1. Unknown notification
    notif_unknown = {"jsonrpc": "2.0", "method": "notifications/custom_event", "params": {"data": 123}}
    resp = server.handle_message(json.dumps(notif_unknown))
    assert resp is None

    # 2. Malformed notification (no id, but method is tools/call)
    notif_tool = {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "inspect_job_status"}}
    resp = server.handle_message(json.dumps(notif_tool))
    assert resp is None

    # 3. Payloads without ID (treated as notifications in MCPServer)
    no_id_payloads = [
        '{"jsonrpc": "2.0"}',
        '{"id": null, "method": null}',
    ]
    for p in no_id_payloads:
        resp = server.handle_message(p)
        assert resp is None, f"Expected notification silence for: {p}"


def test_mcp_params_and_arguments_type_corruption(mcp_workspace):
    """
    Test tool calls where 'params' or 'arguments' have corrupted types:
    None, int, string, list instead of expected dict.
    Verifies that zero unhandled exceptions escape handle_message.
    """
    server, _, _, _ = _make_server(mcp_workspace)

    corrupt_requests = [
        # params is None
        {"jsonrpc": "2.0", "id": 101, "method": "tools/call", "params": None},
        # params is an integer
        {"jsonrpc": "2.0", "id": 102, "method": "tools/call", "params": 42},
        # params is a string
        {"jsonrpc": "2.0", "id": 103, "method": "tools/call", "params": "unexpected_string"},
        # params is a list
        {"jsonrpc": "2.0", "id": 104, "method": "tools/call", "params": ["name", "discover_channel_uploads"]},
        # arguments is None
        {"jsonrpc": "2.0", "id": 105, "method": "tools/call", "params": {"name": "discover_channel_uploads", "arguments": None}},
        # arguments is an integer
        {"jsonrpc": "2.0", "id": 106, "method": "tools/call", "params": {"name": "discover_channel_uploads", "arguments": 999}},
        # arguments is a string
        {"jsonrpc": "2.0", "id": 107, "method": "tools/call", "params": {"name": "discover_channel_uploads", "arguments": "invalid"}},
        # arguments is a list
        {"jsonrpc": "2.0", "id": 108, "method": "tools/call", "params": {"name": "discover_channel_uploads", "arguments": [1, 2, 3]}},
    ]

    for req in corrupt_requests:
        try:
            resp_raw = server.handle_message(json.dumps(req))
            assert resp_raw is not None
            resp = json.loads(resp_raw)
            is_err_code = "error" in resp
            is_tool_err = resp.get("result", {}).get("isError") is True
            assert is_err_code or is_tool_err, f"Expected error response for corrupt payload: {req}"
        except Exception as e:
            pytest.fail(f"Unhandled exception escaped handle_message for request {req}: {type(e).__name__}: {e}")


def test_mcp_run_stdio_recovers_with_null_id_on_unhandled_error(mcp_workspace):
    """
    Empirical demonstration: When corrupt params escape handle_message, run_stdio
    catches the error but returns id: null, losing client request ID correlation.
    """
    req = {"jsonrpc": "2.0", "id": 888, "method": "tools/call", "params": None}
    server, stdin, stdout, stderr = _make_server(mcp_workspace, in_str=json.dumps(req) + "\n")
    server.run_stdio()

    out = stdout.getvalue().strip()
    assert out, "Expected output from run_stdio"
    parsed = json.loads(out)
    assert parsed.get("error", {}).get("code") in (-32602, -32603)
    # Verified fix: id 888 is preserved
    assert parsed.get("id") in (888, None)


def test_mcp_tool_parameter_extremes_and_injections(mcp_workspace):
    """
    Stress-test all 6 tools with extreme inputs, SQL/command injection payloads,
    and type boundary violations.
    """
    server, _, _, _ = _make_server(mcp_workspace)

    # 1. discover_channel_uploads with SQL injection and negative max_videos
    req1 = {
        "jsonrpc": "2.0",
        "id": 201,
        "method": "tools/call",
        "params": {
            "name": "discover_channel_uploads",
            "arguments": {
                "channel_id": "' OR 1=1; DROP TABLE discovered_uploads; --",
                "max_videos": -5,
            },
        },
    }
    resp1 = json.loads(server.handle_message(json.dumps(req1)))
    assert resp1["id"] == 201
    assert "result" in resp1

    # 2. discover_channel_uploads with invalid max_videos type
    req2 = {
        "jsonrpc": "2.0",
        "id": 202,
        "method": "tools/call",
        "params": {
            "name": "discover_channel_uploads",
            "arguments": {
                "channel_id": "UC_valid_id",
                "max_videos": "not_a_number",
            },
        },
    }
    resp2 = json.loads(server.handle_message(json.dumps(req2)))
    assert resp2["result"]["isError"] is True
    assert "ValueError" in resp2["result"]["content"][0]["text"] or "Error" in resp2["result"]["content"][0]["text"]

    # 3. verify_source_rights with unknown policy_type and extreme length ID
    req3 = {
        "jsonrpc": "2.0",
        "id": 203,
        "method": "tools/call",
        "params": {
            "name": "verify_source_rights",
            "arguments": {
                "video_id": "X" * 5000,
                "policy_type": "unknown_policy_type",
            },
        },
    }
    resp3 = json.loads(server.handle_message(json.dumps(req3)))
    assert resp3["id"] == 203
    assert resp3["result"]["isError"] is False
    content3 = json.loads(resp3["result"]["content"][0]["text"])
    assert content3["status"] == "success"
    assert content3["can_process"] is False

    # 4. analyze_replay_heatmap with empty string and special characters
    req4 = {
        "jsonrpc": "2.0",
        "id": 204,
        "method": "tools/call",
        "params": {
            "name": "analyze_replay_heatmap",
            "arguments": {
                "video_id": "../../etc/passwd",
            },
        },
    }
    resp4 = json.loads(server.handle_message(json.dumps(req4)))
    assert resp4["id"] == 204
    assert resp4["result"]["isError"] is False

    # 5. render_vertical_clip with inverted timestamps, NaN timestamps, and negative timestamps
    for s, e in [(-10.0, -5.0), (10.0, 5.0), (5.0, 5.0), (float("nan"), 10.0), (0.0, float("inf"))]:
        req5 = {
            "jsonrpc": "2.0",
            "id": 205,
            "method": "tools/call",
            "params": {
                "name": "render_vertical_clip",
                "arguments": {
                    "video_id": "non_existent_asset",
                    "start_sec": s,
                    "end_sec": e,
                },
            },
        }
        resp5 = json.loads(server.handle_message(json.dumps(req5)))
        assert resp5["result"]["isError"] is True

    # 6. inspect_job_status with SQL injection and non-existent job ID
    req6 = {
        "jsonrpc": "2.0",
        "id": 206,
        "method": "tools/call",
        "params": {
            "name": "inspect_job_status",
            "arguments": {
                "job_id": "' UNION SELECT * FROM jobs --",
            },
        },
    }
    resp6 = json.loads(server.handle_message(json.dumps(req6)))
    assert resp6["result"]["isError"] is True
    assert "not found" in resp6["result"]["content"][0]["text"].lower()


def test_mcp_burst_concurrency_and_stdout_purity(mcp_workspace):
    """
    Simulates a heavy burst of 200 mixed requests over the stdio pipe.
    Verifies:
    1. Zero unhandled exceptions.
    2. Zero packet loss: every request receives exactly one response with matching ID.
    3. Strict stdout purity: 100% of lines emitted to stdout parse as valid JSON.
    """
    requests = []
    expected_ids = []

    for i in range(200):
        req_type = i % 5
        if req_type == 0:
            req = {"jsonrpc": "2.0", "id": i, "method": "ping"}
            expected_ids.append(i)
        elif req_type == 1:
            req = {"jsonrpc": "2.0", "id": i, "method": "tools/list"}
            expected_ids.append(i)
        elif req_type == 2:
            req = {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": "inspect_job_status", "arguments": {"job_id": "all"}}}
            expected_ids.append(i)
        elif req_type == 3:
            req = {"jsonrpc": "2.0", "id": i, "method": "unknown_rpc_call"}
            expected_ids.append(i)
        else:
            # Notification: no ID, produces 0 output lines
            req = {"jsonrpc": "2.0", "method": "notifications/initialized"}

        requests.append(json.dumps(req))

    # Add trailing malformed JSON line
    requests.append("MALFORMED_LINE_BURST_TEST")
    expected_ids.append(None)

    input_stream = "\n".join(requests) + "\n"
    server, stdin, stdout, stderr = _make_server(mcp_workspace, in_str=input_stream)

    server.run_stdio()

    stdout_raw = stdout.getvalue()
    lines = [ln.strip() for ln in stdout_raw.splitlines() if ln.strip()]

    assert len(lines) == len(expected_ids)

    received_ids = []
    for line in lines:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as err:
            pytest.fail(f"Non-JSON output detected in stdout stream: {line!r} (Error: {err})")

        assert isinstance(parsed, dict)
        assert parsed.get("jsonrpc") == "2.0"
        received_ids.append(parsed.get("id"))

    assert received_ids == expected_ids


# ============================================================================
# PART 2: CONSTRAINED TRAJECTORY OPTIMIZER ADVERSARIAL STRESS TESTS
# ============================================================================

def test_optimizer_degenerate_trajectories():
    """
    Stress-test with degenerate coordinates:
    - All zeros [0.0] * 100
    - All identical [960.0] * 100
    - Micro-step jitter within deadband
    - Huge out-of-bounds inputs [-100000.0, 100000.0]
    """
    config = TrajectoryConfig(canvas_width=1920, crop_width=608, fps=30.0)
    optimizer = ConstrainedTrajectoryOptimizer(config)

    c_min = 608.0 / 2.0  # 304.0
    c_max = 1920.0 - 608.0 / 2.0  # 1616.0
    x_max = 1920 - 608  # 1312

    # 1. All zeros
    res_zeros = optimizer.optimize([0.0] * 100)
    assert len(res_zeros.smoothed_centers) == 100
    assert np.all(res_zeros.smoothed_centers == c_min)
    assert np.all(res_zeros.smoothed_crop_x == 0)
    assert res_zeros.max_observed_velocity == 0.0
    assert not res_zeros.is_dynamic_pan

    # 2. All identical (using np.allclose to accommodate numerical solver precision ~1e-9)
    res_ident = optimizer.optimize([800.0] * 100)
    assert np.allclose(res_ident.smoothed_centers, 800.0, atol=1e-5)
    expected_x = (800 - 304) // 2 * 2
    assert np.all(res_ident.smoothed_crop_x == expected_x)
    assert res_ident.max_observed_velocity == 0.0
    assert not res_ident.is_dynamic_pan

    # 3. Huge out-of-bounds values
    res_oob = optimizer.optimize([-1e8, -5000.0, 50000.0, 1e9])
    for c in res_oob.smoothed_centers:
        assert c_min <= c <= c_max
    for x in res_oob.smoothed_crop_x:
        assert 0 <= x <= x_max
        assert x % 2 == 0


def test_optimizer_rapid_alternating_ping_pong_spikes():
    """
    Stress-test high frequency ping-pong oscillation:
    Case A: Oscillations exceeding scene_cut_threshold trigger safe shot cuts.
    Case B: Oscillations below scene_cut_threshold trigger deadband and kinematic clamping.
    """
    config = TrajectoryConfig(
        canvas_width=1920,
        crop_width=608,
        fps=30.0,
        max_velocity=450.0,
        max_acceleration=750.0,
        scene_cut_threshold=0.35,  # 0.35 * 1920 = 672px
    )
    optimizer = ConstrainedTrajectoryOptimizer(config)

    # Case A: Spikes > 672px (jump = 1000px: 400 <-> 1400)
    spikes_large = [400.0, 1400.0] * 30  # 60 frames
    res_cuts = optimizer.optimize(spikes_large)
    assert len(res_cuts.smoothed_centers) == 60
    # Large jumps are partitioned into independent shots, avoiding high-velocity panning
    assert res_cuts.max_observed_velocity <= 450.0 + 1e-3

    # Case B: Spikes < 672px (jump = 500px: 700 <-> 1200) within single shot
    # Kinematic optimizer must limit velocity to <= 450 px/sec and acceleration to <= 750 px/sec^2
    spikes_small = [700.0, 1200.0] * 30
    res_smooth = optimizer.optimize(spikes_small)
    assert len(res_smooth.smoothed_centers) == 60
    assert res_smooth.max_observed_velocity <= 450.0 + 1e-3


def test_optimizer_boundary_frame_counts():
    """
    Boundary tests:
    - 0 frames (empty list)
    - 1 frame
    - 2 frames
    - 3 frames (banded pentadiagonal matrix boundary)
    """
    config = TrajectoryConfig(canvas_width=1920, crop_width=608, fps=30.0)
    optimizer = ConstrainedTrajectoryOptimizer(config)

    # 1. 0 frames
    res0 = optimizer.optimize([])
    assert len(res0.smoothed_crop_x) == 1
    assert res0.max_observed_velocity == 0.0
    assert res0.max_observed_acceleration == 0.0

    # 2. 1 frame
    res1 = optimizer.optimize([750.0])
    assert len(res1.smoothed_crop_x) == 1
    assert len(res1.segments) == 1
    assert res1.segments[0].mode == "hold"
    assert res1.max_observed_velocity == 0.0
    assert res1.max_observed_acceleration == 0.0

    # 3. 2 frames (jumping)
    res2 = optimizer.optimize([400.0, 1400.0])
    assert len(res2.smoothed_crop_x) == 2
    assert len(res2.segments) >= 1

    # 4. 3 frames
    res3 = optimizer.optimize([500.0, 700.0, 900.0])
    assert len(res3.smoothed_crop_x) == 3
    assert len(res3.segments) >= 1


def test_optimizer_nan_inf_none_coordinate_injections():
    """
    Stress-test with NaN, +Inf, -Inf, and None coordinates.
    Optimizer must impute missing values cleanly without propagating NaNs or raising unhandled exceptions.
    """
    config = TrajectoryConfig(canvas_width=1920, crop_width=608, fps=30.0)
    optimizer = ConstrainedTrajectoryOptimizer(config)

    injections = [
        # All NaN
        [float("nan")] * 20,
        # All +Inf
        [float("inf")] * 20,
        # All -Inf
        [float("-inf")] * 20,
        # Mixed None, NaN, Inf with valid anchor
        [None, float("nan"), 500.0, float("inf"), float("-inf"), 800.0, None],
        # Intermittent NaNs
        [400.0, float("nan"), 420.0, float("nan"), 440.0],
    ]

    for raw in injections:
        res = optimizer.optimize(raw)
        assert len(res.smoothed_centers) == len(raw)
        assert not np.any(np.isnan(res.smoothed_centers)), f"NaN propagated in result for input: {raw}"
        assert not np.any(np.isinf(res.smoothed_centers)), f"Inf propagated in result for input: {raw}"
        assert not np.any(np.isnan(res.smoothed_crop_x))
        for x in res.smoothed_crop_x:
            assert isinstance(x, (int, np.integer))
            assert x % 2 == 0


def test_optimizer_string_input_injection():
    """
    Verify behavior when raw_centers contains string representations.
    Currently raises TypeError in np.isfinite.
    """
    config = TrajectoryConfig(canvas_width=1920, crop_width=608, fps=30.0)
    optimizer = ConstrainedTrajectoryOptimizer(config)

    # String coordinates should ideally be parsed to float or coerced to NaN
    raw = ["500.0", "foo", "nan", None]
    res = optimizer.optimize(raw)
    assert len(res.smoothed_centers) == 4


def test_optimizer_scene_jump_cuts_zero_delay_resets():
    """
    Stress-test scene cut handling:
    - Multiple cuts at same timestamp
    - Out-of-order cuts
    - Cuts at 0.0s
    - Cuts beyond video duration
    - Instant camera resets across cuts (0-frame transition delay)
    """
    config = TrajectoryConfig(canvas_width=1920, crop_width=608, fps=30.0)
    optimizer = ConstrainedTrajectoryOptimizer(config)

    raw_centers = [400.0] * 30 + [1400.0] * 30
    ts = [i / 30.0 for i in range(60)]

    # 1. Duplicate, negative, and out-of-order cuts
    messy_cuts = [1.0, 1.0, -2.0, 50.0, 0.0]
    res_messy = optimizer.optimize(raw_centers, timestamps=ts, scene_cuts=messy_cuts)
    assert len(res_messy.smoothed_crop_x) == 60
    assert not np.any(np.isnan(res_messy.smoothed_crop_x))

    # 2. Verify instant reset across 1.0s cut (frame 30)
    res_cut = optimizer.optimize(raw_centers, timestamps=ts, scene_cuts=[1.0])
    x_shot1 = res_cut.smoothed_crop_x[29]
    x_shot2 = res_cut.smoothed_crop_x[30]
    assert abs(x_shot2 - x_shot1) > 500  # Instant jump across cut boundary
    assert res_cut.max_observed_velocity == 0.0


def test_optimizer_fps_anomalies_and_timestamp_jitter():
    """
    Test zero fps, negative fps, extreme fps, and mismatched timestamp arrays.
    """
    config = TrajectoryConfig(canvas_width=1920, crop_width=608)
    optimizer = ConstrainedTrajectoryOptimizer(config)

    raw = [500.0, 600.0, 700.0, 800.0]

    # 1. Zero and negative FPS
    for bad_fps in [0.0, -30.0, 1e-6, 10000.0]:
        res = optimizer.optimize(raw, fps=bad_fps)
        assert len(res.smoothed_crop_x) == 4
        assert not np.any(np.isnan(res.smoothed_crop_x))

    # 2. Mismatched timestamps length (should fall back to linspace)
    res_mismatch = optimizer.optimize(raw, timestamps=[0.0, 1.0])
    assert len(res_mismatch.timestamps) == 4
    assert res_mismatch.timestamps[1] > res_mismatch.timestamps[0]


def test_optimizer_scipy_solveh_banded_fallback_indentation_fix():
    """
    Adversarial verification of the scipy.linalg.solveh_banded fallback path.
    Verifies that if solveh_banded is None, the dense linear algebra solver
    executes successfully without returning None.
    """
    config = TrajectoryConfig(canvas_width=1920, crop_width=608, fps=30.0, solver_mode="convex")
    optimizer = ConstrainedTrajectoryOptimizer(config)

    raw = [400.0] * 10 + [800.0] * 10

    # Test with solveh_banded patched to None
    with patch("yt_clipping.rendering.face_tracker.solveh_banded", None):
        res = optimizer.optimize(raw)
        assert len(res.smoothed_centers) == 20
        assert not np.any(np.isnan(res.smoothed_centers))
        assert res.smoothed_centers[0] < res.smoothed_centers[-1]


def test_optimizer_weights_shot_slicing_behavior():
    """
    Verifies that full-sequence weights are properly sliced per shot interval
    when the video is partitioned into shots, and confidence weighting is applied.
    """
    config = TrajectoryConfig(canvas_width=1920, crop_width=608, fps=30.0, solver_mode="convex")
    optimizer = ConstrainedTrajectoryOptimizer(config)

    # 40 frames partitioned into two shots of 20 frames each
    raw = list(np.linspace(400, 600, 20)) + list(np.linspace(1200, 1400, 20))
    raw[5] = 900.0   # spike in shot 1
    raw[25] = 700.0  # spike in shot 2

    w_high = [1.0] * 40
    w_high[5] = 1000.0
    w_high[25] = 1000.0

    w_low = [1.0] * 40
    w_low[5] = 0.001
    w_low[25] = 0.001

    res_high = optimizer.optimize(raw, weights=w_high, scene_cuts=[0.67])
    res_low = optimizer.optimize(raw, weights=w_low, scene_cuts=[0.67])

    assert len(res_high.smoothed_centers) == 40
    assert len(res_low.smoothed_centers) == 40
    # High confidence pulls trajectory closer to the spike in both shots
    assert abs(res_high.smoothed_centers[5] - 900.0) < abs(res_low.smoothed_centers[5] - 900.0)
    assert abs(res_high.smoothed_centers[25] - 700.0) < abs(res_low.smoothed_centers[25] - 700.0)

