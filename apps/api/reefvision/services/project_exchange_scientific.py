"""Scientific archive validation and explicit linkage remapping, without rewriting evidence."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError as SchemaError

from reefvision.domain.errors import ValidationError
from reefvision.domain.scientific_units import normalize_quantity
from reefvision.schemas.scientific_data import ScientificRecordResponse
from reefvision.services.scientific_data import content_hash

SCIENCE_SECTIONS = {"scientific_records", "environmental_cache_entries"}
SUBJECT_SECTIONS = {
    "image_id": "images",
    "video_id": "videos",
    "track_id": "video_tracks",
    "annotation_id": "annotations",
    "mask_id": "mask_annotations",
    "prediction_id": "prediction_proposals",
    "model_run_id": "jobs",
}


def validate_exchange_records(
    project_id: str, sections: dict[str, list[dict[str, Any]]], models: dict[str, type[Any]]
) -> None:
    try:
        _validate_exchange_records(project_id, sections, models)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValidationError("Invalid scientific exchange inventory structure") from exc


def _validate_exchange_records(
    project_id: str, sections: dict[str, list[dict[str, Any]]], models: dict[str, type[Any]]
) -> None:
    """Reject ambiguous identifiers and references before creating an imported project."""
    seen = {project_id}
    by_section: dict[str, dict[str, dict[str, Any]]] = {}
    for name, rows in sections.items():
        if name not in models:
            if rows:
                raise ValidationError(f"Unsupported exchange section: {name}")
            continue
        by_section[name] = {}
        for row in rows:
            identifier = row.get("id")
            if not isinstance(identifier, str) or not identifier or identifier in seen:
                raise ValidationError(f"Missing or duplicate exchange identifier in {name}")
            seen.add(identifier)
            by_section[name][identifier] = row
            if "project_id" in row and row["project_id"] != project_id:
                raise ValidationError(f"Foreign project reference in {name}")
    scientific = by_section.get("scientific_records", {})
    caches = by_section.get("environmental_cache_entries", {})
    if not scientific and not caches:
        return
    # Every scalar FK in an enriched archive must resolve to a record in this archive.
    tables = {model.__table__.name: by_section.get(name, {}) for name, model in models.items()}
    tables["projects"] = {project_id: {"id": project_id}}
    for name, rows in sections.items():
        if name not in models:
            continue
        for column in models[name].__table__.columns:
            for fk in column.foreign_keys:
                for row in rows:
                    value = row.get(column.name)
                    if value is not None and value not in tables.get(fk.column.table.name, {}):
                        raise ValidationError(f"Unresolved {name}.{column.name} reference")
    cache_by_key = {}
    for cache in caches.values():
        key = cache.get("cache_key")
        if not isinstance(key, str) or len(key) != 64 or key in cache_by_key:
            raise ValidationError("Invalid or duplicate environmental cache key")
        cache_by_key[key] = cache
        payload = cache["payload_json"]
        if content_hash(payload) != cache["content_sha256"]:
            raise ValidationError("Environmental cache checksum mismatch")
        ids = payload.get("record_ids")
        if not isinstance(ids, list) or not ids or len(ids) != len(set(ids)):
            raise ValidationError("Invalid environmental cache record inventory")
        for identifier in ids:
            linked_record = scientific.get(identifier)
            if (
                linked_record is None
                or linked_record["payload_json"].get("environmental_cache_key") != key
            ):
                raise ValidationError("Environmental cache refers to missing or unrelated records")
        identity = payload.get("cache_identity")
        if identity is None:
            identity = {
                "source_url": cache["source_url"],
                "subject": scientific[ids[0]]["payload_json"]["subject"],
            }
        if not isinstance(identity, dict) or content_hash(identity) != key:
            raise ValidationError("Environmental cache identity does not match its key")
        if "subject" in identity and not isinstance(identity["subject"], dict):
            raise ValidationError("Environmental cache subject must be an object")
        for identifier in ids:
            if (
                "subject" in identity
                and scientific[identifier]["payload_json"]["subject"] != identity["subject"]
            ):
                raise ValidationError("Environmental cache subject does not match its records")
    for row in scientific.values():
        try:
            UUID(row["id"])
            payload = row["payload_json"]
            if content_hash(payload) != row["content_sha256"]:
                raise ValidationError("Scientific record checksum mismatch")
            record = ScientificRecordResponse.model_validate(
                {
                    **payload,
                    "id": row["id"],
                    "project_id": project_id,
                    "content_sha256": row["content_sha256"],
                }
            )
            expected_value, expected_unit = normalize_quantity(record.value, record.unit)
            expected_uncertainty = (
                normalize_quantity(record.uncertainty.value, record.unit, difference=True)[0]
                if record.uncertainty
                else None
            )
            if (record.normalized_value, record.normalized_unit, record.normalized_uncertainty) != (
                expected_value,
                expected_unit,
                expected_uncertainty,
            ):
                raise ValidationError(
                    "Scientific normalized quantity does not match original units"
                )
            calibration = payload.get("calibration_snapshot")
            if payload.get("calibration_sha256") != (
                content_hash(calibration) if calibration else None
            ):
                raise ValidationError("Scientific calibration checksum mismatch")
            for field in ("variable", "source_kind"):
                if row[field] != payload[field]:
                    raise ValidationError(f"Scientific {field} index does not match payload")
            timestamp = datetime.fromisoformat(row["observed_at"])
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)  # SQLite UTC column
            if timestamp != record.observed_at:
                raise ValidationError("Scientific timestamp index does not match payload")
            subject = record.subject.model_dump(mode="json")
            for field, section in SUBJECT_SECTIONS.items():
                identifier = subject.get(field)
                if (
                    field in ("image_id", "video_id", "track_id", "model_run_id")
                    and row.get(field) != identifier
                ):
                    raise ValidationError(f"Scientific {field} index does not match payload")
                if identifier is not None and identifier not in by_section.get(section, {}):
                    raise ValidationError(f"Unresolved scientific subject {field}")
            key = payload.get("environmental_cache_key")
            if key is not None and key not in cache_by_key:
                raise ValidationError("Scientific record refers to missing environmental cache")
        except (SchemaError, KeyError, TypeError, ValueError) as exc:
            raise ValidationError(f"Invalid scientific exchange record: {exc}") from exc


def remap_scientific_sections(
    sections: dict[str, list[dict[str, Any]]], id_map: dict[str, str]
) -> dict[str, list[dict[str, Any]]]:
    """Rewrite declared links only; raw provider responses and source provenance are evidence."""
    result = {name: deepcopy(sections.get(name, [])) for name in SCIENCE_SECTIONS}
    records = result["scientific_records"]
    keys: dict[str, str] = {}
    for cache in result["environmental_cache_entries"]:
        payload = cache["payload_json"]
        linked = [
            row
            for row in records
            if row["payload_json"].get("environmental_cache_key") == cache["cache_key"]
        ]
        # 0038 NOAA caches predate explicit identity metadata. Their identity is URL + subject.
        identity = deepcopy(payload.get("cache_identity"))
        if identity is None:
            identity = {
                "source_url": cache["source_url"],
                "subject": linked[0]["payload_json"]["subject"],
            }
        if "subject" in identity:
            identity["subject"] = {
                field: id_map.get(value, value) if isinstance(value, str) else value
                for field, value in identity["subject"].items()
            }
        key = content_hash(identity)
        keys[cache["cache_key"]] = key
        cache["cache_key"] = key
        payload["cache_identity"] = identity
        payload["record_ids"] = [id_map[value] for value in payload["record_ids"]]
        cache["content_sha256"] = content_hash(payload)
    for row in records:
        payload = row["payload_json"]
        payload["subject"] = {
            field: id_map.get(value, value)
            if field in SUBJECT_SECTIONS and isinstance(value, str)
            else value
            for field, value in payload["subject"].items()
        }
        if payload.get("environmental_cache_key") is not None:
            payload["environmental_cache_key"] = keys[payload["environmental_cache_key"]]
        row["content_sha256"] = content_hash(payload)
    return result
