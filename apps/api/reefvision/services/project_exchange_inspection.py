"""Read-only integrity inspection for ReefVision exchange ZIP archives."""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections import Counter
from pathlib import PurePosixPath
from typing import Any, BinaryIO

from reefvision.schemas.project_exchange import ProjectExchangeInspectionResponse
from reefvision.storage.datasets import canonical_json_sha256

FORMAT_NAME = "reefvision-project-exchange"
FORMAT_VERSION = "1.0"
MANIFEST_NAME = "reefvision-exchange-manifest.json"
MAX_ARCHIVE_FILES = 100_000
MAX_EXPANDED_BYTES = 100 * 1024**3


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name.replace("\\", "/"))
    return bool(name) and not path.is_absolute() and ".." not in path.parts


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validate_file_inventory(
    *,
    archive: zipfile.ZipFile,
    name_set: set[str],
    descriptors: Any,
    label: str,
    require_source_relative_path: bool,
    errors: list[str],
) -> list[dict[str, Any]]:
    if not isinstance(descriptors, list):
        errors.append(f"Manifest {label} inventory is invalid")
        return []
    valid: list[dict[str, Any]] = []
    for index, descriptor_value in enumerate(descriptors):
        if not isinstance(descriptor_value, dict):
            errors.append(f"{label.title()} descriptor is invalid: {index}")
            continue
        descriptor = descriptor_value
        member = str(descriptor.get("path", ""))
        if not _safe_member(member):
            errors.append(f"{label.title()} path is unsafe: {member or index}")
            continue
        if require_source_relative_path:
            source_relative_path = str(descriptor.get("source_relative_path", ""))
            if not _safe_member(source_relative_path):
                errors.append(
                    f"Generated artifact restore path is unsafe: {source_relative_path or index}"
                )
                continue
        if member not in name_set:
            errors.append(f"{label.title()} file is missing: {member or index}")
            continue
        payload = archive.read(member)
        expected_sha = str(descriptor.get("sha256", ""))
        if expected_sha and _sha256(payload) != expected_sha:
            errors.append(f"{label.title()} checksum failed: {member}")
        expected_size = descriptor.get("size_bytes")
        if expected_size is not None and len(payload) != int(expected_size):
            errors.append(f"{label.title()} size failed: {member}")
        valid.append(descriptor)
    return valid


def inspect_project_exchange(source: BinaryIO) -> ProjectExchangeInspectionResponse:
    warnings: list[str] = []
    errors: list[str] = []
    section_counts: dict[str, int] = {}
    manifest: dict[str, Any] | None = None
    included_media_count = 0
    included_generated_artifact_count = 0
    try:
        source.seek(0)
        with zipfile.ZipFile(source, "r") as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
            if len(infos) > MAX_ARCHIVE_FILES:
                errors.append("Archive contains too many files")
            if sum(item.file_size for item in infos) > MAX_EXPANDED_BYTES:
                errors.append("Archive expands beyond the 100 GB inspection limit")
            if duplicates:
                errors.append("Archive contains duplicate member names")
            if any(not _safe_member(name) for name in names):
                errors.append("Archive contains unsafe paths")
            name_set = set(names)
            if MANIFEST_NAME not in name_set:
                errors.append("ReefVision exchange manifest is missing")
            if errors:
                return ProjectExchangeInspectionResponse(
                    compatible=False,
                    format_name=None,
                    format_version=None,
                    application_version=None,
                    manifest_sha256=None,
                    project_name=None,
                    section_counts={},
                    included_media_count=0,
                    included_generated_artifact_count=0,
                    warnings=warnings,
                    errors=errors,
                )

            manifest_value = json.loads(archive.read(MANIFEST_NAME))
            if not isinstance(manifest_value, dict):
                errors.append("Exchange manifest must be a JSON object")
                manifest_value = {}
            manifest = manifest_value
            if manifest.get("format_name") != FORMAT_NAME:
                errors.append("Archive is not a ReefVision project exchange package")
            version = str(manifest.get("format_version", ""))
            if version not in {"1.0", "1.1"}:
                errors.append("Unsupported exchange format version")

            sections = manifest.get("sections", {})
            if not isinstance(sections, dict):
                errors.append("Manifest sections are invalid")
                sections = {}
            for name, descriptor_value in sections.items():
                if not isinstance(descriptor_value, dict):
                    errors.append(f"Section descriptor is invalid: {name}")
                    continue
                member = str(descriptor_value.get("path", ""))
                if member not in name_set:
                    errors.append(f"Section file is missing: {name}")
                    continue
                payload = archive.read(member)
                if _sha256(payload) != descriptor_value.get("sha256"):
                    errors.append(f"Section checksum failed: {name}")
                lines = [line for line in payload.splitlines() if line.strip()]
                section_counts[str(name)] = len(lines)
                if len(lines) != int(descriptor_value.get("count", -1)):
                    errors.append(f"Section row count failed: {name}")
                for line_number, line in enumerate(lines, start=1):
                    try:
                        json.loads(line)
                    except json.JSONDecodeError:
                        errors.append(f"Section JSON is invalid: {name} line {line_number}")
                        break

            media = _validate_file_inventory(
                archive=archive,
                name_set=name_set,
                descriptors=manifest.get("media", []),
                label="media",
                require_source_relative_path=False,
                errors=errors,
            )
            included_media_count = len(media)
            if not media:
                warnings.append(
                    "Package does not include original media; imported records may require "
                    "relinking files"
                )

            telemetry_sidecars = _validate_file_inventory(
                archive=archive,
                name_set=name_set,
                descriptors=manifest.get(
                    "telemetry_sidecars",
                    [],
                ),
                label="telemetry sidecar",
                require_source_relative_path=True,
                errors=errors,
            )

            for index, descriptor in enumerate(telemetry_sidecars):
                metadata_key = descriptor.get("metadata_key")

                if metadata_key not in {
                    "telemetry",
                    "airdata_telemetry",
                }:
                    errors.append(f"Telemetry sidecar metadata key is invalid: {index}")

                source_path = descriptor.get("source_path")

                if (
                    not isinstance(
                        source_path,
                        str,
                    )
                    or not source_path.strip()
                ):
                    errors.append(f"Telemetry sidecar source path is invalid: {index}")

            generated = _validate_file_inventory(
                archive=archive,
                name_set=name_set,
                descriptors=manifest.get("generated_artifacts", []),
                label="generated artifact",
                require_source_relative_path=True,
                errors=errors,
            )
            included_generated_artifact_count = len(generated)
    except (zipfile.BadZipFile, json.JSONDecodeError, OSError, ValueError) as exc:
        errors.append(f"Archive could not be inspected: {exc}")

    project_value = manifest.get("project") if manifest else None
    return ProjectExchangeInspectionResponse(
        compatible=not errors,
        format_name=str(manifest.get("format_name")) if manifest else None,
        format_version=str(manifest.get("format_version")) if manifest else None,
        application_version=str(manifest.get("application_version")) if manifest else None,
        manifest_sha256=canonical_json_sha256(manifest) if manifest else None,
        project_name=(str(project_value.get("name")) if isinstance(project_value, dict) else None),
        section_counts=section_counts,
        included_media_count=included_media_count,
        included_generated_artifact_count=included_generated_artifact_count,
        warnings=warnings,
        errors=errors,
    )
