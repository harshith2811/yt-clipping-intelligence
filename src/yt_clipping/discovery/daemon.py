"""
Continuous Discovery Daemon Service (FEATURE-01).
Polls registered creator channels at configured intervals (default: 300s),
leverages zero-cost RSS Atom feeds with ETag caching, calculates view velocity,
and queues top-performing videos for clipping.
Handles SIGINT and SIGTERM gracefully.
"""

from typing import Optional, Dict, Any, List
import time
import signal
import sys
import logging
from datetime import datetime, timezone

from ..config import AppConfig
from .channel_registry import ChannelRegistry
from .monitor import ChannelMonitor
from .ranker import PublicMetricRanker
from ..rights.gate import LocalRightsPolicy
from ..contracts.models import VideoCandidate, CreatorSource

logger = logging.getLogger("yt_clipping.daemon")


class DiscoveryDaemon:
    """
    Continuous background monitor service for creator channels.
    """

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        interval_seconds: int = 300,
        monitor: Optional[ChannelMonitor] = None,
        registry: Optional[ChannelRegistry] = None,
        ranker: Optional[PublicMetricRanker] = None,
        rights_policy: Optional[LocalRightsPolicy] = None,
    ):
        self.config = config or AppConfig()
        self.interval = interval_seconds
        self.registry = registry or ChannelRegistry(self.config.db_path)
        self.monitor = monitor or ChannelMonitor(
            api_key=self.config.youtube_api_key,
            db_path=self.config.db_path,
        )
        self.ranker = ranker or PublicMetricRanker(db_path=self.config.db_path)
        self.rights_policy = rights_policy or LocalRightsPolicy(
            ledger_path=self.config.rights_ledger_path,
            db_path=self.config.db_path,
        )

        self._running = False
        self._cycles_completed = 0
        self._total_discovered = 0
        self._discovered_videos: List[VideoCandidate] = []

    def stop(self, signum=None, frame=None) -> None:
        """Signals daemon to gracefully stop after current iteration."""
        self._running = False
        logger.info("Daemon received shutdown signal. Terminating gracefully...")

    def run(self, max_iterations: Optional[int] = None) -> Dict[str, Any]:
        """
        Runs the discovery daemon loop.
        If max_iterations is set, stops after that many iterations.
        """
        self._running = True

        # Register OS signal handlers if running on main thread
        try:
            signal.signal(signal.SIGINT, self.stop)
            signal.signal(signal.SIGTERM, self.stop)
        except (ValueError, AttributeError):
            pass

        logger.info(f"Discovery Daemon started with interval={self.interval}s")

        while self._running:
            self._run_cycle()
            self._cycles_completed += 1

            if max_iterations is not None and self._cycles_completed >= max_iterations:
                break

            # Sleep in small slices to remain responsive to shutdown signals
            sleep_slices = max(1, int(self.interval))
            for _ in range(sleep_slices):
                if not self._running:
                    break
                time.sleep(1)

        return self.get_telemetry()

    def _run_cycle(self) -> None:
        """Executes a single discovery polling pass across all active channels."""
        channels = self.registry.list_channels(active_only=True)
        logger.debug(f"Polling {len(channels)} active channels...")

        for ch in channels:
            if not self._running:
                break

            channel_id = ch["channel_id"]
            try:
                # 1. Fetch recent candidates (uses RSS client with ETag 304 caching)
                candidates = self.monitor.fetch_recent_videos(channel_id, limit=5)
                self.registry.update_last_polled(channel_id)

                creator = self.registry.get_creator_source(channel_id) or CreatorSource(
                    creator_id=channel_id,
                    name=ch["name"],
                    channel_id=channel_id,
                    channel_url=ch.get("channel_url", ""),
                    baseline_views=ch.get("baseline_views", 10000.0),
                )

                # 2. Score candidate performance against creator baseline
                for cand in candidates:
                    self.ranker.compute_discovery_score(cand, creator)
                    self._total_discovered += 1
                    self._discovered_videos.append(cand)
                    logger.info(
                        f"Discovered '{cand.video_id}' ({cand.title[:30]}...) "
                        f"Score={cand.discovery_score:.1f} Rationale={cand.discovery_rationale}"
                    )

            except Exception as e:
                logger.error(f"Error polling channel {channel_id}: {e}")

    def get_telemetry(self) -> Dict[str, Any]:
        """Returns operational metrics for health and CLI reporting."""
        return {
            "cycles_completed": self._cycles_completed,
            "total_discovered": self._total_discovered,
            "interval_seconds": self.interval,
            "is_running": self._running,
            "discovered_videos_sample": [
                {
                    "video_id": v.video_id,
                    "title": v.title,
                    "score": v.discovery_score,
                    "creator_id": v.creator_id,
                }
                for v in self._discovered_videos[-10:]
            ],
        }
