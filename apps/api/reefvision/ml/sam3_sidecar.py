"""SAM 3 segmentation provider backed by an isolated localhost sidecar."""

from __future__ import annotations

import base64
import binascii
import json
import os
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request

from PIL import Image, UnidentifiedImageError

from reefvision.domain.errors import ValidationError
from reefvision.ml.providers import DetectionSettings, PixelBox
from reefvision.ml.segmentation import SegmentationPrediction

_PROVIDER_NAME = "sam3_sidecar"
_DESCRIPTOR_SCHEMA = "reefvision-sam3-sidecar-v1"
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _validated_endpoint(value: object) -> str:
    endpoint = str(value or "").strip().rstrip("/")
    parsed = url_parse.urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"}:
        raise ValidationError("SAM 3 sidecar endpoint must use http or https")
    if parsed.hostname is None or parsed.hostname.casefold() not in _LOOPBACK_HOSTS:
        raise ValidationError("SAM 3 sidecar endpoint must remain on localhost")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValidationError("SAM 3 sidecar endpoint may not contain credentials or query data")
    return endpoint


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
        raise ValidationError(f"SAM 3 sidecar returned HTTP {exc.code}: {body}") from exc
    except (url_error.URLError, TimeoutError, OSError) as exc:
        raise ValidationError(f"SAM 3 sidecar request failed: {exc}") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError("SAM 3 sidecar returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValidationError("SAM 3 sidecar returned an unexpected response")
    return parsed


def _source_png(image_path: Path) -> tuple[bytes, int, int]:
    try:
        with Image.open(image_path) as source:
            source.load()
            rgb = source.convert("RGB")
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError("Could not read the image for SAM 3 inference") from exc
    stream = BytesIO()
    rgb.save(stream, format="PNG", optimize=True)
    return stream.getvalue(), rgb.width, rgb.height


def _normalized_mask(
    encoded: object,
    *,
    width: int,
    height: int,
) -> tuple[bytes, tuple[int, int, int, int]]:
    if not isinstance(encoded, str) or not encoded:
        raise ValidationError("SAM 3 sidecar instance is missing a mask")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValidationError("SAM 3 sidecar mask is not valid base64") from exc
    try:
        with Image.open(BytesIO(raw)) as source:
            source.load()
            if source.size != (width, height):
                raise ValidationError("SAM 3 sidecar mask dimensions do not match the source image")
            binary = source.convert("L").point(lambda value: 255 if value else 0)
            bounds = binary.getbbox()
            if bounds is None:
                raise ValidationError("SAM 3 sidecar returned an empty mask")
            stream = BytesIO()
            binary.save(stream, format="PNG", optimize=True)
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError("SAM 3 sidecar mask is not a readable PNG") from exc
    return stream.getvalue(), bounds


class Sam3SidecarSegmentationProvider:
    """Use SAM 3 in a separate Python/CUDA environment over loopback HTTP."""

    provider_name = _PROVIDER_NAME

    def __init__(self) -> None:
        self.provider_version = "unknown"
        self._endpoint: str | None = None
        self._concept_prompt: str | None = None
        self._output_label: str | None = None
        self._score_threshold = 0.35
        self._timeout_seconds = 120.0
        self._token: str | None = None

    def load_model(self, model_path: Path, device: str) -> None:
        if not model_path.is_file() or model_path.suffix.casefold() != ".json":
            raise ValidationError("SAM 3 sidecar registration descriptor is missing")
        try:
            descriptor = json.loads(model_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("SAM 3 sidecar descriptor is not valid JSON") from exc
        if not isinstance(descriptor, dict) or descriptor.get("schema") != _DESCRIPTOR_SCHEMA:
            raise ValidationError("SAM 3 sidecar descriptor schema is unsupported")
        prompt = str(descriptor.get("concept_prompt", "")).strip()
        output_label = str(descriptor.get("output_label", prompt)).strip()
        if not prompt or not output_label:
            raise ValidationError("SAM 3 sidecar descriptor is missing its concept prompt")
        token_env = str(descriptor.get("token_env", "REEFVISION_SAM3_SIDECAR_TOKEN")).strip()
        if not token_env or not token_env.replace("_", "").isalnum():
            raise ValidationError("SAM 3 sidecar token environment name is invalid")
        try:
            score_threshold = float(descriptor.get("score_threshold", 0.35))
            timeout_seconds = float(descriptor.get("timeout_seconds", 120.0))
        except (TypeError, ValueError) as exc:
            raise ValidationError("SAM 3 sidecar descriptor thresholds are invalid") from exc
        if not 0 <= score_threshold <= 1:
            raise ValidationError("SAM 3 sidecar score threshold must be between 0 and 1")
        if not 1 <= timeout_seconds <= 600:
            raise ValidationError("SAM 3 sidecar timeout must be between 1 and 600 seconds")
        self._endpoint = _validated_endpoint(descriptor.get("endpoint"))
        self._concept_prompt = prompt
        self._output_label = output_label
        self._score_threshold = score_threshold
        self._timeout_seconds = timeout_seconds
        self._token = os.environ.get(token_env)
        self.provider_version = str(descriptor.get("sam3_version", "sam3"))

    def predict(
        self,
        image_path: Path,
        settings: DetectionSettings,
    ) -> list[SegmentationPrediction]:
        if self._endpoint is None or self._concept_prompt is None or self._output_label is None:
            raise ValidationError("SAM 3 sidecar provider is not loaded")
        source_png, width, height = _source_png(image_path)
        threshold = max(self._score_threshold, settings.confidence_threshold)
        response = _post_json(
            f"{self._endpoint}/segment",
            token=self._token,
            payload={
                "image_png_base64": base64.b64encode(source_png).decode("ascii"),
                "prompt": self._concept_prompt,
                "score_threshold": threshold,
                "device": settings.device,
            },
            timeout_seconds=self._timeout_seconds,
        )
        instances = response.get("instances")
        if not isinstance(instances, list):
            raise ValidationError("SAM 3 sidecar response has no instance list")
        self.provider_version = str(response.get("model_version", self.provider_version))
        predictions: list[SegmentationPrediction] = []
        for raw_instance in instances:
            if not isinstance(raw_instance, dict):
                continue
            try:
                score = float(raw_instance.get("score"))
            except (TypeError, ValueError):
                continue
            if not 0 <= score <= 1 or score < threshold:
                continue
            mask_png, mask_bounds = _normalized_mask(
                raw_instance.get("mask_png_base64"),
                width=width,
                height=height,
            )
            left, top, right, bottom = mask_bounds
            box = PixelBox(
                x_min=float(left),
                y_min=float(top),
                x_max=float(right),
                y_max=float(bottom),
            )
            predictions.append(
                SegmentationPrediction(
                    label=self._output_label,
                    class_index=0,
                    confidence=score,
                    box=box,
                    polygon=None,
                    mask_png_bytes=mask_png,
                )
            )
        return predictions

    def unload_model(self) -> None:
        self._endpoint = None
        self._concept_prompt = None
        self._output_label = None
        self._token = None
