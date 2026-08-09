"""Safe cloud Auto Label readiness without exposing credential material."""

from __future__ import annotations

from typing import Any

from reefvision.config import Settings


def _configured(secret: object) -> bool:
    if secret is None:
        return False
    getter = getattr(secret, "get_secret_value", None)
    if not callable(getter):
        return False
    return bool(str(getter()).strip())


def cloud_auto_label_status(settings: Settings) -> dict[str, Any]:
    return {
        "cloud_inference_enabled": settings.cloud_inference_enabled,
        "providers": {
            "openai": {"configured": _configured(settings.openai_api_key)},
            "gemini": {"configured": _configured(settings.gemini_api_key)},
            "anthropic": {"configured": _configured(settings.anthropic_api_key)},
        },
        "credentials_exposed": False,
    }
