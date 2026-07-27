"""Application configuration."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DESKTOP_WEB_ORIGINS = (
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
)
LOCAL_WEB_ORIGIN_REGEX = r"^https?://(?:localhost|127\.0\.0\.1)(?::\d+)?$"
STORAGE_SETTINGS_SCHEMA = "reefvision-storage-settings-v1"
STORAGE_SETTING_FIELDS = ("data_dir", "model_cache_dir", "temp_dir")


def storage_settings_path() -> Path:
    """Return the stable per-user storage-settings file path."""

    configured = os.environ.get("REEFVISION_STORAGE_SETTINGS_FILE")
    if configured:
        return Path(configured).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return (
            Path(local_app_data).expanduser().resolve() / "ReefVision" / "config" / "storage.json"
        )
    return Path.home() / ".config" / "reefvision" / "storage.json"


def load_storage_overrides(path: Path | None = None) -> dict[str, str]:
    """Load persisted path overrides without allowing arbitrary settings injection."""

    settings_path = path or storage_settings_path()
    if not settings_path.is_file():
        return {}
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema") != STORAGE_SETTINGS_SCHEMA:
        return {}
    raw_paths = payload.get("paths")
    if not isinstance(raw_paths, dict):
        return {}
    overrides: dict[str, str] = {}
    for field_name in STORAGE_SETTING_FIELDS:
        value = raw_paths.get(field_name)
        if isinstance(value, str) and value.strip():
            overrides[field_name] = value.strip()
    return overrides


def write_storage_overrides(
    paths: dict[str, str],
    *,
    destination: Path | None = None,
) -> Path:
    """Persist validated storage paths atomically."""

    settings_path = destination or storage_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema": STORAGE_SETTINGS_SCHEMA,
        "paths": {
            field_name: paths[field_name]
            for field_name in STORAGE_SETTING_FIELDS
            if paths.get(field_name)
        },
    }
    temporary_path = settings_path.with_suffix(settings_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_path, settings_path)
    return settings_path


def storage_environment_locked(field_name: str) -> bool:
    """Return whether an environment value must override persisted preferences.

    The packaged desktop launcher always supplies REEFVISION_DATA_DIR as a safe
    fallback for first launch and for its runtime control files. In desktop mode,
    that internal fallback must not prevent a user-saved application data root
    from taking effect on the next restart. Other environment overrides remain
    authoritative deployment settings.
    """

    environment_name = f"REEFVISION_{field_name.upper()}"
    if environment_name not in os.environ:
        return False
    is_desktop_data_fallback = (
        field_name == "data_dir"
        and os.environ.get("REEFVISION_ENV", "").strip().casefold() == "desktop"
    )
    return not is_desktop_data_fallback


class Settings(BaseSettings):
    """Runtime settings populated from environment variables and user preferences."""

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
    model_cache_dir: Path | None = None
    temp_dir: Path | None = None
    database_url: str | None = None
    safe_mode: bool = False
    background_worker_enabled: bool = True
    worker_poll_seconds: float = Field(default=0.5, gt=0, le=60)
    worker_concurrency: int = Field(default=1, ge=1, le=64)
    thumbnail_max_width: int = Field(default=512, ge=64, le=4096)
    thumbnail_max_height: int = Field(default=512, ge=64, le=4096)
    model_max_upload_bytes: int = Field(default=2_147_483_648, ge=1_048_576)
    inference_default_confidence: float = Field(default=0.25, ge=0, le=1)
    inference_default_iou: float = Field(default=0.45, ge=0, le=1)
    assist_session_ttl_seconds: int = Field(default=900, ge=60, le=86_400)
    assist_cache_max_items: int = Field(default=4, ge=1, le=64)
    smart_mask_sample_spacing: float = Field(default=14.0, gt=1, le=512)
    allow_unsafe_pickled_models: bool = True
    allow_remote_vision: bool = False
    openai_api_key: str | None = Field(default=None, repr=False)
    gemini_api_key: str | None = Field(default=None, repr=False)
    remote_vision_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    log_max_bytes: int = Field(default=1_048_576, ge=65_536)
    log_backup_count: int = Field(default=5, ge=1, le=50)

    @field_validator("data_dir", "model_cache_dir", "temp_dir", mode="before")
    @classmethod
    def expand_storage_path(cls, value: object) -> Path | None:
        if value is None or str(value).strip() == "":
            return None
        return Path(str(value)).expanduser()

    @property
    def resolved_data_dir(self) -> Path:
        return self.data_dir.resolve()

    @property
    def resolved_model_cache_dir(self) -> Path:
        configured = self.model_cache_dir or (self.resolved_data_dir / "model-cache")
        return configured.resolve()

    @property
    def resolved_temp_dir(self) -> Path:
        configured = self.temp_dir or (self.resolved_data_dir / "tmp")
        return configured.resolve()

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
        self.resolved_model_cache_dir.mkdir(parents=True, exist_ok=True)
        self.resolved_temp_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    overrides = load_storage_overrides()
    for field_name in STORAGE_SETTING_FIELDS:
        if storage_environment_locked(field_name):
            overrides.pop(field_name, None)
    settings_factory = cast(Any, Settings)
    return cast(Settings, settings_factory(**overrides))


def clear_settings_cache() -> None:
    get_settings.cache_clear()
