"""SAM 2 Prompt Assist provider backed by an isolated localhost sidecar."""

from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass
from io import BytesIO
from math import isfinite
from pathlib import Path
from typing import Any
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request

import numpy as np
from PIL import Image, UnidentifiedImageError

from reefvision.domain.errors import ValidationError
from reefvision.ml.providers import (
    AssistModelMetadata,
    AssistPrediction,
    PixelBox,
    PixelPoint,
    mask_to_box,
)

_PROVIDER_NAME = "sam2_sidecar"
_DESCRIPTOR_SCHEMA = "reefvision-sam2-sidecar-v1"
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


@dataclass(frozen=True, slots=True)
class PreparedSam2SidecarImage:
    image_png_base64: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class Sam2SidecarDescriptor:
    endpoint: str
    token_env: str
    timeout_seconds: float
    provider_version: str


def _validated_endpoint(value: object) -> str:
    endpoint = str(value or "").strip().rstrip("/")
    parsed = url_parse.urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"}:
        raise ValidationError("SAM 2 sidecar endpoint must use http or https")
    if parsed.hostname is None or parsed.hostname.casefold() not in _LOOPBACK_HOSTS:
        raise ValidationError("SAM 2 sidecar endpoint must remain on localhost")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValidationError("SAM 2 sidecar endpoint may not contain credentials or query data")
    return endpoint


def _read_descriptor(model_path: Path) -> Sam2SidecarDescriptor:
    if not model_path.is_file() or model_path.suffix.casefold() != ".json":
        raise ValidationError("SAM 2 sidecar registration descriptor is missing")
    try:
        payload = json.loads(model_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("SAM 2 sidecar descriptor is not valid JSON") from exc
    if not isinstance(payload, dict) or payload.get("schema") != _DESCRIPTOR_SCHEMA:
        raise ValidationError("SAM 2 sidecar descriptor schema is unsupported")
    token_env = str(payload.get("token_env", "REEFVISION_SAM2_SIDECAR_TOKEN")).strip()
    if (
        not token_env
        or not token_env.replace("_", "").isalnum()
        or not token_env[0].isalpha()
    ):
        raise ValidationError("SAM 2 sidecar token environment name is invalid")
    try:
        timeout_seconds = float(payload.get("timeout_seconds", 120.0))
    except (TypeError, ValueError) as exc:
        raise ValidationError("SAM 2 sidecar timeout is invalid") from exc
    if not 1 <= timeout_seconds <= 600:
        raise ValidationError("SAM 2 sidecar timeout must be between 1 and 600 seconds")
    provider_version = str(payload.get("sam2_version", "sam2")).strip() or "sam2"
    return Sam2SidecarDescriptor(
        endpoint=_validated_endpoint(payload.get("endpoint")),
        token_env=token_env,
        timeout_seconds=timeout_seconds,
        provider_version=provider_version,
    )


def _read_json_response(raw: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError("SAM 2 sidecar returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValidationError("SAM 2 sidecar returned an unexpected response")
    return parsed


def _get_json(
    url: str,
    *,
    token: str | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = url_request.Request(url, headers=headers, method="GET")
    try:
        with url_request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except url_error.HTTPError as exc:
        body = exc.read(2048).decode("utf-8", errors="replace")
        raise ValidationError(f"SAM 2 sidecar returned HTTP {exc.code}: {body}") from exc
    except (url_error.URLError, TimeoutError, OSError) as exc:
        raise ValidationError(f"SAM 2 sidecar request failed: {exc}") from exc
    return _read_json_response(raw)


def _post_json(
    url: str,
    *,
    token: str | None,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = url_request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with url_request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except url_error.HTTPError as exc:
        body = exc.read(2048).decode("utf-8", errors="replace")
        raise ValidationError(f"SAM 2 sidecar returned HTTP {exc.code}: {body}") from exc
    except (url_error.URLError, TimeoutError, OSError) as exc:
        raise ValidationError(f"SAM 2 sidecar request failed: {exc}") from exc
    return _read_json_response(raw)


def check_sam2_sidecar_health(
    endpoint: str,
    *,
    token_env: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Validate and query a SAM 2 sidecar without exposing its bearer token."""

    validated_endpoint = _validated_endpoint(endpoint)
    normalized_token_env = token_env.strip()
    if (
        not normalized_token_env
        or not normalized_token_env.replace("_", "").isalnum()
        or not normalized_token_env[0].isalpha()
    ):
        raise ValidationError("SAM 2 sidecar token environment name is invalid")
    if not 1 <= timeout_seconds <= 600:
        raise ValidationError("SAM 2 sidecar timeout must be between 1 and 600 seconds")
    token = os.environ.get(normalized_token_env)
    payload = _get_json(
        f"{validated_endpoint}/health",
        token=token,
        timeout_seconds=timeout_seconds,
    )
    status = str(payload.get("status", "")).strip().casefold()
    provider = str(payload.get("provider", "")).strip().casefold()
    device = str(payload.get("device", "")).strip()
    model_version_raw = payload.get("model_version")
    model_version = None if model_version_raw is None else str(model_version_raw).strip()
    if status != "ok":
        raise ValidationError("SAM 2 sidecar health response did not report status=ok")
    if provider != _PROVIDER_NAME:
        raise ValidationError("The endpoint is not a ReefVision SAM 2 sidecar")
    if not device:
        raise ValidationError("SAM 2 sidecar health response is missing its device")
    return {
        "status": status,
        "provider": provider,
        "model_version": model_version or None,
        "device": device,
        "endpoint": validated_endpoint,
        "token_configured": token is not None,
    }


def _prepared_image(image_path: Path) -> PreparedSam2SidecarImage:
    try:
        with Image.open(image_path) as source:
            source.load()
            rgb = source.convert("RGB")
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError("Could not read the image for SAM 2 sidecar refinement") from exc
    stream = BytesIO()
    rgb.save(stream, format="PNG", optimize=True)
    return PreparedSam2SidecarImage(
        image_png_base64=base64.b64encode(stream.getvalue()).decode("ascii"),
        width=rgb.width,
        height=rgb.height,
    )


def _mask_prediction(
    payload: dict[str, Any],
    *,
    width: int,
    height: int,
) -> AssistPrediction:
    encoded = payload.get("mask_png_base64")
    if not isinstance(encoded, str) or not encoded:
        raise ValidationError("SAM 2 sidecar response is missing a mask")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValidationError("SAM 2 sidecar mask is not valid base64") from exc
    try:
        with Image.open(BytesIO(raw)) as source:
            source.load()
            if source.size != (width, height):
                raise ValidationError("SAM 2 sidecar mask dimensions do not match the source image")
            mask = np.asarray(source.convert("L"), dtype=np.uint8) > 0
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError("SAM 2 sidecar mask is not a readable PNG") from exc
    if not bool(mask.any()):
        raise ValidationError("SAM 2 sidecar returned an empty mask")
    try:
        score = float(payload.get("score", 0.0))
    except (TypeError, ValueError) as exc:
        raise ValidationError("SAM 2 sidecar returned an invalid score") from exc
    if not 0 <= score <= 1:
        raise ValidationError("SAM 2 sidecar score is outside 0 to 1")
    return AssistPrediction(mask=mask, box=mask_to_box(mask), score=score)


def _validated_box(box: PixelBox, *, width: int, height: int) -> list[float]:
    values = [box.x_min, box.y_min, box.x_max, box.y_max]
    if not all(isfinite(value) for value in values) or not (
        0 <= box.x_min < box.x_max <= width
        and 0 <= box.y_min < box.y_max <= height
    ):
        raise ValidationError("SAM 2 sidecar box prompt is outside the image")
    return values


def _validated_points(
    points: list[PixelPoint],
    *,
    width: int,
    height: int,
) -> list[list[float]]:
    payload: list[list[float]] = []
    for point in points:
        if not (isfinite(point.x) and isfinite(point.y)) or not (
            0 <= point.x < width and 0 <= point.y < height
        ):
            raise ValidationError("SAM 2 sidecar point prompt is outside the image")
        payload.append([point.x, point.y])
    return payload


class SAM2SidecarAssistProvider:
    """Use SAM 2 in a separate Python/CUDA environment over loopback HTTP."""

    provider_name = _PROVIDER_NAME

    def __init__(self) -> None:
        self.provider_version = "unknown"
        self._endpoint: str | None = None
        self._timeout_seconds = 120.0
        self._token: str | None = None
        self._device = "auto"

    def inspect_model(self, model_path: Path) -> AssistModelMetadata:
        descriptor = _read_descriptor(model_path)
        return AssistModelMetadata(
            framework="sam2-sidecar",
            task="assist_segmentation",
            provider_name=self.provider_name,
            provider_version=descriptor.provider_version,
            metadata={
                "descriptor_schema": _DESCRIPTOR_SCHEMA,
                "endpoint": descriptor.endpoint,
                "token_env": descriptor.token_env,
                "timeout_seconds": descriptor.timeout_seconds,
                "local_sidecar": True,
                "automatic_downloads_disabled": True,
                "capabilities": (
                    "box_prompt",
                    "point_prompt",
                    "negative_points",
                    "context_box",
                ),
            },
        )

    def load_model(self, model_path: Path, device: str) -> None:
        descriptor = _read_descriptor(model_path)
        self._endpoint = descriptor.endpoint
        self._timeout_seconds = descriptor.timeout_seconds
        self._token = os.environ.get(descriptor.token_env)
        self._device = device
        self.provider_version = descriptor.provider_version

    def prepare_image(self, image_path: Path) -> PreparedSam2SidecarImage:
        if self._endpoint is None:
            raise ValidationError("SAM 2 sidecar provider is not loaded")
        return _prepared_image(image_path)

    def predict_from_points(
        self,
        prepared: PreparedSam2SidecarImage,
        positive_points: list[PixelPoint],
        negative_points: list[PixelPoint],
        context_box: PixelBox | None = None,
    ) -> AssistPrediction:
        if self._endpoint is None:
            raise ValidationError("SAM 2 sidecar provider is not loaded")
        if not positive_points and context_box is None:
            raise ValidationError(
                "SAM 2 sidecar point prompting requires a positive point or context box"
            )
        positive_payload = _validated_points(
            positive_points,
            width=prepared.width,
            height=prepared.height,
        )
        negative_payload = _validated_points(
            negative_points,
            width=prepared.width,
            height=prepared.height,
        )
        context_payload = (
            _validated_box(context_box, width=prepared.width, height=prepared.height)
            if context_box is not None
            else None
        )
        response = _post_json(
            f"{self._endpoint}/segment-points",
            token=self._token,
            payload={
                "image_png_base64": prepared.image_png_base64,
                "positive_points": positive_payload,
                "negative_points": negative_payload,
                "context_box": context_payload,
                "device": self._device,
            },
            timeout_seconds=self._timeout_seconds,
        )
        self.provider_version = str(response.get("model_version", self.provider_version))
        return _mask_prediction(
            response,
            width=prepared.width,
            height=prepared.height,
        )

    def predict_from_box(
        self,
        prepared: PreparedSam2SidecarImage,
        box: PixelBox,
    ) -> AssistPrediction:
        if self._endpoint is None:
            raise ValidationError("SAM 2 sidecar provider is not loaded")
        box_payload = _validated_box(box, width=prepared.width, height=prepared.height)
        response = _post_json(
            f"{self._endpoint}/segment-box",
            token=self._token,
            payload={
                "image_png_base64": prepared.image_png_base64,
                "box": box_payload,
                "device": self._device,
            },
            timeout_seconds=self._timeout_seconds,
        )
        self.provider_version = str(response.get("model_version", self.provider_version))
        return _mask_prediction(
            response,
            width=prepared.width,
            height=prepared.height,
        )

    def unload_model(self) -> None:
        self._endpoint = None
        self._token = None
        self._device = "auto"
