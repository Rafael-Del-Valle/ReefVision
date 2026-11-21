"""Validate archived paired model evidence and rebuild only its live Exchange links."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from reefvision.db.base import Base
from reefvision.db.models import (
    DatasetVersion,
    DatasetVersionItem,
    Job,
    ModelRegistration,
    PredictionProposal,
    Project,
    TrainingRun,
)
from reefvision.domain.errors import NotFoundError, ReefVisionError, ValidationError
from reefvision.schemas.model_runtime import RuntimeReceipt
from reefvision.schemas.paired_models_v15 import ComparisonEvidence, ComparisonRequest
from reefvision.services.model_comparison_stills_v15 import (
    RecordedImageRuns,
    UnverifiedLegacyInference,
    compare_image_models,
)
from reefvision.services.model_comparison_video_v15 import compare_video_models
from reefvision.services.paired_models_v15 import JOB_TYPE, summarize_groups
from reefvision.services.project_exchange_models import has_local_model_lineage
from reefvision.storage.datasets import canonical_json_sha256

ARTIFACT_TYPE = "paired_model_report"
IMAGE_TASKS = {"detector", "mask"}
TABLES = {
    "images": "images",
    "models": "model_registrations",
    "dataset_versions": "dataset_versions",
    "dataset_version_items": "dataset_version_items",
    "training_runs": "training_runs",
    "jobs": "jobs",
    "prediction_proposals": "prediction_proposals",
    "videos": "videos",
    "reefpose_references": "reefpose_references",
    "pose_identity_association_runs": "pose_identity_association_runs",
    "pose_identity_observations": "pose_identity_observations",
    "pose_training_datasets": "pose_training_datasets",
    "pose_training_dataset_items": "pose_training_dataset_items",
}
Row = dict[str, Any]
Sections = dict[str, list[Row]]
RasterReader = Callable[[str], bytes]


def _completed(sections: Sections) -> list[Row]:
    return [
        row
        for row in sections.get("jobs", [])
        if row.get("job_type") == JOB_TYPE and row["status"] == "succeeded"
    ]


def _sources(snapshot: Row) -> set[str]:
    evidence = snapshot["evidence"]
    selection = snapshot["selection"]
    ids = {
        snapshot["project_id"],
        snapshot["comparison_id"],
        evidence["reference_id"],
        selection["left"]["id"],
        selection["right"]["id"],
        *(model["model_id"] for model in snapshot["models"]),
        *(source["id"] for source in selection["sources"]),
        *(row for row in evidence.get("inference_job_ids", [])),
        *(obs["media_id"] for group in evidence["groups"] for obs in group["observations"]),
    }
    for lineage in evidence.get("lineage", []):
        ids.update(lineage.get("training_run_ids", []))
        ids.update(lineage.get("model_selection_job_ids", []))
        ids.update(lineage.get("checkpoint_dependencies", {}))
        ids.update(row["id"] for row in lineage.get("datasets", []))
    if selection["task"] in IMAGE_TASKS and not evidence.get("inference_job_ids"):
        # The original algorithm hashed a project class UUID in each prediction.
        for model in snapshot["models"]:
            receipt = model["receipt"]
            if receipt["source_project_id"] == snapshot["project_id"]:
                ids.update(value for value in receipt["class_mapping"].values() if value)
    return ids


def _local(identifier: str, mapping: Mapping[str, str]) -> str:
    return mapping.get(identifier, identifier)


def _add_raster(paths: dict[str, str], row: Row) -> None:
    if row.get("geometry_kind") != "raster_mask":
        return
    path, digest = row.get("mask_path"), row.get("mask_content_sha256")
    if (
        not isinstance(path, str)
        or not isinstance(digest, str)
        or len(digest) != 64
        or paths.setdefault(path, digest) != digest
    ):
        raise ValidationError("Paired model raster path and checksum must be uniquely declared")


def paired_comparison_raster_paths(
    sections: Sections,
    *,
    include_legacy: bool = True,
) -> dict[str, str]:
    """Return project-relative managed paths required to verify archived raster scores."""
    paths: dict[str, str] = {}
    for job in _completed(sections):
        result = job["result_json"]
        snapshot, mapping = result["snapshot"], result["source_id_map"]
        if snapshot["selection"]["task"] != "mask":
            continue
        evidence = snapshot["evidence"]
        dataset = _local(evidence["reference_id"], mapping)
        child_ids = {
            _local(identifier, mapping) for identifier in evidence.get("inference_job_ids", [])
        }
        if not child_ids:
            if not include_legacy:
                continue
            request = job["request_json"]
            selection_ids = {request["left"]["id"], request["right"]["id"]}
            child_ids = {
                row["id"]
                for row in sections.get("jobs", [])
                if row.get("job_type") == "inference"
                and row.get("project_id") == job["project_id"]
                and row.get("status") == "succeeded"
                and row["request_json"].get("evaluation_only") is True
                and row["request_json"].get("runtime_selection_id") in selection_ids
                and row.get("completed_at")
                and row["completed_at"] <= job["completed_at"]
                and (not job.get("started_at") or row["created_at"] >= job["started_at"])
            }
        for item in sections.get("dataset_version_items", []):
            if (
                item["dataset_version_id"] == dataset
                and item["split"] == "test"
                and item["image_annotation_status"] == "reviewed"
            ):
                for mask in item["mask_annotation_snapshot_json"]:
                    _add_raster(paths, mask)
        for proposal in sections.get("prediction_proposals", []):
            if proposal["inference_job_id"] in child_ids:
                _add_raster(paths, proposal)
    return paths


@contextmanager
def _archive_session(sections: Sections) -> Iterator[Session]:
    """Load only the scoped evidence tables into SQLite memory, with no project writes."""
    engine = create_engine("sqlite://")
    tables = {name: Base.metadata.tables[table] for name, table in TABLES.items()}
    try:
        Base.metadata.create_all(engine, tables=list(tables.values()))
        with Session(engine) as session:
            for name, table in tables.items():
                for row in sections.get(name, []):
                    values = {
                        column.name: (
                            datetime.fromisoformat(row[column.name])
                            if isinstance(column.type, DateTime)
                            and isinstance(row[column.name], str)
                            else row[column.name]
                        )
                        for column in table.columns
                        if column.name in row
                    }
                    session.execute(table.insert().values(**values))
            yield session
    finally:
        engine.dispose()


def _groups(evidence: Row, mapping: Mapping[str, str]) -> dict[str, list[str]]:
    return {
        row["group_id"]: sorted(
            canonical_json_sha256({**obs, "media_id": _local(obs["media_id"], mapping)})
            for obs in row["observations"]
        )
        for row in evidence["groups"]
    }


def _lineage(evidence: Row, mapping: Mapping[str, str], *, include_digests: bool) -> dict[str, Any]:
    return {
        _local(row["model_id"], mapping): {
            "status": row["status"],
            "training_run_ids": sorted(
                _local(identifier, mapping) for identifier in row["training_run_ids"]
            ),
            "model_selection_job_ids": sorted(
                _local(identifier, mapping) for identifier in row["model_selection_job_ids"]
            ),
            "checkpoint_dependencies": {
                _local(key, mapping): value for key, value in row["checkpoint_dependencies"].items()
            },
            "datasets": sorted(
                (
                    _local(item["id"], mapping),
                    sorted(item["splits"]),
                    item["manifest_sha256"] if include_digests else "",
                )
                for item in row["datasets"]
            ),
            "overlapping_image_ids": sorted(
                _local(identifier, mapping) for identifier in row["overlapping_image_ids"]
            ),
        }
        for row in evidence["lineage"]
    }


def _validate_record(
    session: Session,
    job: Row,
    sections: Sections,
    project_id: str,
    origin_map: Mapping[str, str],
    read_raster: RasterReader,
) -> bool:
    result = job["result_json"]
    snapshot, mapping = result["snapshot"], result["source_id_map"]
    source = ComparisonRequest.model_validate(snapshot["selection"])
    current = ComparisonRequest.model_validate(job["request_json"])
    evidence = ComparisonEvidence.model_validate(snapshot["evidence"]).model_dump(mode="json")
    refs = _sources(snapshot)
    if (
        snapshot["schema_version"] != "paired-model-comparison-1.5"
        or canonical_json_sha256(snapshot) != result["content_sha256"]
        or job["project_id"] != project_id
        or _local(snapshot["project_id"], mapping) != project_id
        or _local(snapshot["comparison_id"], mapping) != job["id"]
        or set(mapping) - refs
        or any(_local(key, mapping) != _local(key, origin_map) for key in refs)
        or len({_local(key, mapping) for key in refs}) != len(refs)
        or source.task != current.task
        or snapshot["summary"] != summarize_groups(evidence["groups"])
    ):
        raise ValueError("Original IDs, grouped summary or comparison checksum do not match")

    runtime_rows = {row["id"]: row for row in sections.get("model_runtime_selections", [])}
    picks = []
    for old_pin, pin, frozen in zip(
        (source.left, source.right), (current.left, current.right), snapshot["models"], strict=True
    ):
        receipt = RuntimeReceipt.model_validate(frozen["receipt"])
        model_id = _local(frozen["model_id"], mapping)
        selected = runtime_rows[str(pin.id)]
        model = session.get(ModelRegistration, model_id)
        if (
            _local(str(old_pin.id), mapping) != str(pin.id)
            or pin.sha256 != old_pin.sha256
            or selected["content_sha256"] != pin.sha256
            or canonical_json_sha256(selected["snapshot_json"]) != pin.sha256
            or selected["snapshot_json"] != receipt.model_dump(mode="json")
            or selected["project_id"] != project_id
            or selected["model_id"] != model_id
            or model is None
            or model.project_id != project_id
            or model.sha256 != receipt.checkpoint_sha256
            or model.task != receipt.task
        ):
            raise ValueError("Reviewed model and its runtime pin differ from registered evidence")
        picks.append(
            {
                "model_id": model_id,
                "checkpoint_sha256": receipt.checkpoint_sha256,
                "runtime_selection_id": str(pin.id),
                "runtime_selection_sha256": pin.sha256,
                **receipt.settings.model_dump(),
            }
        )

    ids = []
    original_digests = []
    for old, live in zip(source.sources, current.sources, strict=True):
        identifier = str(live.id)
        if _local(str(old.id), mapping) != identifier:
            raise ValueError("Local comparison source differs from the original source")
        record: DatasetVersion | Job | None
        if source.task in IMAGE_TASKS:
            record = session.get(DatasetVersion, identifier)
        else:
            record = session.get(Job, identifier)
        if record is None or record.project_id != project_id:
            raise ValueError("Paired comparison has a foreign source")
        digest = (
            record.manifest_sha256
            if isinstance(record, DatasetVersion)
            else (record.result_json or {}).get("result_sha256")
        )
        if digest != live.sha256 or (not mapping and live.sha256 != old.sha256):
            raise ValueError("Comparison source has a mismatched digest")
        ids.append(identifier)
        original_digests.append(old.sha256)

    if source.task in IMAGE_TASKS:
        children = tuple(
            _local(identifier, mapping) for identifier in evidence["inference_job_ids"]
        )
        if children and (len(children) != 2 or len(set(children)) != 2):
            raise ValueError("Still comparison lacks both independently recorded inference jobs")
        for identifier in children:
            child = session.get(Job, identifier)
            if child is None or child.request_json.get("paired_owner_run_id") not in (
                None,
                job["id"],
            ):
                raise ValueError("A still inference job belongs to a different comparison")
        if (
            evidence["reference_id"] != str(source.sources[0].id)
            or evidence["reference_sha256"] != original_digests[0]
        ):
            raise ValueError("Still source identity differs from the frozen test reference")
        frozen_groups = dict(
            session.execute(
                select(DatasetVersionItem.image_id, DatasetVersionItem.group_key).where(
                    DatasetVersionItem.dataset_version_id == ids[0],
                    DatasetVersionItem.split == "test",
                )
            ).all()
        )
        archived_groups = [
            (_local(obs["media_id"], mapping), group["group_id"])
            for group in evidence["groups"]
            for obs in group["observations"]
            if obs["media_kind"] == "image" and obs["frame"] is None
        ]
        if len(archived_groups) != len(frozen_groups) or dict(archived_groups) != frozen_groups:
            raise ValueError("Comparison does not bind exactly the frozen image groups")
        evidence_hashes = evidence["source_sha256"]
        if len(evidence_hashes) != 6 or evidence_hashes[:4] != [
            pick[field]
            for field in ("checkpoint_sha256", "runtime_selection_sha256")
            for pick in picks
        ]:
            raise ValueError(
                "Paired snapshot does not bind both selected model and runtime digests"
            )
        if not children and source.task == "mask":
            # Early exchanges could omit these pixels. Retain the report as unverified history.
            job_sections = sections | {
                "jobs": [
                    row
                    for row in sections["jobs"]
                    if row["job_type"] != JOB_TYPE or row["id"] == job["id"]
                ]
            }
            try:
                for path in paired_comparison_raster_paths(job_sections):
                    read_raster(path)
            except NotFoundError:
                return False
        try:
            expected = compare_image_models(
                session,
                None,
                project_id,
                source.task,
                {"dataset_version_id": ids[0]},
                picks,
                recorded=RecordedImageRuns(
                    (children[0], children[1]) if children else None,
                    read_raster,
                    {value: key for key, value in mapping.items()},
                    datetime.fromisoformat(job["completed_at"]),
                    legacy_digests=None if children else (evidence_hashes[4], evidence_hashes[5]),
                    started_at=datetime.fromisoformat(job["started_at"])
                    if job.get("started_at")
                    else None,
                ),
            )
        except UnverifiedLegacyInference:
            if not children:
                return False
            raise
        if expected["source_sha256"] != evidence["source_sha256"] or _lineage(
            expected, {}, include_digests=not mapping
        ) != _lineage(evidence, mapping, include_digests=not mapping):
            raise ValueError("Frozen still outputs or training lineage do not replay")
    else:
        if source.task not in ("pose", "tracking", "event"):
            raise ValueError("Unknown paired model task")
        expected = compare_video_models(
            session,
            project_id,
            source.task,
            ids,
            [pick["model_id"] for pick in picks],
            historical=True,
        )
        if evidence["source_sha256"] != original_digests or evidence["inference_job_ids"]:
            raise ValueError("Original scored video source digests differ")
    expected = ComparisonEvidence.model_validate(expected).model_dump(mode="json")
    if (
        expected["reference_id"] != _local(evidence["reference_id"], mapping)
        or (not mapping and expected["reference_sha256"] != evidence["reference_sha256"])
        or _groups(evidence, mapping) != _groups(expected, {})
        or any(
            expected[key] != evidence[key] for key in ("method", "limitations", "evaluation_status")
        )
    ):
        raise ValueError("Paired observations do not match their frozen model outputs")
    return True


def _artifact_checks(sections: Sections, records: dict[str, Row]) -> None:
    graphs = {row["id"]: row for row in sections.get("workflow_graphs", [])}
    runs = {row["id"]: row for row in sections.get("workflow_runs", [])}
    for graph in graphs.values():
        for node in graph.get("graph_json", {}).get("nodes", []):
            if node.get("node_type") != JOB_TYPE:
                continue
            params = node["parameters"]
            job = records[str(UUID(params["comparison_id"]))]
            if params["comparison_sha256"] != job["result_json"]["content_sha256"]:
                raise ValueError("Saved paired workflow has the wrong frozen report digest")
    producers = {
        row["id"]: row
        for row in sections.get("workflow_node_runs", [])
        if row["node_type"] == JOB_TYPE and row["status"] == "succeeded"
    }
    artifacts = [
        row for row in sections.get("workflow_artifacts", []) if row["data_type"] == ARTIFACT_TYPE
    ]
    if Counter(producers.keys()) != Counter(row["producer_node_run_id"] for row in artifacts):
        raise ValueError("Each completed paired model node must have exactly one immutable report")
    for artifact in artifacts:
        node = producers[artifact["producer_node_run_id"]]
        run = runs[node["workflow_run_id"]]
        graph = graphs[run["workflow_graph_record_id"]]
        [declared] = [
            entry for entry in graph["graph_json"]["nodes"] if entry["node_id"] == node["node_id"]
        ]
        params = node["parameters_json"]
        job = records[str(UUID(params["comparison_id"]))]
        result = job["result_json"]
        if (
            artifact["producer_port_id"] != "report"
            or artifact["workflow_run_id"] != run["id"]
            or declared["node_type"] != JOB_TYPE
            or declared["parameters"] != params
            or params["comparison_sha256"] != result["content_sha256"]
            or artifact["payload_json"]
            != {"snapshot": result["snapshot"], "content_sha256": result["content_sha256"]}
            or canonical_json_sha256(artifact["payload_json"]) != artifact["payload_sha256"]
        ):
            raise ValueError("Paired workflow artifact differs from its frozen result or producer")


def validate_paired_models_exchange(
    project_id: str,
    sections: Sections,
    origin_map: Mapping[str, str],
    *,
    read_raster: RasterReader | None = None,
) -> frozenset[str]:
    try:
        jobs = _completed(sections)
        _artifact_checks(sections, {row["id"]: row for row in jobs})
        if not jobs:
            return frozenset()
        paths = paired_comparison_raster_paths(sections)

        def verified_raster(path: str) -> bytes:
            if read_raster is None or path not in paths:
                raise NotFoundError("An archived paired comparison raster is missing")
            payload = read_raster(path)
            if sha256(payload).hexdigest() != paths[path]:
                raise ValidationError("Archived comparison raster checksum changed")
            return payload

        # Verify even raster inputs later excluded from metrics.
        for path in paired_comparison_raster_paths(sections, include_legacy=False):
            verified_raster(path)
        with _archive_session(sections) as session:
            return frozenset(
                row["id"]
                for row in jobs
                if _validate_record(session, row, sections, project_id, origin_map, verified_raster)
            )
    except (
        ReefVisionError,
        SQLAlchemyError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        IndexError,
    ) as exc:
        raise ValidationError(
            f"Paired model comparison Exchange could not verify its evidence. {exc}"
        ) from exc


def remap_paired_models_parameters(
    parameters: Row,
    id_map: dict[str, str],
    digest_map: dict[str, str] | None = None,
) -> Row:
    del digest_map
    try:
        original = str(UUID(parameters["comparison_id"]))
    except (TypeError, KeyError, ValueError, AttributeError):
        return parameters
    return {**parameters, "comparison_id": id_map.get(original, original)}


def _mapped_key(row: Row, key: str, mapping: Mapping[str, str]) -> None:
    if isinstance(row.get(key), str):
        row[key] = _local(row[key], mapping)


def _mapped_mask_path(row: Row, old_root: str, new_root: str) -> None:
    prefix = old_root.rstrip("/") + "/"
    path = row.get("mask_path")
    if old_root and isinstance(path, str) and path.startswith(prefix):
        row["mask_path"] = new_root.rstrip("/") + "/" + path[len(prefix) :]


def _dataset_for_restore(
    session: Session,
    dataset: Row,
    mapping: dict[str, str],
    digests: dict[str, str],
    project: Project,
    source_storage_root: str,
) -> None:
    version = session.get(DatasetVersion, mapping[dataset["id"]])
    if version is None or version.project_id != project.id:
        raise ValidationError("Restored frozen dataset is missing")
    manifest = deepcopy(dataset["manifest_json"])
    manifest["project"]["id"] = project.id
    _mapped_key(manifest["dataset_version"], "id", mapping)
    _mapped_key(manifest["dataset_version"], "parent_version_id", mapping)
    for entry in manifest["class_map"]:
        _mapped_key(entry, "id", mapping)
    local_items = {
        row.image_id: row
        for row in session.scalars(
            select(DatasetVersionItem).where(DatasetVersionItem.dataset_version_id == version.id)
        )
    }
    for original in manifest["items"]:
        snapshot = original
        _mapped_key(snapshot, "image_id", mapping)
        for name in ("annotations", "mask_annotations"):
            for shape in snapshot.get(name, []):
                for field in ("id", "label_class_id", "source_model_id", "source_prediction_id"):
                    _mapped_key(shape, field, mapping)
                provenance = shape.get("provenance_json")
                if isinstance(provenance, dict):
                    for field in ("source_model_id", "source_prediction_id"):
                        _mapped_key(provenance, field, mapping)
                _mapped_mask_path(shape, source_storage_root, project.storage_root)
        for name in ("per_class_counts", "per_mask_class_counts"):
            if name in snapshot:
                snapshot[name] = {
                    _local(identifier, mapping): count
                    for identifier, count in snapshot[name].items()
                }
        old_sha = snapshot.pop("snapshot_sha256")
        item = local_items[snapshot["image_id"]]
        item.original_filename = snapshot["original_filename"]
        item.annotation_snapshot_json = snapshot["annotations"]
        item.mask_annotation_snapshot_json = snapshot.get("mask_annotations", [])
        item.group_key = snapshot.get("group_key")
        item.per_class_counts_json = snapshot.get("per_class_counts", {})
        item.per_mask_class_counts_json = snapshot.get("per_mask_class_counts", {})
        item.snapshot_sha256 = snapshot["snapshot_sha256"] = canonical_json_sha256(snapshot)
        digests[old_sha] = item.snapshot_sha256
    version.class_map_json = manifest["class_map"]
    version.manifest_json = manifest
    version.manifest_sha256 = canonical_json_sha256(manifest)
    digests[dataset["manifest_sha256"]] = version.manifest_sha256


def restore_frozen_dataset_and_model_lineage(
    session: Session,
    project_id: str,
    sections: Sections,
    id_map: dict[str, str],
    digest_map: dict[str, str],
    *,
    source_storage_root: str = "",
    linked_dataset_ids: frozenset[str] = frozenset(),
) -> None:
    """Restore typed snapshot IDs, literal labels and verified comparison and model links."""
    completed = _completed(sections)
    if not completed and not linked_dataset_ids:
        return
    project = session.get(Project, project_id)
    if project is None:
        raise ValidationError("Restored comparison project is missing")
    datasets_by_old_id = {row["id"]: row for row in sections.get("dataset_versions", [])}
    dataset_ids = set(linked_dataset_ids)
    relevant_model_ids = {
        row["id"]
        for row in sections.get("models", [])
        if has_local_model_lineage(row)
        and (row.get("metadata_json") or {}).get("source_dataset_version_id") in linked_dataset_ids
    }
    children: set[str] = set()
    for row in completed:
        receipt = row["result_json"]
        snapshot, mapping = receipt["snapshot"], receipt["source_id_map"]
        if snapshot["selection"]["task"] in IMAGE_TASKS:
            data = snapshot["evidence"]
            datasets = {
                data["reference_id"],
                *(item["id"] for lineage in data["lineage"] for item in lineage["datasets"]),
            }
            dataset_ids.update(_local(key, mapping) for key in datasets)
            children.update(_local(key, mapping) for key in data.get("inference_job_ids", []))
            relevant_model_ids.update(
                _local(model["model_id"], mapping) for model in snapshot["models"]
            )
            relevant_model_ids.update(
                _local(key, mapping)
                for lineage in data["lineage"]
                for key in lineage["checkpoint_dependencies"]
            )

    for identifier in dataset_ids:
        _dataset_for_restore(
            session,
            datasets_by_old_id[identifier],
            id_map,
            digest_map,
            project,
            source_storage_root,
        )
    for row in sections.get("training_runs", []):
        source = datasets_by_old_id.get(row.get("dataset_version_id"))
        if (
            source is not None
            and row["dataset_version_id"] in dataset_ids
            and row["dataset_manifest_sha256"] == source["manifest_sha256"]
        ):
            run = session.get(TrainingRun, id_map[row["id"]])
            if run is not None:
                run.dataset_manifest_sha256 = digest_map[source["manifest_sha256"]]
    for row in sections.get("models", []):
        if row["id"] not in relevant_model_ids:
            continue
        model = session.get(ModelRegistration, id_map[row["id"]])
        if model is None:
            raise ValidationError("Restored paired model registration is missing")
        original_map = row["class_map_json"]
        model.class_map_json = {
            **original_map,
            "mapping": {
                label: _local(identifier, id_map) if identifier else None
                for label, identifier in original_map.get("mapping", {}).items()
            },
        }
        if not has_local_model_lineage(row):
            continue
        metadata = deepcopy(model.metadata_json)
        source = datasets_by_old_id.get(
            (row["metadata_json"] or {}).get("source_dataset_version_id")
        )
        if (
            source is not None
            and source["id"] in dataset_ids
            and (row["metadata_json"] or {}).get("source_dataset_manifest_sha256")
            == source["manifest_sha256"]
        ):
            metadata["source_dataset_manifest_sha256"] = digest_map[source["manifest_sha256"]]
        if "classes" in (row["metadata_json"] or {}):
            metadata["classes"] = deepcopy(row["metadata_json"]["classes"])
        model.metadata_json = metadata
    for row in sections.get("prediction_proposals", []):
        if row["inference_job_id"] in children:
            # The class label is an author literal, even if it looks like a project ID.
            proposal = session.get(PredictionProposal, id_map[row["id"]])
            if proposal is not None:
                proposal.predicted_label = row["predicted_label"]

    for row in completed:
        item = session.get(Job, id_map[row["id"]])
        if item is None or item.project_id != project_id:
            raise ValidationError("Restored paired comparison job is missing")
        old_result = row["result_json"]
        snapshot = old_result["snapshot"]
        prior = old_result["source_id_map"]
        links = {key: id_map[_local(key, prior)] for key in sorted(_sources(snapshot))}
        request = ComparisonRequest.model_validate(row["request_json"]).model_dump(mode="json")
        for name in ("left", "right"):
            request[name]["id"] = id_map[request[name]["id"]]
        for source in request["sources"]:
            archived_id = source["id"]
            source["id"] = id_map[archived_id]
            if request["task"] in IMAGE_TASKS:
                version = session.get(DatasetVersion, source["id"])
                assert version is not None
                source["sha256"] = version.manifest_sha256
            else:
                report = session.get(Job, source["id"])
                if report is None or not report.result_json:
                    raise ValidationError("Restored paired video scoring job is missing")
                source["sha256"] = report.result_json["result_sha256"]
        item.result_json = {**old_result, "source_id_map": links}
        item.request_json = request
    session.flush()
