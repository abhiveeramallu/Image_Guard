"""Application settings, read from environment variables (prefix IMAGEGUARD_)."""
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "1.1.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IMAGEGUARD_", env_file=".env", extra="ignore")

    environment: str = "development"  # "development" | "production"
    # Comma-separated list of allowed browser origins. Never "*" in production.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Upload limits
    max_upload_bytes: int = 10 * 1024 * 1024
    max_logo_bytes: int = 2 * 1024 * 1024
    max_image_side: int = 8000
    max_image_pixels: int = 16_000_000
    max_logo_pixels: int = 4_000_000
    min_image_side: int = 16

    # Temporary detection artifacts (in memory only)
    artifact_ttl_seconds: int = 900
    artifact_max_entries: int = 40
    artifact_max_bytes: int = 256 * 1024 * 1024

    # Invisible watermark: server-side secret (never sent to clients). Unset => feature unavailable.
    watermark_key: SecretStr | None = None
    watermark_min_pixels: int = 256 * 256

    # Model-based localization (ONNX). Unset path => reported as unavailable, never mocked.
    localization_model_path: str | None = None
    localization_model_config: str | None = None  # defaults to <model>.json
    model_device: str = "auto"  # "auto" | "cpu" | "cuda"
    model_threads: int = 2
    inference_timeout_seconds: float = 60.0
    inference_max_side: int = 1024

    # Throughput protection
    max_concurrent_jobs: int = 2
    job_wait_seconds: float = 15.0
    rate_limit_per_minute: int = 60  # per client IP, POST /api/* only; 0 disables

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]
        if self.is_production:
            origins = [o for o in origins if o != "*"]
        return origins


@lru_cache
def get_settings() -> Settings:
    return Settings()
