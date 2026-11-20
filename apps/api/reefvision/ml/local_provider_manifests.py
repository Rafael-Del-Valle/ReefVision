"""Inspect declarative local provider manifests without loading provider code."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from reefvision.config import Settings

MAX_LOCAL_PROVIDER_MANIFEST_BYTES = 64 * 1024

LocalProviderCapability = Literal[
    "image_detection",
    "image_instance_segmentation",
    "image_semantic_segmentation",
    "text_prompt_detection",
    "image_example_detection",
    "click_prompting",
    "box_prompting",
    "brush_prompting",
    "mask_prompting",
    "video_propagation",
    "multi_object_tracking",
    "training",
    "validation",
    "tiled_training",
    "tiled_inference",
    "export",
    "cpu_inference",
    "cuda_inference",
    "fp16",
    "quantized_inference",
    "packaged_desktop_operation",
]


class LocalProviderAvailabilityV1(BaseModel):
    """Availability declared by a manifest, not verified runtime readiness."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: Literal["available", "unavailable", "experimental", "retired"]
    reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def require_unavailable_reason(self) -> LocalProviderAvailabilityV1:
        if self.status in {"unavailable", "retired"} and self.reason is None:
            raise ValueError(f"availability reason is required when status is {self.status}")
        return self


class LocalProviderManifestV1(BaseModel):
    """Versioned inspect-only provider declaration.

    This schema intentionally contains no entrypoint, module, command, URL,
    dependency-install, checkpoint-load, or executable adapter field.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    manifest_version: Literal[1]
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    display_name: str = Field(min_length=1, max_length=120)
    provider_version: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=1000)
    capabilities: list[LocalProviderCapability] = Field(default_factory=list, max_length=32)
    supported_tasks: list[str] = Field(default_factory=list, max_length=32)
    availability: LocalProviderAvailabilityV1
    code_license: str = Field(min_length=1, max_length=200)
    weight_license: str = Field(min_length=1, max_length=200)
    notes: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("capabilities", "supported_tasks")
    @classmethod
    def require_unique_values(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("values must be unique")
        return value

    @field_validator("supported_tasks")
    @classmethod
    def validate_task_ids(cls, value: list[str]) -> list[str]:
        for task_id in value:
            if not task_id or len(task_id) > 64:
                raise ValueError("task IDs must contain between 1 and 64 characters")
            if not task_id[0].islower() or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in task_id
            ):
                raise ValueError("task IDs must use lowercase letters, digits, and underscores")
        return value

    @field_validator("notes")
    @classmethod
    def validate_notes(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("notes must be unique")
        if any(not note or len(note) > 500 for note in value):
            raise ValueError("notes must contain between 1 and 500 characters")
        return value


LocalProviderDiscoveryStatus = Literal[
    "valid",
    "invalid",
    "duplicate",
    "built_in_conflict",
]


@dataclass(frozen=True)
class LocalProviderManifestRecord:
    """One isolated inspection result, including failures."""

    record_id: str
    source_filename: str
    source_sha256: str | None
    discovery_status: LocalProviderDiscoveryStatus
    errors: tuple[str, ...]
    manifest: LocalProviderManifestV1 | None
    execution_allowed: Literal[False] = False


def _fallback_record_id(filename: str) -> str:
    digest = hashlib.sha256(filename.encode("utf-8")).hexdigest()
    return f"local_manifest_{digest[:16]}"


def _invalid_record(
    path: Path,
    *errors: str,
    source_sha256: str | None = None,
    status: LocalProviderDiscoveryStatus = "invalid",
) -> LocalProviderManifestRecord:
    return LocalProviderManifestRecord(
        record_id=_fallback_record_id(path.name),
        source_filename=path.name,
        source_sha256=source_sha256,
        discovery_status=status,
        errors=tuple(errors),
        manifest=None,
    )


def _validation_errors(error: ValidationError) -> tuple[str, ...]:
    messages: list[str] = []
    for item in error.errors(include_url=False):
        location = ".".join(str(part) for part in item["loc"]) or "manifest"
        messages.append(f"{location} {item['msg']}")
    return tuple(messages)


def _inspect_manifest_file(path: Path) -> LocalProviderManifestRecord:
    if path.is_symlink():
        return _invalid_record(path, "Manifest path is a symbolic link and was not followed")
    if not path.is_file():
        return _invalid_record(path, "Manifest path must be a regular file")
    try:
        size = path.stat().st_size
    except OSError as exc:
        return _invalid_record(path, f"Manifest metadata could not be read: {exc}")
    if size > MAX_LOCAL_PROVIDER_MANIFEST_BYTES:
        return _invalid_record(
            path,
            f"Manifest exceeds the {MAX_LOCAL_PROVIDER_MANIFEST_BYTES}-byte size limit",
        )
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return _invalid_record(path, f"Manifest could not be read: {exc}")
    digest = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return _invalid_record(path, "Manifest must be valid UTF-8", source_sha256=digest)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return _invalid_record(
            path,
            f"Manifest JSON is invalid at line {exc.lineno}, column {exc.colno}",
            source_sha256=digest,
        )
    try:
        manifest = LocalProviderManifestV1.model_validate(payload)
    except ValidationError as exc:
        return _invalid_record(path, *_validation_errors(exc), source_sha256=digest)
    return LocalProviderManifestRecord(
        record_id=manifest.provider_id,
        source_filename=path.name,
        source_sha256=digest,
        discovery_status="valid",
        errors=(),
        manifest=manifest,
    )


def discover_local_provider_manifests(
    settings: Settings,
    *,
    built_in_ids: set[str] | frozenset[str] = frozenset(),
) -> list[LocalProviderManifestRecord]:
    """Inspect manifests independently and never import or execute provider code."""

    directory = settings.resolved_data_dir / "provider-manifests"
    if not directory.is_dir():
        return []
    try:
        paths = sorted(
            (path for path in directory.iterdir() if path.suffix.lower() == ".json"),
            key=lambda path: path.name,
        )
    except OSError:
        return []

    records: list[LocalProviderManifestRecord] = []
    seen_ids: set[str] = set()
    for path in paths:
        record = _inspect_manifest_file(path)
        manifest = record.manifest
        if manifest is None:
            records.append(record)
            continue
        if manifest.provider_id in built_in_ids:
            records.append(
                _invalid_record(
                    path,
                    f"provider_id {manifest.provider_id!r} conflicts with a built-in provider",
                    source_sha256=record.source_sha256,
                    status="built_in_conflict",
                )
            )
            continue
        if manifest.provider_id in seen_ids:
            records.append(
                _invalid_record(
                    path,
                    f"provider_id {manifest.provider_id!r} duplicates an earlier local manifest",
                    source_sha256=record.source_sha256,
                    status="duplicate",
                )
            )
            continue
        seen_ids.add(manifest.provider_id)
        records.append(record)
    return records
