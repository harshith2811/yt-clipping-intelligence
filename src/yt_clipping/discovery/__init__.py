"""Channel discovery, trend monitoring, and public metric ranking."""
from .monitor import ChannelMonitor, APIQuotaBudget, RSSFeedClient
from .ranker import PublicMetricRanker
from .heatmap import HeatmapAnalyzer
from .trend_analyzer import TrendAnalyzer
from .outlier import (
    OutlierMultiplier,
    OutlierReport,
    OutlierClassification,
)
from .attribution_engine import (
    AttributionEngine,
    CreatorPolicy,
    AttributionPackage,
)
from .channel_registry import ChannelRegistry
from .channel_watcher import ChannelWatcher
from .daemon import DiscoveryDaemon
from .pinger_daemon import PingerDaemon
from .quota_governor import APIQuotaGovernor, QuotaExceededError
from .trend_scorer import (
    TrendScorer,
    ViralityClassification,
    VelocityTelemetry,
)

__all__ = [
    "ChannelMonitor",
    "APIQuotaBudget",
    "RSSFeedClient",
    "PublicMetricRanker",
    "HeatmapAnalyzer",
    "TrendAnalyzer",
    "OutlierMultiplier",
    "OutlierReport",
    "OutlierClassification",
    "AttributionEngine",
    "CreatorPolicy",
    "AttributionPackage",
    "ChannelRegistry",
    "ChannelWatcher",
    "DiscoveryDaemon",
    "PingerDaemon",
    "APIQuotaGovernor",
    "QuotaExceededError",
    "TrendScorer",
    "ViralityClassification",
    "VelocityTelemetry",
    "VideoMetadataService",
    "EnrichedVideoInfo",
    "normalize_youtube_url",
]

from .video_metadata import VideoMetadataService, EnrichedVideoInfo, normalize_youtube_url
