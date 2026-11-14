"""Portable inventory and integrity rules for the integrated 1.2 archive."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import ColumnElement, Table, select
from sqlalchemy.orm import Session

from reefvision.db.base import Base
from reefvision.db.models import Annotation, ImageAsset, MaskAnnotation
from reefvision.domain.errors import ValidationError
from reefvision.schemas.coral_graph import CorrespondenceSnapshot, GraphSnapshot, GrowthSnapshot
from reefvision.schemas.ecology_analysis import (
    ecology_analysis_source_ids,
    validate_ecology_analysis_snapshot,
)
from reefvision.schemas.ecology_pose_links import PoseLinkSource
from reefvision.services.annotations import annotation_snapshot, mask_annotation_snapshot
from reefvision.services.ecology_identity import EcologyIdentityService
from reefvision.services.project_exchange_pose import heldout_scope, validate_pose_rows
from reefvision.services.project_exchange_workflows import validate_workflow_rows
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.ecology_pose_links import remap_pose_link_source

FORMAT_VERSION = "1.2"

# Project-owned roots have no entry in _PARENTS. Child ownership is derived
# through a required database foreign key and never inferred from JSON.
SECTION_NAMES = (
    "ecology_identity_revisions",
    "ecology_identity_image_evidence",
    "ecology_identity_annotation_evidence",
    "ecology_identity_calibration_evidence",
    "pose_evaluation_runs",
    "pose_identity_association_runs",
    "pose_animal_identities",
    "pose_identity_observations",
    "pose_identity_association_decisions",
    "pose_identity_occlusions",
    "pose_identity_corrections",
    "pose_identity_truth_datasets",
    "pose_identity_evaluation_runs",
    "pose_measurement_runs",
    "pose_measurement_series",
    "pose_measurement_samples",
    "pose_event_detection_runs",
    "pose_biological_event_revisions",
    "reefpose_references",
    "reefpose_heldout_locks",
)
_NEW_SECTION_NAMES = (
    "coral_graph_revisions",
    "coral_branch_correspondence_revisions",
    "coral_growth_records",
    "ecology_pose_link_revisions",
    "ecology_analysis_records",
)
_PARENTS = {
    "pose_animal_identities": ("association_run_id", "pose_identity_association_runs"),
    "pose_identity_observations": ("association_run_id", "pose_identity_association_runs"),
    "pose_identity_association_decisions": ("association_run_id", "pose_identity_association_runs"),
    "pose_identity_occlusions": ("association_run_id", "pose_identity_association_runs"),
    "pose_identity_corrections": ("association_run_id", "pose_identity_association_runs"),
    "pose_identity_evaluation_runs": ("association_run_id", "pose_identity_association_runs"),
    "pose_measurement_series": ("measurement_run_id", "pose_measurement_runs"),
    "pose_measurement_samples": ("series_id", "pose_measurement_series"),
    "pose_event_detection_runs": ("measurement_run_id", "pose_measurement_runs"),
    "pose_biological_event_revisions": ("event_detection_run_id", "pose_event_detection_runs"),
}


def map_origin_ids(origin: dict[str, Any], mapping: dict[str, str]) -> dict[str, str]:
    previous = origin.get("id_map", {})
    return {
        **mapping,
        **{old: mapping[current] for old, current in previous.items() if current in mapping},
    }


def validate_origin(origin: Any) -> None:
    if origin is None:
        return
    if (
        not isinstance(origin, dict)
        or not _valid_digest(origin.get("manifest_sha256"))
        or not isinstance(origin.get("id_map"), dict)
        or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in origin["id_map"].items()
        )
    ):
        raise ValidationError("Archive source manifest mapping is invalid")


def integrated_models() -> dict[str, type[Base]]:
    by_table = {
        cast(Table, mapper.local_table).name: mapper.class_ for mapper in Base.registry.mappers
    }
    return {name: by_table[name] for name in (*SECTION_NAMES, *_NEW_SECTION_NAMES)}


def integrated_records(session: Session, project_id: str) -> dict[str, Sequence[Base]]:
    records: dict[str, Sequence[Base]] = {}
    ownership: dict[str, Any] = {}
    for name, model in integrated_models().items():
        table = cast(Table, model.__table__)
        owned: ColumnElement[bool]
        if (parent := _PARENTS.get(name)) is not None:
            key, parent_name = parent
            owned = table.c[key].in_(ownership[parent_name])
        else:
            owned = table.c.project_id == project_id
        ownership[name] = select(next(iter(table.primary_key))).where(owned)
        records[name] = list(session.scalars(select(model).where(owned)))
    return records


def has_integrated_records(session: Session, project_id: str) -> bool:
    return any(
        session.scalar(select(table.c.project_id).where(table.c.project_id == project_id).limit(1))
        for name, model in integrated_models().items()
        if name not in _PARENTS
        for table in (cast(Table, model.__table__),)
    )


def heldout_scope_mappings(
    source_project_id: str, project_id: str, sections: dict[str, list[dict[str, Any]]]
) -> dict[str, str]:
    remaining = {row["scope_sha256"] for row in sections.get("reefpose_heldout_locks", [])}
    if not remaining:
        return {}
    videos = {row["sha256"] for row in sections.get("videos", [])}
    checkpoints = {None, *(row["sha256"] for row in sections.get("models", []))}
    for row in sections.get("jobs", []):
        if row["job_type"] == "reefpose_validation" and row.get("result_json"):
            report = row["result_json"]
            videos.update(
                item["video_sha256"] for item in report["scored_reference_manifest"]["recordings"]
            )
            checkpoints.update(model["checkpoint_sha256"] for model in report["models"].values())
    mapping: dict[str, str] = {}
    for video in videos:
        for checkpoint in checkpoints:
            old = heldout_scope(source_project_id, video, checkpoint)
            if old in remaining:
                mapping[old] = heldout_scope(project_id, video, checkpoint)
                remaining.remove(old)
                if not remaining:
                    return mapping
    raise ValidationError("Exchange held-out lock scope has no available recording/model identity")


def parent_first(rows: list[dict[str, Any]], model: type[Any]) -> list[dict[str, Any]]:
    table = model.__table__
    self_fields = tuple(fk.parent.name for fk in table.foreign_keys if fk.column.table is table)
    if not self_fields:
        return rows
    key = next(iter(table.primary_key)).name
    by_id = {row[key]: row for row in rows}
    ordered: list[dict[str, Any]] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(row: dict[str, Any]) -> None:
        identifier = row[key]
        if identifier in visited:
            return
        if identifier in visiting:
            raise ValidationError(f"Cyclic exchange revision history in {table.name}")
        visiting.add(identifier)
        for field in self_fields:
            parent = by_id.get(row.get(field))
            if parent is not None:
                visit(parent)
        visiting.remove(identifier)
        visited.add(identifier)
        ordered.append(row)

    for row in rows:
        visit(row)
    return ordered


def validate_integrated_records(
    project_id: str,
    sections: dict[str, list[dict[str, Any]]],
    models: Mapping[str, type[Any]],
) -> None:
    by_section = {name: {row.get("id"): row for row in rows} for name, rows in sections.items()}
    images = by_section.get("images", {})
    observations = by_section.get("ecology_identity_image_evidence", {})
    annotations = by_section.get("ecology_identity_annotation_evidence", {})
    identities = {
        (row.get("organism_key"), row.get("revision"))
        for row in sections.get("ecology_identity_revisions", [])
    }
    for observation in observations.values():
        image = images.get(observation.get("image_id"))
        if (
            (observation.get("organism_key"), observation.get("identity_revision"))
            not in identities
            or not image
            or not _valid_digest(observation.get("image_sha256"))
            or (
                observation.get("source_metadata_sha256") is not None
                and not _valid_digest(observation["source_metadata_sha256"])
            )
        ):
            raise ValidationError("Ecological exchange image evidence has invalid provenance")
    for annotation in annotations.values():
        source_section = {"box": "annotations", "mask": "mask_annotations"}.get(
            annotation["annotation_kind"]
        )
        source = by_section.get(source_section or "", {}).get(annotation.get("annotation_id"))
        image_link = observations.get(annotation.get("image_evidence_id"))
        if (
            not source
            or not image_link
            or source.get("image_id") != image_link.get("image_id")
            or not _valid_digest(annotation.get("annotation_sha256"))
        ):
            raise ValidationError("Ecological exchange annotation has an unresolved source")
    for calibration in sections.get("ecology_identity_calibration_evidence", []):
        linked_annotation = annotations.get(calibration.get("annotation_evidence_id"))
        calibration_image = (
            observations.get(linked_annotation.get("image_evidence_id"))
            if linked_annotation
            else None
        )
        if (
            not calibration_image
            or calibration.get("image_id") != calibration_image["image_id"]
            or calibration.get("image_sha256") != calibration_image["image_sha256"]
            or _calibration_digest(calibration) != calibration.get("calibration_sha256")
        ):
            raise ValidationError("Ecological exchange calibration checksum or lineage is invalid")
    inventory = integrated_models()
    for name, rows in sections.items():
        if name in inventory:
            parent_first(rows, models[name])
    validate_pose_rows(sections)
    validate_workflow_rows(sections)
    heldout_scope_mappings(project_id, project_id, sections)
    ids = {key for rows in by_section.values() for key in rows if key is not None}
    for name in _NEW_SECTION_NAMES:
        for row in sections.get(name, []):
            mapped = row.get("source_id_map_json", {})
            expected = _snapshot_refs(name, row)
            if not isinstance(mapped, dict) or mapped.keys() - expected:
                raise ValidationError(f"Invalid exchange source ID map in {name}")
            if any(mapped.get(identifier, identifier) not in ids for identifier in expected):
                raise ValidationError(f"Unresolved exchange snapshot source in {name}")
            if name == "ecology_pose_link_revisions":
                remap_pose_link_source(
                    row["source_json"],
                    map_id=_pose_id_mapper(by_section, {}),
                    map_digest=lambda _, digest: digest,
                )
    _validate_coral_lineage(by_section)


def _pose_id_mapper(
    by_section: dict[str, dict[Any, dict[str, Any]]], mapping: dict[str, str]
) -> Callable[[str, str], str]:
    def mapped_id(section: str, identifier: str) -> str:
        if section in {"pose_identity_observation_series", "pose_biological_event_series"}:
            return mapping.get(identifier, identifier)
        if section == "pose_landmark_schemas" and identifier not in by_section.get(section, {}):
            # Built-in and legacy schema keys are opaque, project-independent strings.
            return identifier
        if identifier not in by_section.get(section, {}):
            raise ValidationError(f"Unresolved {section} link in organism pose snapshot")
        return mapping.get(identifier, identifier)

    return mapped_id


def _snapshot_refs(name: str, row: dict[str, Any]) -> set[str]:
    if name == "ecology_analysis_records":
        parsed = validate_ecology_analysis_snapshot(row["snapshot_json"], row["content_sha256"])
        if parsed.selection.kind != row["kind"]:
            raise ValidationError("Ecological analysis snapshot kind disagrees with its index")
        return ecology_analysis_source_ids(row["snapshot_json"])
    if name == "ecology_pose_link_revisions":
        value = row["source_json"]
        if canonical_json_sha256(value) != row["source_sha256"]:
            raise ValidationError("Ecology pose link checksum does not match")
        PoseLinkSource.model_validate(value)
        return set()

    value = row["payload_json"]
    if canonical_json_sha256(value) != row["content_sha256"]:
        raise ValidationError(f"Exchange checksum does not match {name}")
    if name == "coral_graph_revisions":
        graph = GraphSnapshot.model_validate(value)
        profile = graph.calibration.profile_source_image_id if graph.calibration else None
        return {graph.image_id, graph.mask_annotation_id, *([profile] if profile else [])}
    if name == "coral_branch_correspondence_revisions":
        CorrespondenceSnapshot.model_validate(value)
    if name == "coral_growth_records":
        GrowthSnapshot.model_validate(value)
    return set()


def _validate_coral_lineage(by_section: dict[str, dict[Any, dict[str, Any]]]) -> None:
    graphs = by_section.get("coral_graph_revisions", {})
    correspondences = by_section.get("coral_branch_correspondence_revisions", {})
    for graph in graphs.values():
        snapshot = graph["payload_json"]
        mapping = graph["source_id_map_json"]
        analysis = by_section.get("skeleton_analysis_revisions", {}).get(graph["analysis_id"])
        identity = by_section.get("ecology_identity_revisions", {}).get(
            graph["identity_revision_id"]
        )
        if (
            not analysis
            or not identity
            or snapshot["organism_key"] != identity["organism_key"]
            or mapping.get(snapshot["image_id"], snapshot["image_id"]) != analysis["image_id"]
            or mapping.get(snapshot["mask_annotation_id"], snapshot["mask_annotation_id"])
            != analysis["mask_annotation_id"]
            or snapshot["analysis_sha256"] != analysis["result_sha256"]
        ):
            raise ValidationError(
                "Reviewed coral graph source does not match the exchange snapshot"
            )
    for row in correspondences.values():
        snap = row["payload_json"]
        for side in ("earlier", "later"):
            graph = graphs[row[f"{side}_graph_revision_id"]]
            edges = {edge["id"] for edge in graph["payload_json"]["edges"]}
            linked = [edge for match in snap["matches"] for edge in match[f"{side}_branch_ids"]]
            if (
                graph["content_sha256"] != snap[f"{side}_graph_sha256"]
                or graph["decision"] != "accepted"
                or len(linked) != len(set(linked))
                or not set(linked) <= edges
            ):
                raise ValidationError(
                    "Coral correspondence does not match exchanged reviewed branches"
                )
    for row in by_section.get("coral_growth_records", {}).values():
        parent = correspondences[row["correspondence_revision_id"]]
        snap = row["payload_json"]
        if snap["correspondence_sha256"] != parent["content_sha256"] or any(
            snap[f"{side}_graph_sha256"] != parent["payload_json"][f"{side}_graph_sha256"]
            for side in ("earlier", "later")
        ):
            raise ValidationError("Coral growth result does not match exchanged correspondence")


def remap_reviewed_snapshot(
    name: str,
    row: dict[str, Any],
    values: dict[str, Any],
    by_section: dict[str, dict[Any, dict[str, Any]]],
    mapping: dict[str, str],
    digests: dict[str, str],
) -> None:
    if name == "ecology_pose_link_revisions":
        payload, digest = remap_pose_link_source(
            row["source_json"],
            map_id=_pose_id_mapper(by_section, mapping),
            map_digest=lambda _, digest: digests.get(digest, digest),
        )
        values["source_json"] = payload
        digests[row["source_sha256"]] = values["source_sha256"] = digest
    elif name in _NEW_SECTION_NAMES:
        keys = _snapshot_refs(name, row)
        previous = row["source_id_map_json"]
        values["source_id_map_json"] = {
            identifier: mapping[previous.get(identifier, identifier)] for identifier in keys
        }
        field = "snapshot_json" if name == "ecology_analysis_records" else "payload_json"
        values[field] = row[field]


def _valid_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _calibration_digest(row: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {
            "algorithm_version": "ecology-calibration-source-0001",
            "image_id": row["image_id"],
            "image_sha256": row["image_sha256"],
            "calibration": row["calibration_json"],
        }
    )


def _annotation_digest(row: Mapping[str, Any], kind: str) -> str:
    model = Annotation if kind == "box" else MaskAnnotation
    values = dict(row)
    if isinstance(values.get("deleted_at"), str):
        values["deleted_at"] = datetime.fromisoformat(values["deleted_at"])
    if model is Annotation:
        snapshot = annotation_snapshot(Annotation(**values))
    else:
        snapshot = mask_annotation_snapshot(MaskAnnotation(**values))
    return canonical_json_sha256(
        {"algorithm_version": "ecology-annotation-source-0001", "kind": kind, "snapshot": snapshot}
    )


def remap_ecology_evidence(
    session: Session,
    sections: dict[str, list[dict[str, Any]]],
    id_map: dict[str, str],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    """Rebind digests only where a matching old source snapshot is available."""
    result: dict[str, list[dict[str, Any]]] = {}
    digests: dict[str, str] = {}
    originals = {
        row["id"]: row
        for section in ("images", "annotations", "mask_annotations")
        for row in sections.get(section, [])
    }

    for name in (
        "ecology_identity_revisions",
        "ecology_identity_image_evidence",
        "ecology_identity_annotation_evidence",
        "ecology_identity_calibration_evidence",
    ):
        result[name] = []
        for row in sections.get(name, []):
            values = dict(row)
            for key in (
                "id",
                "project_id",
                "image_id",
                "image_evidence_id",
                "annotation_id",
                "annotation_evidence_id",
            ):
                if key in row:
                    values[key] = id_map[row[key]]
            if name == "ecology_identity_image_evidence":
                original = dict(originals[row["image_id"]])
                if isinstance(original.get("capture_timestamp"), str):
                    original["capture_timestamp"] = datetime.fromisoformat(
                        original["capture_timestamp"]
                    )
                source = ImageAsset(**original)
                target = session.get(ImageAsset, values["image_id"])
                frozen = row.get("source_metadata_sha256")
                if target is not None and frozen is not None:
                    replacement = None
                    if EcologyIdentityService._source_metadata_fingerprint(source) == frozen:
                        replacement = EcologyIdentityService._source_metadata_fingerprint(target)
                    elif EcologyIdentityService.frozen_explicit_capture_time(source, frozen):
                        explicit = EcologyIdentityService._explicit_capture_fingerprint(target)
                        if explicit is not None:
                            replacement = explicit[1]
                    if replacement is not None:
                        values["source_metadata_sha256"] = digests[frozen] = replacement
            elif name == "ecology_identity_annotation_evidence":
                kind = row["annotation_kind"]
                original = originals[row["annotation_id"]]
                original_digest = row["annotation_sha256"]
                if original_digest == _annotation_digest(original, kind):
                    model = Annotation if kind == "box" else MaskAnnotation
                    target_annotation = session.get(model, values["annotation_id"])
                    if isinstance(target_annotation, Annotation):
                        snapshot = annotation_snapshot(target_annotation)
                    elif isinstance(target_annotation, MaskAnnotation):
                        snapshot = mask_annotation_snapshot(target_annotation)
                    else:
                        raise ValidationError("Imported ecological annotation is missing")
                    digest = canonical_json_sha256(
                        {
                            "algorithm_version": "ecology-annotation-source-0001",
                            "kind": kind,
                            "snapshot": snapshot,
                        }
                    )
                    values["annotation_sha256"] = digests[original_digest] = digest
            elif name == "ecology_identity_calibration_evidence":
                calibration = dict(row["calibration_json"])
                profile = calibration.get("profile_source_image_id")
                if isinstance(profile, str) and profile in id_map:
                    calibration["profile_source_image_id"] = id_map[profile]
                values["calibration_json"] = calibration
                digest = _calibration_digest(values)
                values["calibration_sha256"] = digests[row["calibration_sha256"]] = digest
            result[name].append(values)
    return result, digests
