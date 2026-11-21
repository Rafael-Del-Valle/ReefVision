"""Preserve local field sources, history and replay across Project Exchange."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from uuid import UUID
from zipfile import ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.db.models.field_capture import (
    FieldCaptureBatch,
    FieldCaptureObservation,
    FieldCaptureReconciliationRecord,
    FieldCaptureReview,
)
from reefvision.domain.errors import ValidationError
from reefvision.schemas.field_capture import (
    MAX_FIELD_OBSERVATIONS,
    FieldCaptureBatchCreate,
    FieldCaptureEntry,
    FieldCaptureManifest,
    FieldCaptureReconciliation,
    FieldCaptureReviewResponse,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.field_capture import FieldCaptureStorage, field_media_kind
from reefvision.storage.projects import resolve_managed_project_path

FIELD_EXCHANGE_FORMAT = "1.5"
FIELD_EXCHANGE_FORMATS = {FIELD_EXCHANGE_FORMAT, "1.6", "1.7", "1.7.1", "1.8", "2.0"}
FIELD_MEDIA_KIND = "field_source"
FIELD_NODE = "field_capture_reconcile"
FIELD_DATA_TYPE = "field_capture_reconciliation"
FIELD_ORIGIN = "field_reconciliation_origin"
FIELD_SECTION_MODELS: dict[str, type[Base]] = {
    "field_capture_batches": FieldCaptureBatch,
    "field_capture_observations": FieldCaptureObservation,
    "field_capture_reconciliations": FieldCaptureReconciliationRecord,
    "field_capture_reviews": FieldCaptureReview,
}


def has_field_capture_batches(session: Session, project_id: str) -> bool:
    return (
        session.scalar(
            select(FieldCaptureBatch.id).where(FieldCaptureBatch.project_id == project_id).limit(1)
        )
        is not None
    )


def field_exchange_records(session: Session, project_id: str) -> dict[str, Sequence[Base]]:
    batches = select(FieldCaptureBatch.id).where(FieldCaptureBatch.project_id == project_id)
    records: dict[str, Sequence[Base]] = {
        "field_capture_batches": list(
            session.scalars(
                select(FieldCaptureBatch).where(FieldCaptureBatch.project_id == project_id)
            )
        ),
        "field_capture_observations": list(
            session.scalars(
                select(FieldCaptureObservation).where(
                    FieldCaptureObservation.project_id == project_id
                )
            )
        ),
        "field_capture_reconciliations": list(
            session.scalars(
                select(FieldCaptureReconciliationRecord).where(
                    FieldCaptureReconciliationRecord.batch_id.in_(batches)
                )
            )
        ),
        "field_capture_reviews": list(
            session.scalars(
                select(FieldCaptureReview).where(FieldCaptureReview.batch_id.in_(batches))
            )
        ),
    }
    return records if any(records.values()) else {}


def _field_source_path(storage_root: str, kind: str, sha256: str) -> str:
    return f"{storage_root}/field_capture/originals/{kind}/{sha256}"


def _field_source_member(sha256: str) -> str:
    return f"media/field/{sha256}"


def field_owned_project_path(relative_path: str) -> bool:
    parts = PurePosixPath(relative_path.replace("\\", "/")).parts
    return bool(parts) and parts[0].rstrip(" .").casefold() == "field_capture"


def contains_field_exchange_records(sections: Mapping[str, Sequence[dict[str, Any]]]) -> bool:
    return (
        any(sections.get(name) for name in FIELD_SECTION_MODELS)
        or any(
            row.get("data_type") == FIELD_DATA_TYPE
            for row in sections.get("workflow_artifacts", [])
        )
        or any(row.get("node_type") == FIELD_NODE for row in sections.get("workflow_node_runs", []))
        or any(
            isinstance(row.get("graph_json"), dict)
            and isinstance(row["graph_json"].get("nodes"), list)
            and any(
                isinstance(node, dict) and node.get("node_type") == FIELD_NODE
                for node in row["graph_json"]["nodes"]
            )
            for row in sections.get("workflow_graphs", [])
        )
    )


def gather_field_media(
    settings: Settings,
    storage_root: str,
    observations: Sequence[FieldCaptureObservation],
    existing_media: Sequence[Mapping[str, Any]],
) -> list[tuple[dict[str, object], Path | None]]:
    storage = FieldCaptureStorage(settings, storage_root)
    existing = {
        (item["kind"], item["sha256"], item["size_bytes"]): item["path"]
        for item in existing_media
        if item.get("kind") in {"image", "video"}
    }
    added: set[str] = set()
    output: list[tuple[dict[str, object], Path | None]] = []
    for row in sorted(observations, key=lambda item: item.id):
        if row.managed_path != _field_source_path(storage_root, row.kind, row.sha256):
            raise ValidationError("Field exchange source path is outside its owning project")
        if row.sha256 in added:
            continue
        source = storage.verify(row.managed_path, row.sha256, row.size_bytes)
        alias = existing.get((row.kind, row.sha256, row.size_bytes))
        descriptor: dict[str, object] = {
            "kind": FIELD_MEDIA_KIND,
            "record_id": row.id,
            "path": alias or _field_source_member(row.sha256),
            "sha256": row.sha256,
            "size_bytes": row.size_bytes,
        }
        output.append((descriptor, None if alias else source))
        added.add(row.sha256)
    return output


def _uuid(value: Any) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Invalid archived field UUID")
    return value


def _entry(row: Mapping[str, Any]) -> FieldCaptureEntry:
    result = FieldCaptureEntry.model_validate(
        {
            **{name: row[name] for name in FieldCaptureEntry.model_fields if name != "metadata"},
            "metadata": row["metadata_json"],
        }
    )
    if (
        field_media_kind(result.filename) != result.kind
        or result.metadata.model_dump(mode="json") != row["metadata_json"]
    ):
        raise ValueError("Field source record is not canonical")
    return result


def _report_digest(payload: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "report_sha256"}
    )


def _report_rows(
    project_id: str,
    sections: Mapping[str, Sequence[dict[str, Any]]],
    batches: Mapping[str, dict[str, Any]],
    observations: Mapping[str, tuple[dict[str, Any], FieldCaptureEntry]],
    ordered: Mapping[str, list[tuple[dict[str, Any], FieldCaptureEntry]]],
    media: Sequence[Mapping[str, Any]],
) -> dict[str, FieldCaptureReconciliation]:
    canonical = {
        (kind, row["id"]): row
        for section, kind in (("images", "image"), ("videos", "video"))
        for row in sections.get(section, [])
    }
    available = {(row["kind"], row["record_id"], row["sha256"]) for row in media}
    results: dict[str, FieldCaptureReconciliation] = {}
    for row in sections.get("field_capture_reconciliations", []):
        batch_id = _uuid(row["batch_id"])
        batch = batches[batch_id]
        report = FieldCaptureReconciliation.model_validate(row["report_json"])
        if (
            batch_id in results
            or str(report.project_id) != project_id
            or str(report.batch_id) != batch_id
            or report.manifest_sha256 != batch["manifest_sha256"]
            or row["report_sha256"] != report.report_sha256
            or _report_digest(row["report_json"]) != report.report_sha256
            or row["report_json"] != report.model_dump(mode="json")
            or [str(item.observation_id) for item in report.rows]
            != [item[0]["id"] for item in ordered[batch_id]]
        ):
            raise ValueError("Field reconciliation source, roster or receipt checksum differs")
        for item in report.rows:
            original, entry = observations[str(item.observation_id)]
            target = canonical[item.kind, str(item.asset_id)]
            if (
                (entry.sha256, entry.kind, entry.source_observation_id)
                != (item.sha256, item.kind, item.source_observation_id)
                or target["project_id"] != project_id
                or target["sha256"] != entry.sha256
                or bool(item.conflicts) != (item.outcome == "conflict")
            ):
                raise ValueError("Field reconciliation has an inconsistent project original")
            if (item.kind, str(item.asset_id), item.sha256) not in available:
                raise ValueError("Project Exchange is missing a reconciled field media asset")
            conflicts: set[str] = set()
            for conflict in item.conflicts:
                other_id = str(conflict.against_observation_id)
                other, evidence = observations[other_id]
                if (
                    other_id in conflicts
                    or other is original
                    or other["batch_id"] != str(conflict.against_batch_id)
                    or conflict.against != evidence
                ):
                    raise ValueError(
                        "Field conflict does not reference its original project evidence"
                    )
                conflicts.add(other_id)
        results[batch_id] = report
    return results


def _validate_field_workflows(
    sections: Mapping[str, Sequence[dict[str, Any]]],
    batches: Mapping[str, dict[str, Any]],
    receipts: Mapping[str, FieldCaptureReconciliation],
) -> None:
    def pins(parameters: dict[str, Any]) -> str:
        batch_id = _uuid(parameters["batch_id"])
        digest = batches[batch_id]["manifest_sha256"]
        if digest is None or digest != parameters["manifest_sha256"]:
            raise ValueError("Field workflow pins do not identify a sealed batch")
        return batch_id

    graphs: dict[str, dict[str, str]] = {}
    for graph in sections.get("workflow_graphs", []):
        graphs[graph["id"]] = {
            node["node_id"]: pins(node["parameters"])
            for node in graph["graph_json"]["nodes"]
            if node.get("node_type") == FIELD_NODE
        }
    runs = {row["id"]: row for row in sections.get("workflow_runs", [])}
    nodes = {row["id"]: row for row in sections.get("workflow_node_runs", [])}
    for artifact in sections.get("workflow_artifacts", []):
        if artifact.get("data_type") != FIELD_DATA_TYPE:
            continue
        producer = nodes[artifact["producer_node_run_id"]]
        run = runs[artifact["workflow_run_id"]]
        batch_id = pins(producer["parameters_json"])
        payload = artifact["payload_json"]
        if (
            producer["node_type"] != FIELD_NODE
            or producer["status"] != "succeeded"
            or producer["workflow_run_id"] != run["id"]
            or artifact["producer_port_id"] != "reconciliation"
            or graphs[run["workflow_graph_record_id"]].get(producer["node_id"]) != batch_id
            or payload != receipts[batch_id].model_dump(mode="json")
            or artifact["payload_sha256"] != canonical_json_sha256(payload)
        ):
            raise ValueError(
                "Field workflow artifact differs from its pinned reconciliation receipt"
            )


def validate_field_exchange(
    project_id: str,
    source_storage_root: str,
    sections: dict[str, list[dict[str, Any]]],
    media: Sequence[Mapping[str, Any]],
) -> None:
    """Validate ownership, media binding and receipts before a destination is created."""
    if not contains_field_exchange_records(sections) and not any(
        descriptor.get("kind") == FIELD_MEDIA_KIND for descriptor in media
    ):
        return
    try:
        path = PurePosixPath(source_storage_root)
        if (
            not path.parts
            or path.is_absolute()
            or PureWindowsPath(source_storage_root).drive
            or ".." in path.parts
            or path.as_posix() != source_storage_root
        ):
            raise ValueError("Field project storage root is invalid")
        batches: dict[str, dict[str, Any]] = {}
        sha_roster: set[str] = set()
        for row in sections.get("field_capture_batches", []):
            batch_id = _uuid(row["id"])
            _uuid(row["origin_project_id"])
            _uuid(row["origin_batch_id"])
            digest = row["manifest_sha256"]
            if (
                row["project_id"] != project_id
                or batch_id in batches
                or digest in sha_roster
                or FieldCaptureBatchCreate(label=row["label"]).label != row["label"]
            ):
                raise ValueError("Field batch has invalid source ownership or identity")
            if digest is not None:
                sha_roster.add(digest)
            batches[batch_id] = row
        observations: dict[str, tuple[dict[str, Any], FieldCaptureEntry]] = {}
        ordered: dict[str, list[tuple[dict[str, Any], FieldCaptureEntry]]] = {
            key: [] for key in batches
        }
        media_sources: dict[str, FieldCaptureEntry] = {}
        for row in sections.get("field_capture_observations", []):
            observation_id = _uuid(row["id"])
            entry = _entry(row)
            key = entry.metadata.observation_key
            if (
                row["project_id"] != project_id
                or observation_id in observations
                or row["managed_path"]
                != _field_source_path(source_storage_root, entry.kind, entry.sha256)
                or type(row["ordinal"]) is not int
                or row["claim_key"] != (key.casefold() if key else None)
            ):
                raise ValueError(
                    "Field observation has invalid project ownership, source path or key"
                )
            previous = media_sources.setdefault(entry.sha256, entry)
            if (previous.kind, previous.size_bytes) != (entry.kind, entry.size_bytes):
                raise ValueError("Field observations disagree about their original media")
            observations[observation_id] = (row, entry)
            ordered[row["batch_id"]].append((row, entry))
        for batch_id, captures in ordered.items():
            captures.sort(key=lambda item: item[0]["ordinal"])
            if (
                len(captures) > MAX_FIELD_OBSERVATIONS
                or [row["ordinal"] for row, _ in captures] != list(range(len(captures)))
                or len({entry.source_observation_id for _, entry in captures}) != len(captures)
            ):
                raise ValueError("Field batch observation order or source IDs are invalid")
            batch = batches[batch_id]
            if batch["manifest_sha256"] is not None:
                manifest = FieldCaptureManifest.model_validate(
                    {
                        **{
                            key: batch[key]
                            for key in ("origin_project_id", "origin_batch_id", "label")
                        },
                        "observations": [entry for _, entry in captures],
                    }
                )
                if (
                    canonical_json_sha256(manifest.model_dump(mode="json"))
                    != batch["manifest_sha256"]
                ):
                    raise ValueError("Sealed field batch source checksum differs")
        _validate_media_inventory(observations, media_sources, media)
        receipts = _report_rows(project_id, sections, batches, observations, ordered, media)
        _validate_reviews(sections, receipts)
        _validate_field_workflows(sections, batches, receipts)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError(f"Field exchange evidence is invalid: {exc}") from exc


def _validate_media_inventory(
    observations: Mapping[str, tuple[dict[str, Any], FieldCaptureEntry]],
    required: Mapping[str, FieldCaptureEntry],
    media: Sequence[Mapping[str, Any]],
) -> None:
    canonical = {
        (row["path"], row["kind"], row["sha256"], row["size_bytes"])
        for row in media
        if row.get("kind") in {"image", "video"}
    }
    found: set[str] = set()
    for descriptor in media:
        if descriptor.get("kind") != FIELD_MEDIA_KIND:
            continue
        _, source = observations[descriptor["record_id"]]
        digest = source.sha256
        path = descriptor["path"]
        if (
            digest in found
            or descriptor["sha256"] != digest
            or descriptor["size_bytes"] != source.size_bytes
            or (
                path != _field_source_member(digest)
                and (path, source.kind, digest, source.size_bytes) not in canonical
            )
        ):
            raise ValueError("Field exchange original has inconsistent media provenance")
        found.add(digest)
    if found != set(required):
        raise ValueError("Project Exchange is missing one or more field originals")


def _validate_reviews(
    sections: Mapping[str, Sequence[dict[str, Any]]],
    receipts: Mapping[str, FieldCaptureReconciliation],
) -> None:
    pairs: set[tuple[UUID, UUID]] = set()
    for row in sections.get("field_capture_reviews", []):
        parsed = FieldCaptureReviewResponse.model_validate(
            {key: row[key] for key in FieldCaptureReviewResponse.model_fields}
        )
        report = receipts[row["batch_id"]]
        pair = (parsed.observation_id, parsed.against_observation_id)
        if pair in pairs or not any(
            item.observation_id == parsed.observation_id
            and any(
                conflict.against_observation_id == parsed.against_observation_id
                for conflict in item.conflicts
            )
            for item in report.rows
        ):
            raise ValueError("Field review is not attached to its source conflict")
        pairs.add(pair)


def restore_field_media(
    archive: ZipFile,
    settings: Settings,
    storage_root: str,
    source_row: Mapping[str, Any],
    descriptors_by_sha: Mapping[str, Mapping[str, Any]],
) -> str:
    entry = _entry(source_row)
    relative = _field_source_path(storage_root, entry.kind, entry.sha256)
    storage = FieldCaptureStorage(settings, storage_root)
    if resolve_managed_project_path(settings, relative).exists():
        storage.verify(relative, entry.sha256, entry.size_bytes)
        return relative
    descriptor = descriptors_by_sha[entry.sha256]
    with storage.staging() as directory, archive.open(descriptor["path"]) as stream:
        path, digest, size = storage.stage_source(stream, entry.filename, entry.kind, directory)
        if (digest, size) != (entry.sha256, entry.size_bytes):
            raise ValidationError("Field original changed during archive restoration")
        return storage.preserve(path, entry)


def _report_references(payload: Mapping[str, Any]) -> set[str]:
    ids = {payload["project_id"], payload["batch_id"]}
    for row in payload["rows"]:
        ids.update((row["observation_id"], row["asset_id"]))
        for conflict in row["conflicts"]:
            ids.update((conflict["against_batch_id"], conflict["against_observation_id"]))
    return ids


def _remap_field_report(payload: Mapping[str, Any], id_map: Mapping[str, str]) -> dict[str, Any]:
    mapped = deepcopy(dict(payload))
    for key in ("project_id", "batch_id"):
        mapped[key] = id_map[mapped[key]]
    for row in mapped["rows"]:
        for key in ("observation_id", "asset_id"):
            row[key] = id_map[row[key]]
        for conflict in row["conflicts"]:
            for key in ("against_batch_id", "against_observation_id"):
                conflict[key] = id_map[conflict[key]]
    mapped["report_sha256"] = _report_digest(mapped)
    return mapped


def restore_field_row(
    section_name: str,
    source_row: dict[str, Any],
    values: dict[str, Any],
    id_map: Mapping[str, str],
) -> None:
    literals = {
        "field_capture_batches": ("origin_project_id", "origin_batch_id", "label"),
        "field_capture_observations": (
            "source_observation_id",
            "filename",
            "claim_key",
            "metadata_json",
        ),
        "field_capture_reviews": ("reviewer", "notes"),
    }
    for key in literals.get(section_name, ()):
        values[key] = deepcopy(source_row[key])
    if section_name == "field_capture_reconciliations":
        payload = _remap_field_report(source_row["report_json"], id_map)
        values["report_json"] = payload
        values["report_sha256"] = payload["report_sha256"]
    if section_name == "workflow_artifacts" and source_row.get("data_type") == FIELD_DATA_TYPE:
        values["payload_json"] = _remap_field_report(source_row["payload_json"], id_map)


def validate_field_origin(
    sections: Mapping[str, Sequence[dict[str, Any]]], origin: Any, archive_origin: Any
) -> None:
    if origin is None:
        return
    try:
        if not isinstance(origin, dict):
            raise ValueError("Field receipt origin must be an object")
        archive_aliases = archive_origin["id_map"] if isinstance(archive_origin, dict) else {}
        receipts = {
            row["batch_id"]: row for row in sections.get("field_capture_reconciliations", [])
        }
        for local_batch, record in origin.items():
            local = receipts[local_batch]["report_json"]
            source_to_local = record["source_to_local"]
            inverse = {_uuid(new): _uuid(old) for old, new in source_to_local.items()}
            if (
                set(inverse) != _report_references(local)
                or len(inverse) != len(source_to_local)
                or any(
                    archive_aliases.get(source) != here for source, here in source_to_local.items()
                )
                or record["local_report_sha256"] != local["report_sha256"]
                or record["source_batch_id"] != inverse[local_batch]
                or _remap_field_report(local, inverse)["report_sha256"]
                != record["source_report_sha256"]
            ):
                raise ValueError(
                    "Field reconciliation origin cannot reproduce its original receipt"
                )
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValidationError(f"Field exchange receipt origin is invalid: {exc}") from exc


def restore_field_origin(
    sections: Mapping[str, Sequence[dict[str, Any]]],
    archived_origin: Mapping[str, Any],
    id_map: Mapping[str, str],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for row in sections.get("field_capture_reconciliations", []):
        batch_id, original = row["batch_id"], row["report_json"]
        previous = archived_origin.get(batch_id)
        mappings = (
            previous["source_to_local"]
            if previous
            else {key: key for key in sorted(_report_references(original))}
        )
        local = _remap_field_report(original, id_map)
        result[id_map[batch_id]] = {
            "source_batch_id": previous["source_batch_id"] if previous else batch_id,
            "source_report_sha256": previous["source_report_sha256"]
            if previous
            else original["report_sha256"],
            "local_report_sha256": local["report_sha256"],
            "source_to_local": {source: id_map[current] for source, current in mappings.items()},
        }
    return result
