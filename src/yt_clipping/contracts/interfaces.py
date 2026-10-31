"""
Abstract Provider Interfaces for the YouTube Clipping Intelligence Platform.
Defines replaceable contracts for discovery, rights, media, AI models, QA, and handoff.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from .models import (
    VideoCandidate,
    MetricSnapshot,
    RightsManifest,
    Transcript,
    HighlightCandidate,
    RenderProfile,
    RenderedClip,
    QAReport,
    HandoffReceipt,
)


class RightsPolicyViolationError(Exception):
    """Raised when an operation is attempted on an unauthorized asset."""
    pass


class TranscriptionError(RuntimeError):
    """Raised when transcription fails across all cascade providers."""
    pass


class RenderingError(RuntimeError):
    """Raised when video rendering via FFmpeg fails."""
    pass


class DiscoveryProvider(ABC):
    """Fetches compliant, public video metadata and channel lists."""

    @abstractmethod
    def fetch_recent_videos(self, channel_id: str, limit: int = 10) -> List[VideoCandidate]:
        """Fetches latest uploads from an official channel uploads playlist or RSS feed."""
        pass

    @abstractmethod
    def get_video_metadata(self, video_id: str) -> Optional[VideoCandidate]:
        """Fetches public metadata for a single video."""
        pass


class MetricObserver(ABC):
    """Tracks time-stamped metric observations to calculate genuine view velocity."""

    @abstractmethod
    def record_snapshot(
        self, video_id: str, view_count: int, like_count: int = 0, comment_count: int = 0
    ) -> MetricSnapshot:
        """Stores a timestamped metric observation."""
        pass

    @abstractmethod
    def calculate_view_velocity(self, snapshots: List[MetricSnapshot]) -> float:
        """Computes views gained per hour between observations."""
        pass


class RightsPolicy(ABC):
    """Hard gate enforcing ownership, licensing, and platform terms before media processing."""

    @abstractmethod
    def check_rights(self, video_id: str) -> RightsManifest:
        """Returns the current rights status for a video."""
        pass

    @abstractmethod
    def verify_rights(self, manifest: RightsManifest) -> bool:
        """Validates that a manifest has verified rights and has not expired."""
        pass

    @abstractmethod
    def register_rights(self, manifest: RightsManifest) -> None:
        """Registers or updates a rights manifest in the local ledger."""
        pass


class AssetProvider(ABC):
    """Resolves authorized local media files or permitted source files."""

    @abstractmethod
    def resolve_asset(self, video_id: str, rights_manifest: RightsManifest) -> str:
        """
        Resolves the local filepath for the asset.
        MUST raise RightsPolicyViolationError if rights_manifest is not VERIFIED.
        """
        pass

    @abstractmethod
    def probe_asset(self, asset_path: str) -> Dict[str, Any]:
        """Probes media container for streams, duration, resolution, codecs."""
        pass


class Transcriber(ABC):
    """Transcribes audio/video to produce word-level timestamps and segments."""

    @abstractmethod
    def transcribe(self, media_path: str, video_id: str) -> Transcript:
        """Generates or loads transcript with word-level timestamps."""
        pass


class HighlightDetector(ABC):
    """Segments transcript into coherent, context-preserving candidate moments."""

    @abstractmethod
    def detect_candidates(
        self, transcript: Transcript, min_duration: float = 20.0, max_duration: float = 60.0
    ) -> List[HighlightCandidate]:
        """Detects candidate moments matching sentence boundaries and pause structures."""
        pass


class HighlightScorer(ABC):
    """Evaluates candidates using explainable multi-signal scorecard."""

    @abstractmethod
    def score_candidate(
        self, candidate: HighlightCandidate, transcript: Transcript
    ) -> HighlightCandidate:
        """Scores candidate hook, moment, coherence, and computes composite score."""
        pass


class Renderer(ABC):
    """Renders selected time interval to vertical short format with captions."""

    @abstractmethod
    def render_clip(
        self,
        source_path: str,
        candidate: HighlightCandidate,
        profile: RenderProfile,
        output_dir: str,
    ) -> RenderedClip:
        """Renders vertical clip using FFmpeg or local pipeline."""
        pass


class QualityVerifier(ABC):
    """Verifies exported media file against structural and perceptual quality thresholds."""

    @abstractmethod
    def verify_clip(
        self, rendered_clip: RenderedClip, candidate: HighlightCandidate
    ) -> QAReport:
        """Checks streams, aspect ratio, duration, audio levels, and checksum."""
        pass


class HandoffPublisher(ABC):
    """Delivers approved, rights-cleared clips to external autopost automation."""

    @abstractmethod
    def publish_clip(
        self,
        rendered_clip: RenderedClip,
        candidate: HighlightCandidate,
        rights_manifest: RightsManifest,
        qa_report: QAReport,
        dry_run: bool = True,
    ) -> HandoffReceipt:
        """
        Submits clip to downstream autopost system.
        MUST reject submission if rights or QA failed.
        """
        pass
