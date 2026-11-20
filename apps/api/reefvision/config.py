"""Application configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DESKTOP_WEB_ORIGINS = (
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
)
LOCAL_WEB_ORIGIN_REGEX = r"^https?://(?:localhost|127\.0\.0\.1)(?::\d+)?$"


class Settings(BaseSettings):
    """Runtime settings populated from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="REEFVISION_",
        case_sensitive=False,
        extra="ignore",
    )

    env: str = "development"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=0, le=65535)
    web_origin: str = "http://localhost:5173"
    data_dir: Path = Path(".reefvision")
    database_url: str | None = None
    safe_mode: bool = False
    background_worker_enabled: bool = True
    worker_poll_seconds: float = Field(default=0.5, gt=0, le=60)
    thumbnail_max_width: int = Field(default=512, ge=64, le=4096)
    thumbnail_max_height: int = Field(default=512, ge=64, le=4096)
    model_max_upload_bytes: int = Field(default=2_147_483_648, ge=1_048_576)
    inference_default_confidence: float = Field(default=0.25, ge=0, le=1)
    inference_default_iou: float = Field(default=0.45, ge=0, le=1)
    assist_session_ttl_seconds: int = Field(default=900, ge=60, le=86_400)
    assist_cache_max_items: int = Field(default=4, ge=1, le=64)
    smart_mask_sample_spacing: float = Field(default=14.0, gt=1, le=512)
    allow_unsafe_pickled_models: bool = True
    cloud_inference_enabled: bool = False
    cloud_request_timeout_seconds: float = Field(default=90.0, gt=1, le=600)
    cloud_max_inline_image_bytes: int = Field(default=15_000_000, ge=65_536, le=20_000_000)
    copernicus_username: SecretStr | None = Field(default=None, exclude=True)
    copernicus_password: SecretStr | None = Field(default=None, exclude=True)
    copernicus_python_executable: Path | None = None
    openai_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    log_max_bytes: int = Field(default=1_048_576, ge=65_536)
    log_backup_count: int = Field(default=5, ge=1, le=50)

    @field_validator("data_dir", mode="before")
    @classmethod
    def expand_data_dir(cls, value: object) -> Path:
        return Path(str(value)).expanduser()

    @property
    def resolved_data_dir(self) -> Path:
        return self.data_dir.resolve()

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        database_path = self.resolved_data_dir / "reefvision.db"
        return f"sqlite:///{database_path.as_posix()}"

    @property
    def allowed_web_origins(self) -> list[str]:
        return list(dict.fromkeys((self.web_origin, *DESKTOP_WEB_ORIGINS)))

    @property
    def allowed_web_origin_regex(self) -> str:
        return LOCAL_WEB_ORIGIN_REGEX

    def ensure_directories(self) -> None:
        self.resolved_data_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
