"""
Centralized, Typed Application Configuration for YouTube Clipping Intelligence.
Provides explicit precedence: CLI Arguments > Environment Variables > Defaults.
Includes environment validation and secret masking.
"""

from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()


@dataclass
class AppConfig:
    # Storage and directory paths
    base_data_dir: str = "data"
    assets_dir: str = "data/assets"
    output_dir: str = "data/rendered_clips"
    temp_dir: str = "data/temp"
    transcripts_dir: str = "data/transcripts"
    heatmaps_dir: str = "data/heatmaps"
    db_path: str = "data/jobs.db"
    rights_ledger_path: str = "data/rights_ledger.json"

    # Publisher / Autopost settings
    autopost_mode: str = "watched_folder"  # "watched_folder" or "webhook"
    autopost_inbox: str = "data/autopost_inbox"
    autopost_webhook_url: Optional[str] = None
    autopost_auth_token: Optional[str] = None
    receipts_path: str = "data/handoffs/receipts.json"

    # API Keys & External Services
    youtube_api_key: Optional[str] = None
    llm_api_base: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: str = "llama3"

    # Transcription configuration
    transcription_provider: str = "faster-whisper"  # "faster-whisper", "cloud", "test"
    transcription_model: str = "base"
    transcription_device: str = "auto"  # "auto", "cuda", "cpu"
    transcription_compute_type: str = "auto"  # "auto", "float16", "int8"
    enable_synthetic_fallbacks: bool = False  # Strictly False in production

    # Rendering configuration
    render_layout: str = "blur_background"  # "blur_background", "crop_center", "split_screen", "active_speaker"
    render_vcodec: str = "libx264"
    render_crf: int = 18
    render_preset: str = "fast"
    burn_subtitles: bool = True
    subtitle_style: str = "bold_social"  # "classic", "clean_editorial", "karaoke", "bold_social"

    # Discovery & Monitoring
    discovery_interval: int = 300
    daily_quota_limit: int = 10000
    retention_days: int = 30
    log_level: str = "INFO"
    execution_mode: str = "production"  # "production", "development", "testing"

    def __post_init__(self):
        # Create directories
        for d in [
            self.base_data_dir,
            self.assets_dir,
            self.output_dir,
            self.temp_dir,
            self.transcripts_dir,
            self.heatmaps_dir,
            os.path.dirname(os.path.abspath(self.db_path)),
            os.path.dirname(os.path.abspath(self.receipts_path)),
        ]:
            if d:
                os.makedirs(d, exist_ok=True)

    @classmethod
    def load_from_env(cls, **cli_overrides: Any) -> "AppConfig":
        """Loads configuration combining defaults, environment variables, and CLI overrides."""
        cfg = cls()

        # Environment variable mapping
        env_map = {
            "DATA_DIR": "base_data_dir",
            "ASSETS_DIR": "assets_dir",
            "OUTPUT_DIR": "output_dir",
            "TEMP_DIR": "temp_dir",
            "TRANSCRIPTS_DIR": "transcripts_dir",
            "HEATMAPS_DIR": "heatmaps_dir",
            "DATABASE_PATH": "db_path",
            "DB_PATH": "db_path",
            "RIGHTS_LEDGER_PATH": "rights_ledger_path",
            "AUTOPOST_MODE": "autopost_mode",
            "AUTOPOST_INBOX": "autopost_inbox",
            "AUTOPOST_WEBHOOK_URL": "autopost_webhook_url",
            "WEBHOOK_URL": "autopost_webhook_url",
            "AUTOPOST_AUTH_TOKEN": "autopost_auth_token",
            "RECEIPTS_PATH": "receipts_path",
            "YOUTUBE_API_KEY": "youtube_api_key",
            "LLM_API_BASE": "llm_api_base",
            "LLM_API_KEY": "llm_api_key",
            "LLM_MODEL": "llm_model",
            "TRANSCRIPTION_PROVIDER": "transcription_provider",
            "TRANSCRIPTION_MODEL": "transcription_model",
            "TRANSCRIPTION_DEVICE": "transcription_device",
            "TRANSCRIPTION_COMPUTE_TYPE": "transcription_compute_type",
            "ENABLE_SYNTHETIC_FALLBACKS": "enable_synthetic_fallbacks",
            "RENDER_LAYOUT": "render_layout",
            "RENDER_VCODEC": "render_vcodec",
            "RENDER_CRF": "render_crf",
            "RENDER_PRESET": "render_preset",
            "BURN_SUBTITLES": "burn_subtitles",
            "SUBTITLE_STYLE": "subtitle_style",
            "DISCOVERY_INTERVAL": "discovery_interval",
            "DAILY_QUOTA_LIMIT": "daily_quota_limit",
            "RETENTION_DAYS": "retention_days",
            "LOG_LEVEL": "log_level",
            "EXECUTION_MODE": "execution_mode",
        }

        for env_k, attr_name in env_map.items():
            val = os.getenv(env_k)
            if val is not None:
                # Type conversions
                attr_type = type(getattr(cfg, attr_name))
                if attr_type == bool:
                    setattr(cfg, attr_name, val.lower() in ("true", "1", "yes"))
                elif attr_type == int:
                    try:
                        setattr(cfg, attr_name, int(val))
                    except ValueError:
                        pass
                else:
                    setattr(cfg, attr_name, val)

        # Apply CLI overrides (which take highest precedence)
        for k, v in cli_overrides.items():
            if v is not None and hasattr(cfg, k):
                setattr(cfg, k, v)

        return cfg

    def validate(self) -> Dict[str, Any]:
        """Validates configuration parameters and returns health report."""
        issues = []
        warnings = []

        if self.autopost_mode not in ("watched_folder", "webhook"):
            issues.append(f"Invalid autopost_mode: '{self.autopost_mode}'. Must be 'watched_folder' or 'webhook'.")

        if self.autopost_mode == "webhook" and not self.autopost_webhook_url:
            warnings.append("Autopost mode is 'webhook' but autopost_webhook_url is not configured.")

        if self.render_vcodec not in ("libx264", "h264_nvenc", "hevc_nvenc", "libx265"):
            issues.append(f"Unsupported render_vcodec: '{self.render_vcodec}'.")

        if self.subtitle_style not in ("classic", "clean_editorial", "karaoke", "bold_social"):
            warnings.append(f"Unknown subtitle_style '{self.subtitle_style}', will fall back to bold_social.")

        if not self.youtube_api_key:
            warnings.append("YOUTUBE_API_KEY is not set. Data API queries will fail or fall back to RSS/Atom feeds.")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
        }

    def masked_summary(self) -> Dict[str, Any]:
        """Returns configuration summary with secrets safely masked."""
        def mask(s: Optional[str]) -> str:
            if not s:
                return "<not configured>"
            if len(s) <= 6:
                return "***"
            return s[:3] + "..." + s[-3:]

        return {
            "execution_mode": self.execution_mode,
            "assets_dir": self.assets_dir,
            "output_dir": self.output_dir,
            "db_path": self.db_path,
            "autopost_mode": self.autopost_mode,
            "autopost_webhook_url": self.autopost_webhook_url or "<none>",
            "autopost_auth_token": mask(self.autopost_auth_token),
            "youtube_api_key": mask(self.youtube_api_key),
            "transcription_provider": self.transcription_provider,
            "transcription_model": self.transcription_model,
            "transcription_device": self.transcription_device,
            "render_layout": self.render_layout,
            "render_vcodec": self.render_vcodec,
            "subtitle_style": self.subtitle_style,
            "discovery_interval": self.discovery_interval,
            "daily_quota_limit": self.daily_quota_limit,
        }

    @classmethod
    def from_env_and_cli(cls, **cli_overrides: Any) -> "AppConfig":
        return cls.load_from_env(**cli_overrides)

    def get_masked_config(self) -> Dict[str, Any]:
        return self.masked_summary()

    def validate_environment(self) -> List[str]:
        val = self.validate()
        return val["issues"] + val["warnings"]
