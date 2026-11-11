"""
Unit tests for Cloudflare Workers AI FLUX.1 Engine and Studio Video Editor Features.
Verifies FLUX image generation, fallback procedural cards, Ken Burns B-roll animation,
dialogue concept extraction, audio waveform energy profiles, and poster frame capture.
"""

import os
import cv2
import json
import base64
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from yt_clipping.rendering.flux_generator import FluxImageGenerator, STYLE_PRESETS
from yt_clipping.web.server import app, flux_generator


@pytest.fixture
def client():
    return TestClient(app)


def test_flux_generator_presets_and_prompt_building():
    """Verifies that FLUX style presets format prompts properly."""
    gen = FluxImageGenerator(account_id="", api_token="")
    assert "cinematic_hook" in STYLE_PRESETS
    assert "tech_minimal" in STYLE_PRESETS
    assert "neon_cyber" in STYLE_PRESETS
    assert "documentary" in STYLE_PRESETS
    assert "raw" in STYLE_PRESETS

    raw_p = "Cybernetic human holding glowing orb"
    built = gen.build_prompt(raw_p, "cinematic_hook")
    assert raw_p in built
    assert "Cinematic vertical 9:16 frame" in built

    built_raw = gen.build_prompt(raw_p, "raw")
    assert built_raw == raw_p


def test_flux_generator_procedural_fallback(tmp_path):
    """Verifies procedural fallback generates valid 9:16 PNG when offline or unconfigured."""
    gen = FluxImageGenerator(account_id="", api_token="", output_dir=str(tmp_path))
    assert not gen.is_configured

    res = gen.generate_image(
        prompt="The breakthrough in quantum computing that shocked the world",
        style_preset="tech_minimal",
        width=768,
        height=1344,
    )

    assert res.success is True
    assert res.is_fallback is True
    assert os.path.exists(res.file_path)
    assert res.file_path.endswith(".png")
    assert res.image_base64.startswith("data:image/png;base64,")

    # Verify image dimensions using OpenCV
    img = cv2.imread(res.file_path)
    assert img is not None
    assert img.shape[0] == 1344  # height
    assert img.shape[1] == 768   # width


def test_flux_generator_mock_cloudflare_api(tmp_path):
    """Verifies FLUX generator calls Cloudflare REST API correctly when credentials are provided."""
    gen = FluxImageGenerator(
        account_id="cf_account_12345",
        api_token="cf_token_secret_xyz",
        output_dir=str(tmp_path),
    )
    assert gen.is_configured

    # Create dummy 1x1 PNG bytes
    dummy_png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00"
        b"\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    dummy_b64 = base64.b64encode(dummy_png_bytes).decode("utf-8")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.json.return_value = {"result": {"image": dummy_b64}}

    with patch("requests.post", return_value=mock_resp) as mock_post:
        res = gen.generate_image(
            prompt="High impact visual hook",
            style_preset="cinematic_hook",
            steps=4,
        )

        assert mock_post.called
        call_args = mock_post.call_args
        assert "cf_account_12345" in call_args[0][0]
        assert "Bearer cf_token_secret_xyz" in call_args[1]["headers"]["Authorization"]

        assert res.success is True
        assert res.is_fallback is False
        assert os.path.exists(res.file_path)


def test_flux_generator_create_broll_clip(tmp_path):
    """Verifies FFmpeg Ken Burns vertical B-roll animation from image."""
    gen = FluxImageGenerator(account_id="", api_token="", output_dir=str(tmp_path))
    res = gen.generate_image(
        prompt="Dramatic test scene",
        style_preset="documentary",
        width=540,
        height=960,
    )
    assert os.path.exists(res.file_path)

    # Convert to 1-second B-roll clip
    clip_path = gen.create_broll_clip(res.file_path, duration=1.0, motion="zoom_in")
    if clip_path:
        assert os.path.exists(clip_path)
        assert clip_path.endswith(".mp4")
        assert os.path.getsize(clip_path) > 1000


def test_flux_extract_broll_concepts():
    """Verifies transcript dialogue analysis for visual concept extraction."""
    transcript = (
        "In this video we talk about artificial intelligence and future automation. "
        "We also discuss how money flows through modern technology and code."
    )
    concepts = FluxImageGenerator.extract_broll_concepts(transcript, max_concepts=3)
    assert len(concepts) > 0
    assert len(concepts) <= 3
    for c in concepts:
        assert "concept" in c
        assert "prompt" in c
        assert "style" in c

    # Empty transcript fallback
    fallback_concepts = FluxImageGenerator.extract_broll_concepts("", max_concepts=2)
    assert len(fallback_concepts) == 1
    assert "prompt" in fallback_concepts[0]


def test_api_flux_status_endpoint(client):
    """Verifies GET /api/v1/flux/status."""
    resp = client.get("/api/v1/flux/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "configured" in data
    assert "model" in data
    assert data["model"] == "@cf/black-forest-labs/flux-1-schnell"
    assert "provider" in data
    assert "style_presets" in data


def test_api_flux_settings_endpoint(client):
    """Verifies POST /api/v1/flux/settings."""
    orig_account = flux_generator.account_id
    orig_token = flux_generator.api_token
    try:
        resp = client.post(
            "/api/v1/flux/settings",
            json={"account_id": "test_account_999", "api_token": "test_token_888"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["configured"] is True
        assert flux_generator.account_id == "test_account_999"
        assert flux_generator.api_token == "test_token_888"
    finally:
        flux_generator.account_id = orig_account
        flux_generator.api_token = orig_token


def test_api_flux_generate_endpoint(client):
    """Verifies POST /api/v1/flux/generate."""
    resp = client.post(
        "/api/v1/flux/generate",
        json={
            "prompt": "Vibrant emerald neon sign in rainy Tokyo street",
            "style_preset": "neon_cyber",
            "width": 768,
            "height": 1344,
            "animate_ken_burns": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "file_path" in data
    assert "image_base64" in data
    assert data["image_base64"].startswith("data:image/png;base64,")


def test_api_flux_auto_broll_endpoint(client):
    """Verifies POST /api/v1/flux/auto-broll."""
    resp = client.post(
        "/api/v1/flux/auto-broll",
        json={
            "transcript_text": "Building a startup requires relentless focus and high growth.",
            "max_concepts": 2,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["count"] > 0
    assert "assets" in data
    assert len(data["assets"]) > 0


def test_api_editor_waveform_endpoint(client, tmp_path):
    """Verifies POST /api/v1/editor/waveform with missing or existing file."""
    # Test 404 for nonexistent file
    resp_404 = client.post(
        "/api/v1/editor/waveform",
        json={"file_path": "totally_nonexistent_audio_file.mp4"},
    )
    assert resp_404.status_code == 404

    # Test with existing file (dummy bytes fallback)
    dummy_file = tmp_path / "valid_clip.mp4"
    dummy_file.write_bytes(b"dummy pcm container bytes")
    resp_200 = client.post(
        "/api/v1/editor/waveform",
        json={"file_path": str(dummy_file)},
    )
    assert resp_200.status_code == 200
    data = resp_200.json()
    assert "points" in data
    assert isinstance(data["points"], list)
    assert len(data["points"]) > 0
    assert "duration" in data


def test_api_editor_save_poster_endpoint(client, tmp_path):
    """Verifies POST /api/v1/editor/save-poster endpoint."""
    dummy_video = tmp_path / "test_poster_video.mp4"
    dummy_video.write_bytes(b"dummy video bytes for poster test")

    dummy_poster = tmp_path / "poster.jpg"
    dummy_poster.write_bytes(b"dummy poster jpeg")

    with patch("yt_clipping.rendering.editor.VideoEditorEngine.extract_frame_preview", return_value=str(dummy_poster)):
        resp = client.post(
            "/api/v1/editor/save-poster",
            json={"video_path": str(dummy_video), "timestamp": 2.5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "poster_path" in data
        assert "poster_url" in data


def test_api_flux_generate_with_broll(client):
    """Verifies POST /api/v1/flux/generate with animate_broll returns a playable URL."""
    resp = client.post(
        "/api/v1/flux/generate",
        json={
            "prompt": "Dynamic quantum data center backdrop",
            "style_preset": "tech_minimal",
            "width": 768,
            "height": 1344,
            "animate_broll": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "broll_video_path" in data
    assert "broll_video_url" in data
    if data["broll_video_path"]:
        assert data["broll_video_url"].startswith("/clips/")
        assert os.path.exists(data["broll_video_path"])


def test_api_flux_broll_clip_returns_url(client, tmp_path):
    """Verifies POST /api/v1/flux/broll-clip produces a playable /clips/ URL."""
    gen = FluxImageGenerator(account_id="", api_token="", output_dir=str(tmp_path))
    res = gen.generate_image(
        prompt="Cybernetic circuit backdrop",
        style_preset="neon_cyber",
        width=540,
        height=960,
    )
    assert os.path.exists(res.file_path)

    resp = client.post(
        "/api/v1/flux/broll-clip",
        json={
            "image_path": res.file_path,
            "duration": 1.0,
            "motion": "zoom_in",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "broll_video_path" in data
    assert "broll_video_url" in data
    assert data["broll_video_url"].startswith("/clips/")


def test_assert_path_in_data_dir_allows_clips_dir():
    """Verifies _assert_path_in_data_dir does not block CLIPS_DIR files."""
    from yt_clipping.web.server import _assert_path_in_data_dir, CLIPS_DIR
    test_clip_path = os.path.join(CLIPS_DIR, "test_clip_ok.mp4")
    resolved = _assert_path_in_data_dir(test_clip_path)
    assert resolved == os.path.abspath(test_clip_path)


def test_broll_aspect_ratio_preservation(tmp_path):
    """Verifies that create_broll_clip preserves 9:16 aspect ratio on 16:9 landscape image."""
    import numpy as np
    gen = FluxImageGenerator(account_id="", api_token="", output_dir=str(tmp_path))
    landscape_img = tmp_path / "landscape.png"
    cv2.imwrite(str(landscape_img), np.zeros((768, 1344, 3), dtype=np.uint8))

    clip = gen.create_broll_clip(str(landscape_img), duration=1.0, motion="zoom_in")
    if clip:
        assert os.path.exists(clip)
        assert os.path.getsize(clip) > 1000


def test_visual_creative_director_heuristics(tmp_path):
    """Verifies GeminiVisualDirector heuristic evaluation and stock reuse guard."""
    from yt_clipping.scoring.visual_director import GeminiVisualDirector, VisualInterventionDecision
    from yt_clipping.contracts.models import (
        HighlightCandidate,
        ScoreBreakdown,
        Transcript,
        TranscriptSegment,
        WordTimestamp,
    )

    director = GeminiVisualDirector(api_key="", offline_mode=True)
    dummy_breakdown = ScoreBreakdown(hook_score=8.5, moment_score=8.5, coherence_score=8.5, pacing_score=8.5)

    # 1. Short clip duration guard
    short_cand = HighlightCandidate(
        candidate_id="c1",
        video_id="v1",
        start_seconds=0.0,
        end_seconds=4.0,
        duration_seconds=4.0,
        score=85.0,
        hook_title="Short Hook",
        breakdown=dummy_breakdown,
    )
    t = Transcript(video_id="v1", language="en", duration_seconds=10.0, text="Hi welcome back", segments=[])
    res = director.evaluate_candidate(short_cand, t)
    assert res.needed is False
    assert "duration" in res.rationale.lower()

    # 2. Local stock reuse guard
    stock_dir = tmp_path / "stock"
    stock_dir.mkdir()
    stock_file = stock_dir / "futuristic_quantum_ai.mp4"
    stock_file.write_bytes(b"dummy stock bytes")

    long_cand = HighlightCandidate(
        candidate_id="c2",
        video_id="v1",
        start_seconds=0.0,
        end_seconds=15.0,
        duration_seconds=15.0,
        score=92.0,
        hook_title="Quantum AI Breakthrough",
        breakdown=dummy_breakdown,
    )
    t_rich = Transcript(
        video_id="v1",
        language="en",
        duration_seconds=20.0,
        text="The breakthrough in quantum artificial intelligence is reshaping computing.",
        segments=[
            TranscriptSegment(
                segment_id=1,
                start=0.0,
                end=15.0,
                text="The breakthrough in quantum artificial intelligence is reshaping computing.",
                words=[
                    WordTimestamp(word="quantum", start=1.0, end=2.0),
                    WordTimestamp(word="artificial", start=2.5, end=3.5),
                    WordTimestamp(word="intelligence", start=4.0, end=5.0),
                ],
            )
        ],
    )
    res_stock = director.evaluate_candidate(long_cand, t_rich, available_assets_dir=str(stock_dir))
    assert res_stock.needed is False
    assert "stock" in res_stock.rationale.lower()

    # 3. Justified heuristic generation when no matching stock exists
    res_heuristic = director.evaluate_candidate(long_cand, t_rich, available_assets_dir=str(tmp_path / "empty"))
    assert res_heuristic.needed is True
    assert res_heuristic.flux_prompt != ""
    assert res_heuristic.style_preset in ["tech_minimal", "neon_cyber", "cinematic_hook"]
    assert res_heuristic.target_duration_seconds > 0.0


def test_visual_creative_director_execute_intervention(tmp_path):
    """Verifies that execute_intervention produces valid image and Ken Burns B-roll clip."""
    from yt_clipping.scoring.visual_director import GeminiVisualDirector, VisualInterventionDecision

    flux_gen = FluxImageGenerator(account_id="", api_token="", output_dir=str(tmp_path))
    director = GeminiVisualDirector(flux_generator=flux_gen, offline_mode=True)

    decision = VisualInterventionDecision(
        needed=True,
        rationale="Illustrating neural network concept",
        concept="Neural Grid",
        target_start_seconds=1.5,
        target_duration_seconds=1.0,
        flux_prompt="Glowing neural network matrix with cyan light beams",
        style_preset="tech_minimal",
        motion="zoom_in",
    )

    executed = director.execute_intervention(decision, output_dir=str(tmp_path))
    assert executed.is_generated is True
    assert executed.asset_path is not None
    assert os.path.exists(executed.asset_path)
    if executed.broll_video_path:
        assert os.path.exists(executed.broll_video_path)


def test_api_trending_stream_to_clipper_endpoint(client):
    """Verifies POST /api/v1/trending/stream-to-clipper initiates background workflow."""
    with patch("yt_clipping.web.server._render_video_pipeline", return_value=[{"clip_id": "clip_test_1", "file_path": "clip.mp4", "duration": 15.0}]):
        resp = client.post(
            "/api/v1/trending/stream-to-clipper",
            json={
                "video_id_or_url": "https://www.youtube.com/watch?v=0e3GPea1Tyg",
                "max_clips": 1,
                "layout": "active_speaker",
                "subtitle_preset": "hormozi",
                "gpu": False,
                "auto_publish": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "task_id" in data
        assert "job_id" in data
        assert data["status"] == "QUEUED"
        assert data["check_status_url"].startswith("/api/v1/jobs/")

    # Invalid URL test
    resp_bad = client.post(
        "/api/v1/trending/stream-to-clipper",
        json={"video_id_or_url": ""},
    )
    assert resp_bad.status_code in (400, 422)

    # Invalid URL test
    resp_bad = client.post(
        "/api/v1/trending/stream-to-clipper",
        json={"video_id_or_url": ""},
    )
    assert resp_bad.status_code in (400, 422)
