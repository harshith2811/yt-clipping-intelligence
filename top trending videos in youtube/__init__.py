"""
Top Trending Videos in YouTube (Channels > 10M Subscribers) Package.
Provides verified channel registries, trending video fetcher,
and streaming integrations to feed high-retention content into the YouTube Clipper.
"""

from .channels import (
    VERIFIED_10M_CHANNELS,
    MIN_SUBSCRIBER_THRESHOLD,
    ChannelInfo,
    verify_channels_batch,
    get_channel_by_id,
)
from .fetcher import (
    TopTrending10MFetcher,
    QualityTrendingVideo,
)
from .streamer import (
    ClipperStreamer,
)

__all__ = [
    "VERIFIED_10M_CHANNELS",
    "MIN_SUBSCRIBER_THRESHOLD",
    "ChannelInfo",
    "TopTrending10MFetcher",
    "QualityTrendingVideo",
    "ClipperStreamer",
    "verify_channels_batch",
    "get_channel_by_id",
]
