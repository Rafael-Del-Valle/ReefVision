"""Read-only integrity inspection for ReefVision exchange ZIP archives."""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections import Counter
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, BinaryIO

from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.domain.reproducibility_v15 import validate_native_proofs
from reefvision.schemas.project_exchange import (
    ProjectExchangeInspectionResponse,
    ProjectExchangeUnavailableAsset,
)
from reefvision.services.project_exchange_bioacoustics_v18 import (
    AUDIO_MEDIA_KIND,
    AUDIO_ORIGIN,
    audio_owned_project_path,
    validate_audio_exchange,
    validate_audio_origin,
)
from reefvision.services.project_exchange_field_v15 import (
    FIELD_EXCHANGE_FORMATS,
    FIELD_MEDIA_KIND,
    FIELD_ORIGIN,
    FIELD_SECTION_MODELS,
    contains_field_exchange_records,
    field_owned_project_path,
    validate_field_exchange,
    validate_field_origin,
)
from reefvision.services.project_exchange_monitoring_v17 import validate_monitoring_exchange
from reefvision.services.project_exchange_qc_v16 import QC_FORMATS, validate_qc_exchange
from reefvision.services.project_exchange_research_v18 import FORMAT as MULTIMODAL_FORMAT
from reefvision.services.project_exchange_research_v18 import (
    validate_research_format,
    validate_research_images,
)
from reefvision.services.project_exchange_schedules import validate_schedule_exchange
from reefvision.services.project_exchange_v15 import INTEGRATED_FORMATS, validate_v15_exchange
from reefvision.services.static_comparison import STATIC_COMPARISON_JOB
from reefvision.storage.datasets import canonical_json_sha256

FORMAT_NAME = "reefvision-project-exchange"
FORMAT_VERSION = "1.0"
MANIFEST_NAME = "reefvision-exchange-manifest.json"
MAX_ARCHIVE_FILES = 100_000
MAX_EXPANDED_BYTES = 100 * 1024**3


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name.replace("\\", "/"))
    return (
        bool(name)
        and not path.is_absolute()
        and not PureWindowsPath(name).drive
        and ".." not in path.parts
    )


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validate_file_inventory(
    *,
    archive: zipfile.ZipFile,
    name_set: set[str],
    descriptors: Any,
    label: str,
    require_source_relative_path: bool,
    require_integrity: bool,
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
        expected_sha = str(descriptor.get("sha256", ""))
        expected_size = descriptor.get("size_bytes")
        if require_integrity and (
            len(expected_sha) != 64
            or any(character not in "0123456789abcdef" for character in expected_sha)
            or type(expected_size) is not int
            or expected_size < 0
        ):
            errors.append(f"{label.title()} checksum or size is invalid: {member}")
            continue
        digest = hashlib.sha256()
        with archive.open(member) as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if expected_sha and digest.hexdigest() != expected_sha:
            errors.append(f"{label.title()} checksum failed: {member}")
        if expected_size is not None and archive.getinfo(member).file_size != int(expected_size):
            errors.append(f"{label.title()} size failed: {member}")
        valid.append(descriptor)
    return valid


def _integrated_media_gaps(
    sections: dict[str, list[dict[str, Any]]], media: list[dict[str, Any]]
) -> list[ProjectExchangeUnavailableAsset]:
    records = {
        (kind, row["id"]): row
        for name, kind in (
            ("images", "image"),
            ("videos", "video"),
            ("models", "model"),
            ("spatial_source_assets", "spatial_source"),
        )
        for row in sections.get(name, [])
    }
    seen: set[tuple[str, str]] = set()
    for descriptor in media:
        key = (descriptor["kind"], descriptor["record_id"])
        source = records.get(key)
        source_size = (
            source.get("file_size_bytes", source.get("size_bytes")) if source is not None else None
        )
        if (
            source is None
            or key in seen
            or source["sha256"] != descriptor.get("sha256")
            or (source_size is not None and source_size != descriptor.get("size_bytes"))
        ):
            raise ValidationError("Exchange media has duplicate or inconsistent source provenance")
        seen.add(key)
    return [
        ProjectExchangeUnavailableAsset(
            kind=kind,
            record_id=identifier,
            name=row.get("original_filename") or row.get("source_filename") or identifier,
            sha256=row["sha256"],
        )
        for (kind, identifier), row in records.items()
        if (kind, identifier) not in seen
    ]


def inspect_project_exchange(
    source: BinaryIO, *, verified_paired_comparison_ids: set[str] | None = None
) -> ProjectExchangeInspectionResponse:
    warnings: list[str] = []
    errors: list[str] = []
    section_counts: dict[str, int] = {}
    manifest: dict[str, Any] | None = None
    included_media_count = 0
    included_generated_artifact_count = 0
    unavailable_assets: list[ProjectExchangeUnavailableAsset] = []
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
            if version not in {"1.0", "1.1", *INTEGRATED_FORMATS}:
                errors.append("Unsupported exchange format version")

            excluded = manifest.get("excluded_record_groups", [])
            if isinstance(excluded, list) and all(isinstance(group, str) for group in excluded):
                warnings.extend(
                    f"Package excludes {group}. Use a backup for a full-fidelity copy."
                    for group in excluded
                )
            else:
                errors.append("Manifest excluded-record groups are invalid")

            sections = manifest.get("sections", {})
            if not isinstance(sections, dict):
                errors.append("Manifest sections are invalid")
                sections = {}
            section_rows: dict[str, list[dict[str, Any]]] = {}
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
                section_rows[name] = []
                for line_number, line in enumerate(lines, start=1):
                    try:
                        row = json.loads(line)
                        if not isinstance(row, dict):
                            raise ValueError
                        section_rows[name].append(row)
                    except ValueError:
                        errors.append(f"Section JSON is invalid: {name} line {line_number}")
                        break
            if not errors:
                from reefvision.services.project_exchange_paired_growth import (
                    validate_paired_growth_exchange,
                )
                from reefvision.services.project_exchange_spatial import (
                    validate_spatial_exchange_records,
                )

                project = manifest.get("project")
                project_id = project.get("id") if isinstance(project, dict) else None
                if not isinstance(project_id, str) or not project_id:
                    errors.append("Exchange archive source project ID is invalid")
                else:
                    try:
                        validate_research_format(
                            version, project_id, section_rows, manifest.get("origin")
                        )
                        validate_v15_exchange(
                            version, project_id, section_rows, manifest.get("origin")
                        )
                        validate_qc_exchange(version, project_id, section_rows)
                        validate_schedule_exchange(version, project_id, section_rows)
                        validate_spatial_exchange_records(project_id, section_rows)
                        validate_paired_growth_exchange(
                            project_id, section_rows, manifest.get("origin")
                        )
                        if version == "1.0" and manifest.get("origin") is not None:
                            from reefvision.services.project_exchange_integrated import (
                                validate_origin,
                            )
                            from reefvision.services.project_exchange_workflows import (
                                has_portable_workflow_history,
                            )

                            if has_portable_workflow_history(section_rows):
                                validate_origin(manifest["origin"])
                    except ValidationError as exc:
                        errors.append(str(exc))
            is_integrated = version in INTEGRATED_FORMATS
            source_project_rows = section_rows.get("project", [])
            if version not in FIELD_EXCHANGE_FORMATS and (
                set(section_rows).intersection(FIELD_SECTION_MODELS)
                or contains_field_exchange_records(section_rows)
                or FIELD_ORIGIN in manifest
            ):
                errors.append("Field records require the 1.5 exchange format")
            if is_integrated and not errors:
                from reefvision.services.project_exchange_import import SECTION_MODELS
                from reefvision.services.project_exchange_import_v1 import register_v1_sections
                from reefvision.services.project_exchange_integrated import (
                    integrated_models,
                    validate_integrated_records,
                    validate_origin,
                )
                from reefvision.services.project_exchange_scientific import (
                    validate_exchange_records,
                )

                register_v1_sections()
                integration = integrated_models()
                models = {**SECTION_MODELS, **integration}
                project_rows = section_rows.pop("project", [])
                project = manifest.get("project")
                if (
                    len(project_rows) != 1
                    or not isinstance(project, dict)
                    or not isinstance(project.get("id"), str)
                    or not project["id"]
                    or project_rows[0].get("id") != project["id"]
                ):
                    raise ValidationError("Exchange archive must identify one source project")
                if (
                    version not in QC_FORMATS
                    and not any(
                        section_rows.get(name) for name in (*integration, *FIELD_SECTION_MODELS)
                    )
                    and not any(
                        row.get("job_type") == STATIC_COMPARISON_JOB
                        for row in section_rows.get("jobs", [])
                    )
                ):
                    raise ValidationError(
                        "Exchange 1.2 archive has no integrated scientific records"
                        if version == "1.2"
                        else "Exchange 1.5 archive has no declared research records"
                    )
                validate_exchange_records(project["id"], section_rows, models)
                validate_integrated_records(project["id"], section_rows, models)
                validate_origin(manifest.get("origin"))

            if not errors:
                try:
                    validate_monitoring_exchange(
                        version, manifest["project"]["id"], section_rows, manifest.get("origin")
                    )
                except ValidationError as exc:
                    errors.append(str(exc))

            media = _validate_file_inventory(
                archive=archive,
                name_set=name_set,
                descriptors=manifest.get("media", []),
                label="media",
                require_source_relative_path=False,
                require_integrity=is_integrated,
                errors=errors,
            )
            included_media_count = len(media)
            if not errors:
                try:
                    ordinary_media = [
                        item
                        for item in media
                        if item.get("kind") not in {FIELD_MEDIA_KIND, AUDIO_MEDIA_KIND}
                    ]
                    if version not in FIELD_EXCHANGE_FORMATS and any(
                        item.get("kind") == FIELD_MEDIA_KIND for item in media
                    ):
                        raise ValidationError("Field originals require the 1.5 exchange format")
                    if version != MULTIMODAL_FORMAT and (
                        AUDIO_ORIGIN in manifest
                        or any(item.get("kind") == AUDIO_MEDIA_KIND for item in media)
                    ):
                        raise ValidationError("Bioacoustic originals require Project Exchange 1.8")
                    media_gaps = _integrated_media_gaps(section_rows, ordinary_media)
                    if version == MULTIMODAL_FORMAT:
                        validate_research_images(
                            manifest["project"]["id"], section_rows, manifest, archive
                        )
                        validate_audio_exchange(
                            str(manifest["project"]["id"]),
                            str(source_project_rows[0]["storage_root"]),
                            section_rows,
                            media,
                            archive,
                        )
                        validate_audio_origin(
                            section_rows, manifest.get(AUDIO_ORIGIN), manifest.get("origin")
                        )
                    if version in FIELD_EXCHANGE_FORMATS:
                        project_id = str(manifest["project"]["id"])
                        validate_field_exchange(
                            project_id,
                            str(source_project_rows[0]["storage_root"]),
                            section_rows,
                            media,
                        )
                        validate_field_origin(
                            section_rows, manifest.get(FIELD_ORIGIN), manifest.get("origin")
                        )
                except ValidationError as exc:
                    errors.append(str(exc))
                else:
                    if is_integrated:
                        unavailable_assets = media_gaps
                    missing_spatial = [item for item in media_gaps if item.kind == "spatial_source"]
                    if missing_spatial:
                        errors.append(
                            "Project Exchange is missing original media for one or more "
                            "spatial sources"
                        )
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
                require_integrity=is_integrated,
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
                require_integrity=is_integrated,
                errors=errors,
            )
            included_generated_artifact_count = len(generated)
            if version in FIELD_EXCHANGE_FORMATS and any(
                field_owned_project_path(str(item.get("source_relative_path", "")))
                for item in generated
            ):
                errors.append("Generated files cannot overwrite field originals or staging")
            if any(
                audio_owned_project_path(str(item.get("source_relative_path", "")))
                for item in generated
            ):
                errors.append("Generated files cannot overwrite audio originals or staging")
            if is_integrated and not errors:
                paths = [
                    str(item["source_relative_path"]).replace("\\", "/").casefold()
                    for item in generated
                ]
                if len(paths) != len(set(paths)) or any(
                    path.split("/", 1)[0] in {"exchanges", "exchange-import"} for path in paths
                ):
                    raise ValidationError("Exchange generated file destinations overlap")
            verified_comparisons: frozenset[str] = frozenset()
            if not errors and source_project_rows:
                from reefvision.services.project_exchange_paired_models_v15 import (
                    validate_paired_models_exchange,
                )
                from reefvision.storage.segmentation_metric_masks import MAX_MASK_PNG_BYTES

                source_record = source_project_rows[0]
                prefix = source_record["storage_root"].rstrip("/") + "/"
                raster_members = {row["source_relative_path"]: row["path"] for row in generated}

                def read_raster(path: str) -> bytes:
                    if not path.startswith(prefix) or path[len(prefix) :] not in raster_members:
                        raise NotFoundError("A required paired comparison raster is missing")
                    member = raster_members[path[len(prefix) :]]
                    with archive.open(member) as stream:
                        data = stream.read(MAX_MASK_PNG_BYTES + 1)
                    if len(data) > MAX_MASK_PNG_BYTES:
                        raise ValidationError("Paired raster is too large")
                    return data

                verified_comparisons = validate_paired_models_exchange(
                    source_record["id"],
                    section_rows,
                    (manifest.get("origin") or {}).get("id_map", {}),
                    read_raster=read_raster,
                )
                if version == MULTIMODAL_FORMAT:
                    from reefvision.services.project_exchange_domain_shift_v18 import (
                        validate_domain_shift_exchange,
                    )

                    validate_domain_shift_exchange(
                        source_record["id"],
                        section_rows,
                        (manifest.get("origin") or {}).get("id_map", {}),
                        read_raster=read_raster,
                    )
            if not errors:
                validate_native_proofs(
                    section_rows,
                    manifest,
                    verified_paired_comparison_ids=verified_comparisons,
                )
                if verified_paired_comparison_ids is not None:
                    verified_paired_comparison_ids.update(verified_comparisons)
    except (zipfile.BadZipFile, OSError, ValueError, TypeError, KeyError, ValidationError) as exc:
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
        unavailable_assets=unavailable_assets,
        warnings=warnings,
        errors=errors,
    )
