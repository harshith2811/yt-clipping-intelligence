"""
Comprehensive tests for VideoMetadataService and URL normalization.
Verifies bare IDs, URL variants, SSRF protections, ISO 8601 duration parsing,
API mocking, yt-dlp fallback, and cache mechanisms.
"""

import pytest
import json
from unittest.mock import patch, MagicMock
from yt_clipping.discovery.video_metadata import (
    normalize_youtube_url,
    parse_iso8601_duration,
    VideoMetadataService,
    EnrichedVideoInfo,
)


def test_url_normalization_valid_variants():
    test_cases = [
        # Bare ID
        ("nEaJMdM1djM", ("nEaJMdM1djM", "https://www.youtube.com/watch?v=nEaJMdM1djM")),
        # Standard watch URL
        ("https://www.youtube.com/watch?v=nEaJMdM1djM", ("nEaJMdM1djM", "https://www.youtube.com/watch?v=nEaJMdM1djM")),
        # Watch URL with tracking query params
        ("https://www.youtube.com/watch?v=nEaJMdM1djM&feature=share&t=42s", ("nEaJMdM1djM", "https://www.youtube.com/watch?v=nEaJMdM1djM")),
        # Short URL
        ("https://youtu.be/nEaJMdM1djM", ("nEaJMdM1djM", "https://www.youtube.com/watch?v=nEaJMdM1djM")),
        ("https://youtu.be/nEaJMdM1djM?si=abcd1234efgh5678", ("nEaJMdM1djM", "https://www.youtube.com/watch?v=nEaJMdM1djM")),
        # Shorts URL
        ("https://www.youtube.com/shorts/nEaJMdM1djM", ("nEaJMdM1djM", "https://www.youtube.com/watch?v=nEaJMdM1djM")),
        # Live URL
        ("https://youtube.com/live/nEaJMdM1djM", ("nEaJMdM1djM", "https://www.youtube.com/watch?v=nEaJMdM1djM")),
        # Embed URL
        ("https://www.youtube.com/embed/nEaJMdM1djM", ("nEaJMdM1djM", "https://www.youtube.com/watch?v=nEaJMdM1djM")),
        # Mobile subdomain
        ("https://m.youtube.com/watch?v=nEaJMdM1djM", ("nEaJMdM1djM", "https://www.youtube.com/watch?v=nEaJMdM1djM")),
    ]

    for input_url, expected in test_cases:
        vid, canonical = normalize_youtube_url(input_url)
        assert vid == expected[0]
        assert canonical == expected[1]


def test_url_normalization_ssrf_and_invalid_inputs():
    invalid_inputs = [
        "",
        "   ",
        "http://localhost:8000/watch?v=12345678901",
        "http://127.0.0.1/watch?v=12345678901",
        "http://169.254.169.254/latest/meta-data/",
        "https://evil-phishing-youtube.com/watch?v=12345678901",
        "https://vimeo.com/123456789",
        "https://www.youtube.com/watch?v=short",  # Not 11 chars
        "https://www.youtube.com/watch?v=toolongvideoidentifier12345",
        "https://www.youtube.com/about",
        "file:///etc/passwd",
        "ftp://www.youtube.com/watch?v=12345678901",
    ]

    for inv in invalid_inputs:
        with pytest.raises(ValueError):
            normalize_youtube_url(inv)


def test_parse_iso8601_duration():
    assert parse_iso8601_duration("PT45S") == 45.0
    assert parse_iso8601_duration("PT15M33S") == 933.0
    assert parse_iso8601_duration("PT1H2M10S") == 3730.0
    assert parse_iso8601_duration("P1DT2H3M4S") == 93784.0
    assert parse_iso8601_duration("") == 0.0
    assert parse_iso8601_duration("invalid") == 0.0


def test_metadata_service_cache(tmp_path):
    cache_dir = str(tmp_path / "metadata_cache")
    service = VideoMetadataService(cache_dir=cache_dir)

    cached_info = EnrichedVideoInfo(
        video_id="nEaJMdM1djM",
        title="Cached Title",
        description="Cached Desc",
        channel_title="Test Channel",
        canonical_url="https://www.youtube.com/watch?v=nEaJMdM1djM",
        metadata_provider="cache",
    )
    service._write_cache("nEaJMdM1djM", cached_info)

    res = service.get_metadata("nEaJMdM1djM", use_cache=True)
    assert res.title == "Cached Title"
    assert res.metadata_provider == "cache"


def test_metadata_service_youtube_api_mock(tmp_path):
    cache_dir = str(tmp_path / "metadata_cache")
    service = VideoMetadataService(api_key="mock_key", cache_dir=cache_dir)

    api_response = {
        "items": [
            {
                "snippet": {
                    "title": "API Video Title",
                    "description": "API Description",
                    "channelTitle": "API Channel",
                    "channelId": "UC1234567890",
                    "publishedAt": "2026-01-01T00:00:00Z",
                    "thumbnails": {"maxres": {"url": "https://i.ytimg.com/vi/nEaJMdM1djM/maxresdefault.jpg"}},
                    "categoryId": "27",
                    "tags": ["education", "tech"],
                },
                "contentDetails": {
                    "duration": "PT5M30S",
                },
                "statistics": {
                    "viewCount": "50000",
                    "likeCount": "2500",
                    "commentCount": "120",
                },
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(api_response).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        info = service.get_metadata("nEaJMdM1djM", use_cache=False)
        assert info.title == "API Video Title"
        assert info.view_count == 50000
        assert info.duration == 330.0
        assert info.metadata_provider == "youtube_data_api_v3"
        assert info.extraction_status == "success"


def test_metadata_service_ytdlp_fallback(tmp_path):
    cache_dir = str(tmp_path / "metadata_cache")
    # Service with empty API key forces fallback
    service = VideoMetadataService(api_key="", cache_dir=cache_dir)

    mock_ytdlp_dict = {
        "title": "yt-dlp Video Title",
        "description": "yt-dlp Description",
        "uploader": "yt-dlp Channel",
        "uploader_id": "UCOrg123",
        "channel_id": "UCOrg123",
        "view_count": 12000,
        "like_count": 800,
        "comment_count": 45,
        "upload_date": "20260201",
        "duration": 185.0,
        "categories": ["Science & Technology"],
        "tags": ["ai", "python"],
        "thumbnail": "https://thumb.jpg",
    }

    mock_ydl_instance = MagicMock()
    mock_ydl_instance.extract_info.return_value = mock_ytdlp_dict
    mock_ydl_instance.__enter__.return_value = mock_ydl_instance

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl_instance):
        info = service.get_metadata("nEaJMdM1djM", use_cache=False)
        assert info.title == "yt-dlp Video Title"
        assert info.metadata_provider == "yt_dlp"
        assert info.duration == 185.0
        assert info.view_count == 12000
