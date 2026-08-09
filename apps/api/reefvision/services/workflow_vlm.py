"""Provider-neutral cloud vision detection for Auto Label workflows."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

import httpx

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.storage.datasets import canonical_json_sha256

SUPPORTED_VLM_PROVIDERS = {"openai", "gemini", "anthropic"}
SUPPORTED_INLINE_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


@dataclass(frozen=True, slots=True)
class VlmClassDefinition:
    label_class_id: str
    name: str
    scientific_name: str | None = None
    state_name: str | None = None
    description: str | None = None


class CloudVlmProviderError(RuntimeError):
    """A provider failure that is distinct from genuine model disagreement."""

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(f"{provider} provider error: {message}")
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable


def _provider_key(settings: Settings, provider: str) -> str:
    secret = {
        "openai": settings.openai_api_key,
        "gemini": settings.gemini_api_key,
        "anthropic": settings.anthropic_api_key,
    }.get(provider)
    if secret is None or not secret.get_secret_value().strip():
        raise ValidationError(
            f"{provider} Auto Label requires the corresponding REEFVISION_*_API_KEY setting"
        )
    return secret.get_secret_value().strip()


def _detection_schema(class_ids: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "detections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label_class_id": {"type": "string", "enum": class_ids},
                        "box_2d": {
                            "type": "array",
                            "items": {"type": "number", "minimum": 0, "maximum": 1000},
                            "minItems": 4,
                            "maxItems": 4,
                        },
                    },
                    "required": ["label_class_id", "box_2d"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["detections"],
        "additionalProperties": False,
    }


def _class_prompt(classes: list[VlmClassDefinition]) -> str:
    lines: list[str] = []
    for item in classes:
        details = [item.name]
        if item.scientific_name:
            details.append(item.scientific_name)
        if item.state_name:
            details.append(item.state_name)
        if item.description:
            details.append(item.description)
        lines.append(f"- {item.label_class_id}: {' | '.join(details)}")
    return "\n".join(lines)


def build_detection_prompt(
    user_prompt: str,
    classes: list[VlmClassDefinition],
) -> str:
    return (
        "You are an image annotation model inside ReefVision. Detect only the allowed "
        "classes listed below. Return one tight bounding box per visible instance. Do not "
        "invent objects. If an instance is too ambiguous to assign to an allowed class, omit "
        "it. box_2d must be [ymin, xmin, ymax, xmax] using image-normalized coordinates from "
        "0 to 1000. Use the exact label_class_id values; never create a new class.\n\n"
        f"Task guidance:\n{user_prompt.strip()}\n\n"
        f"Allowed classes:\n{_class_prompt(classes)}"
    )


def _extract_json_text(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ("output_text", "text"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip().startswith(("{", "[")):
                return value
        for value in payload.values():
            found = _extract_json_text(value)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _extract_json_text(value)
            if found is not None:
                return found
    return None


def _openai_request(
    *,
    model: str,
    prompt: str,
    schema: dict[str, Any],
    image_b64: str,
    media_type: str,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    return (
        "https://api.openai.com/v1/responses",
        {},
        {
            "model": model,
            "store": False,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": f"data:{media_type};base64,{image_b64}",
                            "detail": "high",
                        },
                    ],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "reefvision_detections",
                    "schema": schema,
                    "strict": True,
                }
            },
        },
    )


def _gemini_request(
    *,
    model: str,
    prompt: str,
    schema: dict[str, Any],
    image_b64: str,
    media_type: str,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    model_name = model.removeprefix("models/")
    return (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent",
        {},
        {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": media_type,
                                "data": image_b64,
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "responseFormat": {
                    "text": {
                        "mimeType": "application/json",
                        "schema": schema,
                    }
                }
            },
        },
    )


def _anthropic_request(
    *,
    model: str,
    prompt: str,
    schema: dict[str, Any],
    image_b64: str,
    media_type: str,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    return (
        "https://api.anthropic.com/v1/messages",
        {"anthropic-version": "2023-06-01"},
        {
            "model": model,
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            "tools": [
                {
                    "name": "submit_detections",
                    "description": "Submit the ReefVision detections for this image.",
                    "input_schema": schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": "submit_detections"},
        },
    )


def _provider_request(
    provider: str,
    *,
    model: str,
    prompt: str,
    schema: dict[str, Any],
    image_b64: str,
    media_type: str,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    builder = {
        "openai": _openai_request,
        "gemini": _gemini_request,
        "anthropic": _anthropic_request,
    }.get(provider)
    if builder is None:
        raise ValidationError(f"Unsupported VLM provider: {provider}")
    return builder(
        model=model,
        prompt=prompt,
        schema=schema,
        image_b64=image_b64,
        media_type=media_type,
    )


def _extract_provider_result(provider: str, response: dict[str, Any]) -> dict[str, Any]:
    if provider == "anthropic":
        for item in response.get("content", []):
            if (
                isinstance(item, dict)
                and item.get("type") == "tool_use"
                and item.get("name") == "submit_detections"
                and isinstance(item.get("input"), dict)
            ):
                return dict(item["input"])
        raise CloudVlmProviderError(
            provider,
            "response did not contain submit_detections tool data",
        )

    text = _extract_json_text(response)
    if text is None:
        raise CloudVlmProviderError(provider, "response did not contain structured JSON output")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CloudVlmProviderError(provider, "structured output was not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise CloudVlmProviderError(provider, "structured output must be a JSON object")
    return parsed


def _usage_metadata(provider: str, response: dict[str, Any]) -> dict[str, Any]:
    if provider == "openai":
        usage = response.get("usage")
    elif provider == "anthropic":
        usage = response.get("usage")
    else:
        usage = response.get("usage_metadata") or response.get("usageMetadata")
    return dict(usage) if isinstance(usage, dict) else {}


def _response_id(response: dict[str, Any]) -> str | None:
    value = response.get("id")
    return str(value) if value is not None else None


def _normalize_detections(
    provider_payload: dict[str, Any],
    *,
    classes: list[VlmClassDefinition],
    image_id: str,
    image_width: int,
    image_height: int,
) -> list[dict[str, Any]]:
    class_by_id = {item.label_class_id: item for item in classes}
    raw_detections = provider_payload.get("detections")
    if not isinstance(raw_detections, list):
        raise CloudVlmProviderError("vlm", "structured output is missing detections array")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw_detections, start=1):
        if not isinstance(item, dict):
            continue
        label_class_id = str(item.get("label_class_id") or "")
        class_definition = class_by_id.get(label_class_id)
        box = item.get("box_2d")
        if class_definition is None or not isinstance(box, list) or len(box) != 4:
            continue
        try:
            y_min, x_min, y_max, x_max = [
                min(max(float(value), 0.0), 1000.0) for value in box
            ]
        except (TypeError, ValueError):
            continue
        if x_max <= x_min or y_max <= y_min:
            continue
        normalized.append(
            {
                "proposal_id": None,
                "image_id": image_id,
                "label_class_id": label_class_id,
                "predicted_label": class_definition.name,
                "confidence": 1.0,
                "confidence_kind": "vote_only_not_calibrated",
                "geometry_kind": "box",
                "box": {
                    "x_min": (x_min / 1000.0) * image_width,
                    "y_min": (y_min / 1000.0) * image_height,
                    "x_max": (x_max / 1000.0) * image_width,
                    "y_max": (y_max / 1000.0) * image_height,
                },
                "provider_detection_index": index,
            }
        )
    return normalized


def run_vlm_detection(
    settings: Settings,
    *,
    provider: str,
    model: str,
    prompt: str,
    classes: list[VlmClassDefinition],
    image_id: str,
    image_bytes: bytes,
    media_type: str,
    image_width: int,
    image_height: int,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Call one cloud vision provider and normalize its result for consensus voting."""

    provider = provider.strip().lower()
    if provider not in SUPPORTED_VLM_PROVIDERS:
        raise ValidationError(f"Unsupported VLM provider: {provider}")
    if not settings.cloud_inference_enabled:
        raise ValidationError(
            "Cloud Auto Label is disabled. Set REEFVISION_CLOUD_INFERENCE_ENABLED=true "
            "after confirming imagery may be sent to the selected provider."
        )
    if not model.strip():
        raise ValidationError("VLM detection requires an explicit provider model name")
    if not classes:
        raise ValidationError("VLM detection requires at least one allowed ReefVision class")
    if media_type not in SUPPORTED_INLINE_MEDIA_TYPES:
        raise ValidationError(
            f"Cloud Auto Label does not support inline media type {media_type}; "
            "use JPEG, PNG, WebP, or non-animated GIF"
        )
    if len(image_bytes) > settings.cloud_max_inline_image_bytes:
        raise ValidationError(
            "Image is too large for ReefVision inline cloud inference; reduce the image size "
            "or use a future provider file-upload workflow"
        )
    if image_width <= 0 or image_height <= 0:
        raise ValidationError("Cloud Auto Label requires known positive image dimensions")

    api_key = _provider_key(settings, provider)
    schema = _detection_schema([item.label_class_id for item in classes])
    full_prompt = build_detection_prompt(prompt, classes)
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    url, extra_headers, body = _provider_request(
        provider,
        model=model.strip(),
        prompt=full_prompt,
        schema=schema,
        image_b64=image_b64,
        media_type=media_type,
    )
    headers = {"Content-Type": "application/json", **extra_headers}
    if provider == "openai":
        headers["Authorization"] = f"Bearer {api_key}"
    elif provider == "gemini":
        headers["x-goog-api-key"] = api_key
    else:
        headers["x-api-key"] = api_key

    owns_client = client is None
    active_client = client or httpx.Client(timeout=settings.cloud_request_timeout_seconds)
    try:
        response = active_client.post(url, headers=headers, json=body)
        if response.status_code >= 400:
            retryable = response.status_code == 429 or response.status_code >= 500
            try:
                error_payload = response.json()
                message = str(
                    error_payload.get("error")
                    or error_payload.get("message")
                    or "HTTP error"
                )
            except (ValueError, AttributeError):
                message = response.text[:500] or "HTTP error"
            raise CloudVlmProviderError(
                provider,
                message,
                status_code=response.status_code,
                retryable=retryable,
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise CloudVlmProviderError(provider, "provider response was not a JSON object")
    except httpx.TimeoutException as exc:
        raise CloudVlmProviderError(provider, "request timed out", retryable=True) from exc
    except httpx.RequestError as exc:
        raise CloudVlmProviderError(provider, str(exc), retryable=True) from exc
    finally:
        if owns_client:
            active_client.close()

    provider_result = _extract_provider_result(provider, payload)
    detections = _normalize_detections(
        provider_result,
        classes=classes,
        image_id=image_id,
        image_width=image_width,
        image_height=image_height,
    )
    return {
        "provider": provider,
        "model": model.strip(),
        "response_id": _response_id(payload),
        "usage": _usage_metadata(provider, payload),
        "prompt_sha256": canonical_json_sha256({"prompt": full_prompt}),
        "schema_sha256": canonical_json_sha256(schema),
        "detections": detections,
    }
