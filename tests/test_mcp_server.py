"""
Unit and Integration Tests for Native Model Context Protocol (MCP) Server.
Validates JSON-RPC 2.0 protocol conformance, stdio framing, tool executions,
stdio stream isolation, and CLI subcommands.
"""

import io
import os
import sys
import json
import sqlite3
import tempfile
import subprocess
import pytest

from yt_clipping.mcp.server import MCPServer
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


@pytest.fixture
def temp_workspace(tmp_path):
    """Sets up an isolated workspace for MCP server tests."""
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

    # Initialize empty ledger
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


def _create_server(ws, in_str=""):
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


# 1. Protocol: Initialize
def test_mcp_initialize(temp_workspace):
    server, _, _, _ = _create_server(temp_workspace)
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        },
    }
    resp_raw = server.handle_message(json.dumps(req))
    resp = json.loads(resp_raw)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert resp["result"]["protocolVersion"] == "2024-11-05"
    assert "tools" in resp["result"]["capabilities"]
    assert resp["result"]["serverInfo"]["name"] == "yt-clipping-intelligence"


# 2. Protocol: Initialized Notification
def test_mcp_initialized_notification(temp_workspace):
    server, _, _, _ = _create_server(temp_workspace)
    assert not server.is_initialized
    notif = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    }
    resp_raw = server.handle_message(json.dumps(notif))
    assert resp_raw is None
    assert server.is_initialized is True


# 3. Protocol: Ping
def test_mcp_ping(temp_workspace):
    server, _, _, _ = _create_server(temp_workspace)
    req = {
        "jsonrpc": "2.0",
        "id": 42,
        "method": "ping",
    }
    resp_raw = server.handle_message(json.dumps(req))
    resp = json.loads(resp_raw)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 42
    assert resp["result"] == {}


# 4. Error Handling: Unknown Method
def test_mcp_unknown_method(temp_workspace):
    server, _, _, _ = _create_server(temp_workspace)
    req = {
        "jsonrpc": "2.0",
        "id": 99,
        "method": "non_existent/method",
    }
    resp_raw = server.handle_message(json.dumps(req))
    resp = json.loads(resp_raw)
    assert resp["id"] == 99
    assert resp["error"]["code"] == -32601
    assert "Method not found" in resp["error"]["message"]


# 5. Error Handling: Malformed JSON
def test_mcp_malformed_json(temp_workspace):
    server, _, _, _ = _create_server(temp_workspace)
    resp_raw = server.handle_message("this is definitely not valid json")
    resp = json.loads(resp_raw)
    assert resp["id"] is None
    assert resp["error"]["code"] == -32700
    assert "Parse error" in resp["error"]["message"]


# 6. Discovery: Tools List
def test_mcp_tools_list(temp_workspace):
    server, _, _, _ = _create_server(temp_workspace)
    req = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/list",
    }
    resp_raw = server.handle_message(json.dumps(req))
    resp = json.loads(resp_raw)
    tools = resp["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    expected_tools = [
        "discover_channel_uploads",
        "verify_source_rights",
        "analyze_replay_heatmap",
        "evaluate_highlight_candidates",
        "render_vertical_clip",
        "inspect_job_status",
    ]
    assert len(tools) == 6
    for et in expected_tools:
        assert et in tool_names


# 7. Tool: discover_channel_uploads
def test_tool_discover_channel_uploads(temp_workspace):
    server, _, _, _ = _create_server(temp_workspace)
    req = {
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {
            "name": "discover_channel_uploads",
            "arguments": {
                "channel_id": "UC_sample_channel",
                "max_videos": 5,
            },
        },
    }
    resp_raw = server.handle_message(json.dumps(req))
    resp = json.loads(resp_raw)
    assert resp["id"] == 11
    assert resp["result"]["isError"] is False
    content = json.loads(resp["result"]["content"][0]["text"])
    assert content["status"] == "success"
    assert content["channel_id"] == "UC_sample_channel"
    assert "videos" in content


# 8. Tool: verify_source_rights
def test_tool_verify_source_rights(temp_workspace):
    policy = LocalRightsPolicy(temp_workspace["ledger_path"], db_path=temp_workspace["db_path"])
    manifest = RightsManifest(
        rights_id="rights-test-vid-1",
        video_id="test_vid_123",
        basis=RightsBasis.OPERATOR_ASSET,
        status=RightsStatus.VERIFIED,
        owner_name="Test Creator",
        audit_notes="Verified via test",
    )
    policy.register_rights(manifest)

    server, _, _, _ = _create_server(temp_workspace)
    req = {
        "jsonrpc": "2.0",
        "id": 12,
        "method": "tools/call",
        "params": {
            "name": "verify_source_rights",
            "arguments": {
                "video_id": "test_vid_123",
                "policy_type": "creator",
            },
        },
    }
    resp_raw = server.handle_message(json.dumps(req))
    resp = json.loads(resp_raw)
    assert resp["result"]["isError"] is False
    content = json.loads(resp["result"]["content"][0]["text"])
    assert content["status"] == "success"
    assert content["video_id"] == "test_vid_123"
    assert content["can_process"] is True
    assert content["rights_status"] == "VERIFIED"


# 9. Tool: analyze_replay_heatmap
def test_tool_analyze_replay_heatmap(temp_workspace):
    server, _, _, _ = _create_server(temp_workspace)
    req = {
        "jsonrpc": "2.0",
        "id": 13,
        "method": "tools/call",
        "params": {
            "name": "analyze_replay_heatmap",
            "arguments": {
                "video_id": "sample_video_hm",
            },
        },
    }
    resp_raw = server.handle_message(json.dumps(req))
    resp = json.loads(resp_raw)
    assert resp["result"]["isError"] is False
    content = json.loads(resp["result"]["content"][0]["text"])
    assert content["status"] == "success"
    assert content["video_id"] == "sample_video_hm"
    assert content["total_points"] >= 50
    assert "peaks" in content


# 10. Tool: evaluate_highlight_candidates (heuristic)
def test_tool_evaluate_highlight_candidates_heuristic(temp_workspace):
    # Seed a transcript
    vid_id = "test_eval_heur"
    words = [
        WordTimestamp("Hello", 0.0, 0.4),
        WordTimestamp("world", 0.5, 0.9),
        WordTimestamp("welcome", 1.0, 1.4),
        WordTimestamp("to", 1.5, 1.7),
        WordTimestamp("dopamine", 1.8, 2.3),
        WordTimestamp("neuroscience", 2.4, 3.0),
        WordTimestamp("secrets", 3.1, 3.8),
    ]
    # Add filler to reach 20 seconds
    for sec in range(4, 25):
        words.append(WordTimestamp("learning", float(sec), float(sec) + 0.8))

    seg = TranscriptSegment(
        segment_id=1,
        start=0.0,
        end=24.8,
        text="Hello world welcome to dopamine neuroscience secrets " + " ".join(["learning"] * 21),
        words=words,
    )
    transcript = Transcript(
        video_id=vid_id,
        language="en",
        duration_seconds=25.0,
        text=seg.text,
        segments=[seg],
    )
    t_file = os.path.join(temp_workspace["transcripts_dir"], f"{vid_id}.transcript.json")
    with open(t_file, "w", encoding="utf-8") as f:
        json.dump(transcript.to_dict(), f)

    server, stdin, stdout, stderr = _create_server(temp_workspace)
    req = {
        "jsonrpc": "2.0",
        "id": 14,
        "method": "tools/call",
        "params": {
            "name": "evaluate_highlight_candidates",
            "arguments": {
                "video_id": vid_id,
                "engine": "heuristic",
            },
        },
    }
    resp_raw = server.handle_message(json.dumps(req))
    resp = json.loads(resp_raw)
    assert resp["result"]["isError"] is False
    content = json.loads(resp["result"]["content"][0]["text"])
    assert content["status"] == "success"
    assert content["engine_used"] == "heuristic"
    assert content["candidate_count"] >= 1
    assert "breakdown" in content["candidates"][0]


# 11. Tool: evaluate_highlight_candidates (gemini fallback)
def test_tool_evaluate_highlight_candidates_gemini(temp_workspace):
    vid_id = "test_eval_gemini"
    words = [WordTimestamp("Test", 0.0, 1.0), WordTimestamp("gemini", 1.0, 2.0)]
    for sec in range(2, 22):
        words.append(WordTimestamp("word", float(sec), float(sec) + 0.8))
    seg = TranscriptSegment(segment_id=1, start=0.0, end=21.8, text="Test gemini " + " ".join(["word"] * 20), words=words)
    transcript = Transcript(video_id=vid_id, language="en", duration_seconds=22.0, text=seg.text, segments=[seg])
    t_file = os.path.join(temp_workspace["transcripts_dir"], f"{vid_id}.transcript.json")
    with open(t_file, "w", encoding="utf-8") as f:
        json.dump(transcript.to_dict(), f)

    server, _, _, _ = _create_server(temp_workspace)
    req = {
        "jsonrpc": "2.0",
        "id": 15,
        "method": "tools/call",
        "params": {
            "name": "evaluate_highlight_candidates",
            "arguments": {
                "video_id": vid_id,
                "engine": "gemini",
            },
        },
    }
    resp_raw = server.handle_message(json.dumps(req))
    resp = json.loads(resp_raw)
    assert resp["result"]["isError"] is False
    content = json.loads(resp["result"]["content"][0]["text"])
    assert content["status"] == "success"
    assert content["candidate_count"] >= 1


# 12. Tool: render_vertical_clip
def test_tool_render_vertical_clip(temp_workspace):
    vid_id = "test_render_clip"
    source_mp4 = os.path.join(temp_workspace["assets_dir"], f"{vid_id}.mp4")

    # Generate small 3-second test video using lavfi
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=10",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
        "-t", "3", "-c:v", "libx264", "-c:a", "aac", source_mp4
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    server, _, _, _ = _create_server(temp_workspace)
    req = {
        "jsonrpc": "2.0",
        "id": 16,
        "method": "tools/call",
        "params": {
            "name": "render_vertical_clip",
            "arguments": {
                "video_id": vid_id,
                "start_sec": 0.0,
                "end_sec": 2.0,
                "layout": "crop_center",
                "preset": "classic",
            },
        },
    }
    resp_raw = server.handle_message(json.dumps(req))
    resp = json.loads(resp_raw)
    assert resp["result"]["isError"] is False
    content = json.loads(resp["result"]["content"][0]["text"])
    assert content["status"] == "success"
    assert content["video_id"] == vid_id
    assert os.path.exists(content["output_file"])
    assert content["duration_seconds"] == 2.0


# 13. Tool: inspect_job_status
def test_tool_inspect_job_status(temp_workspace):
    journal = JobJournal(temp_workspace["db_path"])
    job = ClipJob(
        job_id="job-mcp-test-1",
        video_id="video-mcp-1",
        current_stage=JobStage.SCORED,
        status=JobStatus.IN_PROGRESS,
    )
    journal.save_job(job)

    server, _, _, _ = _create_server(temp_workspace)
    req = {
        "jsonrpc": "2.0",
        "id": 17,
        "method": "tools/call",
        "params": {
            "name": "inspect_job_status",
            "arguments": {
                "job_id": "job-mcp-test-1",
            },
        },
    }
    resp_raw = server.handle_message(json.dumps(req))
    resp = json.loads(resp_raw)
    assert resp["result"]["isError"] is False
    content = json.loads(resp["result"]["content"][0]["text"])
    assert content["status"] == "success"
    assert content["job_id"] == "job-mcp-test-1"
    assert content["current_stage"] == "SCORED"
    assert content["status_value"] == "IN_PROGRESS"


# 14. Error Handling: Unknown Tool Name
def test_tool_call_invalid_tool(temp_workspace):
    server, _, _, _ = _create_server(temp_workspace)
    req = {
        "jsonrpc": "2.0",
        "id": 18,
        "method": "tools/call",
        "params": {
            "name": "magic_non_existent_tool",
            "arguments": {},
        },
    }
    resp_raw = server.handle_message(json.dumps(req))
    resp = json.loads(resp_raw)
    assert resp["result"]["isError"] is True
    assert "Unknown tool" in resp["result"]["content"][0]["text"]


# 15. Error Handling: Missing Required Args
def test_tool_call_missing_required_args(temp_workspace):
    server, _, _, _ = _create_server(temp_workspace)
    req = {
        "jsonrpc": "2.0",
        "id": 19,
        "method": "tools/call",
        "params": {
            "name": "render_vertical_clip",
            "arguments": {
                "video_id": "some_vid",
                # missing start_sec and end_sec
            },
        },
    }
    resp_raw = server.handle_message(json.dumps(req))
    resp = json.loads(resp_raw)
    assert resp["result"]["isError"] is True
    assert "Missing required argument" in resp["result"]["content"][0]["text"]


# 16. Concurrency & Stdio Isolation: No stdout leaks
def test_stdio_isolation_no_stdout_leaks(temp_workspace):
    lines_in = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}),
    ]
    input_text = "\n".join(lines_in) + "\n"
    server, stdin, stdout, stderr = _create_server(temp_workspace, in_str=input_text)

    server.run_stdio()

    stdout_val = stdout.getvalue()
    lines_out = [ln.strip() for ln in stdout_val.splitlines() if ln.strip()]

    # Every single line in stdout MUST be valid JSON
    assert len(lines_out) == 2  # initialize + ping (notification produces 0)
    for line in lines_out:
        parsed = json.loads(line)
        assert isinstance(parsed, dict)
        assert parsed.get("jsonrpc") == "2.0"


# 17. CLI Subcommand Invocation
def test_mcp_cli_invocation():
    result = subprocess.run(
        [sys.executable, "-m", "yt_clipping.cli.master_cli", "mcp-server", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Model Context Protocol (MCP) JSON-RPC 2.0 stdio server" in result.stdout


# 18. Error Handling: Missing or Non-String Method
def test_mcp_missing_method_invalid_request(temp_workspace):
    server, _, _, _ = _create_server(temp_workspace)
    # Missing method
    req1 = {"jsonrpc": "2.0", "id": 1}
    resp1_raw = server.handle_message(json.dumps(req1))
    resp1 = json.loads(resp1_raw)
    assert resp1["jsonrpc"] == "2.0"
    assert resp1["id"] == 1
    assert resp1["error"]["code"] == -32600
    assert "Invalid Request" in resp1["error"]["message"]

    # Non-string method
    req2 = {"jsonrpc": "2.0", "id": 2, "method": 12345}
    resp2_raw = server.handle_message(json.dumps(req2))
    resp2 = json.loads(resp2_raw)
    assert resp2["jsonrpc"] == "2.0"
    assert resp2["id"] == 2
    assert resp2["error"]["code"] == -32600
    assert "Invalid Request" in resp2["error"]["message"]


# 19. Defenses: Null and Non-Dict Params in handle_message and tools/call
def test_mcp_null_or_invalid_params_defense(temp_workspace):
    server, _, _, _ = _create_server(temp_workspace)
    # Null params in tools/call
    req1 = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": None}
    resp1_raw = server.handle_message(json.dumps(req1))
    assert resp1_raw is not None
    resp1 = json.loads(resp1_raw)
    assert resp1["jsonrpc"] == "2.0"
    assert resp1["id"] == 1
    assert resp1["error"]["code"] == -32602
    assert "Invalid params: Missing tool 'name'" in resp1["error"]["message"]

    # Non-dict params in tools/call
    req2 = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": "not-a-dict"}
    resp2_raw = server.handle_message(json.dumps(req2))
    assert resp2_raw is not None
    resp2 = json.loads(resp2_raw)
    assert resp2["jsonrpc"] == "2.0"
    assert resp2["id"] == 2
    assert resp2["error"]["code"] == -32602

    # Null params in initialize
    req3 = {"jsonrpc": "2.0", "id": 3, "method": "initialize", "params": None}
    resp3_raw = server.handle_message(json.dumps(req3))
    assert resp3_raw is not None
    resp3 = json.loads(resp3_raw)
    assert resp3["jsonrpc"] == "2.0"
    assert resp3["id"] == 3
    assert "protocolVersion" in resp3["result"]

    # Non-dict arguments in tools/call
    req4 = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "verify_source_rights",
            "arguments": "not-a-dict",
        },
    }
    resp4_raw = server.handle_message(json.dumps(req4))
    assert resp4_raw is not None
    resp4 = json.loads(resp4_raw)
    assert resp4["result"]["isError"] is True
    assert "Missing required argument" in resp4["result"]["content"][0]["text"]

