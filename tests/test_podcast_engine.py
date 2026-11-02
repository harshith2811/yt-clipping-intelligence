"""
Tests for the dedicated Podcast Shorts Engine.
Verifies config defaults, filtergraph builders, shot detection,
subtitle positioning, and pipeline orchestration.
"""

import os
import pytest
import numpy as np

from src.yt_clipping.podcast.config import PodcastLayoutConfig
from src.yt_clipping.podcast.shot_detector import (
    PodcastShotDetector, PodcastShot, PodcastShotType
)
from src.yt_clipping.podcast.layout import (
    build_podcast_split_filtergraph,
    build_podcast_closeup_filtergraph,
    escape_libass_path,
)
from src.yt_clipping.podcast.captions import PodcastSubtitleGenerator
from src.yt_clipping.podcast.pipeline import PodcastShortMaker, get_ffmpeg_path


def test_podcast_layout_config_defaults():
    config = PodcastLayoutConfig()
    assert config.width == 1080
    assert config.height == 1920
    assert config.margin_v == 960
    assert config.split_mode == "hybrid"
    assert config.host_side == "left"


def test_podcast_layout_config_preview_scaling():
    config = PodcastLayoutConfig(preview=True)
    assert config.width == 540
    assert config.height == 960
    assert config.margin_v == 480
    assert config.font_size == 38
    # Must be even integers for H.264
    assert config.width % 2 == 0
    assert config.height % 2 == 0


def test_escape_libass_path_windows():
    raw_path = r"C:\data\assets\subtitles.ass"
    escaped = escape_libass_path(raw_path)
    assert escaped == "C\\:/data/assets/subtitles.ass"
    # No backslash path separators
    assert "/data/assets/subtitles.ass" in escaped


def test_build_podcast_split_filtergraph():
    config = PodcastLayoutConfig(width=540, height=960)
    fg = build_podcast_split_filtergraph(
        src_w=854,
        src_h=480,
        config=config,
        host_cx=230,
        guest_cx=630,
        subtitle_ass_path=None
    )
    assert "[0:v]split=2[in_top][in_bot]" in fg
    assert "scale=540:480[top]" in fg
    assert "scale=540:480[bot]" in fg
    assert "[top][bot]vstack=inputs=2[stacked]" in fg
    assert "setsar=1" in fg


def test_build_podcast_closeup_filtergraph():
    config = PodcastLayoutConfig(width=540, height=960)
    vf = build_podcast_closeup_filtergraph(
        src_w=854,
        src_h=480,
        config=config,
        speaker_cx=540,
        subtitle_ass_path=None
    )
    assert "scale=540:960" in vf
    assert "setsar=1" in vf
    assert "crop=" in vf


def test_podcast_shot_detector_classification():
    detector = PodcastShotDetector(use_yolo=False)
    # Synthetic frame test
    blank_frame = np.zeros((480, 854, 3), dtype=np.uint8)
    shot_type, sp_cx, h_cx, g_cx = detector._classify_frame(blank_frame, 854, 480)
    assert shot_type in (PodcastShotType.DUAL_WIDE, PodcastShotType.SINGLE_CLOSEUP, PodcastShotType.PANORAMIC)


def test_podcast_subtitle_generator(tmp_path):
    config = PodcastLayoutConfig(width=1080, height=1920)
    sub_gen = PodcastSubtitleGenerator(config)
    assert sub_gen.base_generator.margin_v == 960

    words = [("HELLO", 0.0, 0.5), ("WORLD", 0.5, 1.0)]
    out_file = str(tmp_path / "test_sub.ass")
    res_path = sub_gen.generate_from_words(words, 0.0, 1.0, out_file)
    assert os.path.exists(res_path)

    with open(res_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "MarginV" in content
    assert "960" in content
    assert "WORLD" in content


def test_get_ffmpeg_path():
    path = get_ffmpeg_path()
    assert path is not None
    assert len(path) > 0


@pytest.mark.skipif(not os.path.exists("data/assets/tpQZLCel_kg_slice.mp4"), reason="Test slice asset missing")
def test_podcast_short_maker_integration(tmp_path):
    config = PodcastLayoutConfig(preview=True, burn_subtitles=False)
    maker = PodcastShortMaker(config=config)

    out_mp4 = str(tmp_path / "podcast_integration.mp4")
    res = maker.create_short(
        video_path="data/assets/tpQZLCel_kg_slice.mp4",
        start_sec=0.0,
        duration_sec=3.0,
        output_path=out_mp4,
    )
    assert os.path.exists(out_mp4)
    assert res["file_size_bytes"] > 0
    assert res["resolution"] == "540x960"
    assert res["shots_detected"] >= 1


def test_podcast_split_filtergraph_with_micro_jump_cuts():
    config = PodcastLayoutConfig(width=540, height=960, apply_micro_jump_cuts=True)
    select_expr = "between(t,0.000,1.500)+between(t,2.000,3.000)"
    fg = build_podcast_split_filtergraph(
        src_w=854,
        src_h=480,
        config=config,
        host_cx=230,
        guest_cx=630,
        subtitle_ass_path=None,
        select_filter_expr=select_expr,
    )
    assert f"select='{select_expr}'" in fg
    assert "setpts=N/FRAME_RATE/TB" in fg
    assert "[stacked]setsar=1" in fg

