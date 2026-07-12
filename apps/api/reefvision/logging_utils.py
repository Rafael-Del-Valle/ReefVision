"""Structured rotating log configuration helpers."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from reefvision.config import Settings

API_LOG_FILENAME = "api.log"
BACKEND_LOG_FILENAME = "backend.log"
_MANAGED_HANDLER_ATTRIBUTE = "_reefvision_managed_handler"
_STRUCTURED_FIELDS = (
    "event_id",
    "correlation_id",
    "job_id",
    "project_id",
    "image_id",
    "dataset_version_id",
    "error_code",
    "schema_status",
    "current_schema_revision",
    "expected_schema_revision",
    "data_dir",
)


class StructuredJsonFormatter(logging.Formatter):
    """Render ReefVision logs as one JSON object per line."""

    def __init__(self, *, default_component: str) -> None:
        super().__init__()
        self.default_component = default_component

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "severity": record.levelname,
            "component": getattr(record, "component", self.default_component),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _STRUCTURED_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def default_logs_dir(settings: Settings) -> Path:
    return settings.resolved_data_dir / "logs"


def default_api_log_path(settings: Settings) -> Path:
    return default_logs_dir(settings) / API_LOG_FILENAME


def configure_rotating_json_logging(
    log_file: Path,
    *,
    default_component: str,
    max_bytes: int,
    backup_count: int,
) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    for handler in list(root_logger.handlers):
        if getattr(handler, _MANAGED_HANDLER_ATTRIBUTE, False):
            root_logger.removeHandler(handler)
            handler.close()

    handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    setattr(handler, _MANAGED_HANDLER_ATTRIBUTE, True)
    handler.setFormatter(StructuredJsonFormatter(default_component=default_component))
    root_logger.addHandler(handler)
