"""Keep static report evidence immutable and relink its project-owned sources."""

from collections import defaultdict
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError as ContractError
from sqlalchemy.orm import Session

from reefvision.db.models import (
    DatasetVersion,
    DatasetVersionItem,
    Job,
    ModelRegistration,
    TrainingRun,
)
from reefvision.domain.errors import ValidationError
from reefvision.domain.static_count_agreement import valid_prediction_mapping
from reefvision.schemas.static_comparison import StaticComparisonRecord, StaticEvidence
from reefvision.services.static_comparison import (
    STATIC_COMPARISON_JOB,
    build_snapshot,
    reference_image,
)
from reefvision.services.static_comparison_lineage import LineageLookup, trace_detector_lineage
from reefvision.storage.datasets import canonical_json_sha256


def _source_ids(evidence: StaticEvidence) -> set[str]:
    return {
        str(evidence.options.dataset_version_id),
        *(str(row.id) for row in evidence.images),
        *(str(row.id) for row in evidence.classes),
        *(str(row.id) for row in evidence.models),
        *(str(value) for row in evidence.models for value in row.mapping.values() if value),
        *(str(row.id) for image in evidence.images for row in image.annotations),
        *(str(row.class_id) for image in evidence.images for row in image.annotations),
        *(
            str(row.source_model_id)
            for image in evidence.images
            for row in image.annotations
            if row.source_model_id
        ),
        *(str(key) for row in evidence.models for key in row.lineage.checkpoint_dependencies),
        *(str(key) for row in evidence.models for key in row.lineage.training_run_ids),
        *(str(key) for row in evidence.models for key in row.lineage.model_selection_job_ids),
        *(str(key.id) for row in evidence.models for key in row.lineage.datasets),
    }


def _at(value: str | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    stamp = datetime.fromisoformat(value)
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def _validate_lineage(
    record: StaticComparisonRecord,
    reference: list[DatasetVersionItem],
    cutoff: datetime,
    sections: dict[str, list[dict[str, Any]]],
    local: Callable[[object], str],
) -> None:
    project_id = str(record.project_id)
    evidence = record.snapshot.evidence
    models = {
        row["id"]: ModelRegistration(**row)
        for row in sections.get("models", [])
        if row["project_id"] == project_id
    }
    training = {
        row["id"]: TrainingRun(**row)
        for row in sections.get("training_runs", [])
        if row["project_id"] == project_id
    }
    # Training runs retain their original manifest hash while imported datasets
    # are re-addressed. Match their exposure using the linked local item inventory.
    original_hashes = {
        local(dataset.id): dataset.manifest_sha256
        for model in evidence.models
        for dataset in model.lineage.datasets
        if local(dataset.id) != str(dataset.id)
    }
    datasets = {
        row["id"]: DatasetVersion(
            **{
                **row,
                "manifest_sha256": original_hashes.get(row["id"], row["manifest_sha256"]),
            }
        )
        for row in sections.get("dataset_versions", [])
        if row["project_id"] == project_id
    }
    items: dict[str, list[DatasetVersionItem]] = defaultdict(list)
    for row in sections.get("dataset_version_items", []):
        if row["dataset_version_id"] in datasets:
            items[row["dataset_version_id"]].append(DatasetVersionItem(**row))
    selections = {
        row["id"]: row
        for row in sections.get("jobs", [])
        if row["job_type"] == "learning_evaluation"
        and row["status"] == "succeeded"
        and row["project_id"] == project_id
    }
    lookup = LineageLookup(
        get_model=models.get,
        get_training=training.get,
        get_dataset=datasets.get,
        get_items=lambda identifier, splits: [
            row for row in items[identifier] if row.split in splits
        ],
    )
    for registration in models.values():
        promoted = (registration.metadata_json or {}).get("promoted_by_evaluation_id")
        if promoted in selections and _at(selections[promoted].get("completed_at")) > cutoff:
            registration.metadata_json = {
                **registration.metadata_json,
                "promoted_by_evaluation_id": None,
            }
    selected_jobs = [
        Job(**row) for row in selections.values() if _at(row.get("completed_at")) <= cutoff
    ]
    reference_images = [reference_image(item) for item in reference]
    for frozen in evidence.models:
        model = models.get(local(frozen.id))
        if model is None and frozen.lineage.status != "held_out":
            continue
        if (
            model is None
            or model.sha256 != frozen.checkpoint_sha256
            or model.task != "detect"
            or model.purpose != "detector"
            or model.provider_name != frozen.provider_name
            or model.class_map_json.get("labels") != frozen.labels
        ):
            raise ValidationError("Static comparison checkpoint does not match its registration")
        expected = {
            label: local(class_id) if class_id else None
            for label, class_id in frozen.mapping.items()
        }
        mapped = model.class_map_json.get("mapping", {})
        if (
            not isinstance(mapped, dict)
            or {label: mapped.get(label) for label in frozen.labels} != expected
        ):
            raise ValidationError("Static comparison class mapping differs from its registration")
        lineage = trace_detector_lineage(model, reference_images, selected_jobs, lookup)
        if (
            lineage.status != frozen.lineage.status
            or {str(value) for value in lineage.overlapping_image_ids}
            != {local(value) for value in frozen.lineage.overlapping_image_ids}
            or {str(value) for value in lineage.training_run_ids}
            != {local(value) for value in frozen.lineage.training_run_ids}
            or {str(value) for value in lineage.model_selection_job_ids}
            != {local(value) for value in frozen.lineage.model_selection_job_ids}
            or {str(value): digest for value, digest in lineage.checkpoint_dependencies.items()}
            != {
                local(value): digest
                for value, digest in frozen.lineage.checkpoint_dependencies.items()
            }
            or {(str(row.id), row.manifest_sha256, tuple(row.splits)) for row in lineage.datasets}
            != {
                (local(row.id), row.manifest_sha256, tuple(row.splits))
                for row in frozen.lineage.datasets
            }
        ):
            raise ValidationError(
                "Static comparison training or model-selection lineage does not replay"
            )


def validate_static_comparison_exchange(
    sections: dict[str, list[dict[str, Any]]],
) -> set[str]:
    saved_ids = set()
    datasets = {row["id"]: row for row in sections.get("dataset_versions", [])}
    items = {
        (row["dataset_version_id"], row["image_id"]): row
        for row in sections.get("dataset_version_items", [])
    }
    for job in sections.get("jobs", []):
        if job["job_type"] != STATIC_COMPARISON_JOB:
            continue
        try:
            request = job["request_json"]
            raw_evidence = request["evidence"]
            if canonical_json_sha256(raw_evidence) != request["evidence_sha256"]:
                raise ValidationError("Static comparison request checksum does not match")
            requested = StaticEvidence.model_validate(raw_evidence)
            if job["status"] != "succeeded":
                continue
            record = StaticComparisonRecord.model_validate(
                {
                    **job["result_json"],
                    "id": job["id"],
                    "project_id": job["project_id"],
                }
            )
            snapshot = record.snapshot
            evidence = snapshot.evidence
            if (
                requested != evidence
                or canonical_json_sha256(snapshot.model_dump(mode="json")) != record.content_sha256
            ):
                raise ValidationError("Static comparison evidence or checksum does not match")
            source_map = record.source_id_map
            if source_map.keys() - _source_ids(evidence):
                raise ValidationError("Static comparison source mapping contains unrelated IDs")

            def local(identifier: object, mapping: dict[str, str] = source_map) -> str:
                value = str(identifier)
                return mapping.get(value, value)

            version_id = local(evidence.options.dataset_version_id)
            dataset = datasets.get(version_id)
            if (
                dataset is None
                or dataset["project_id"] != job["project_id"]
                or dataset["manifest_sha256"] != record.local_reference_sha256
                or (not source_map and evidence.reference_sha256 != record.local_reference_sha256)
                or canonical_json_sha256(dataset["manifest_json"]) != dataset["manifest_sha256"]
            ):
                raise ValidationError("Static comparison has no matching reviewed dataset")
            expected_classes = {
                row["id"]: row["name"]
                for row in dataset["class_map_json"]
                if not evidence.options.class_ids
                or row["id"] in {local(key) for key in evidence.options.class_ids}
            }
            if expected_classes != {local(row.id): row.name for row in evidence.classes}:
                raise ValidationError(
                    "Static comparison class identities differ from the reference"
                )
            selected_items = {
                image_id
                for (dataset_id, image_id), item in items.items()
                if dataset_id == version_id
                and (evidence.options.split == "all" or item["split"] == "test")
            }
            if (
                selected_items != {local(row.id) for row in evidence.images}
                or len(selected_items) != len(evidence.images)
                or evidence.outside_split_image_count
                != dataset["image_count"] - len(selected_items)
            ):
                raise ValidationError(
                    "Static comparison image selection does not match the frozen split"
                )
            reviewed_items = []
            for image in evidence.images:
                item = items[version_id, local(image.id)]
                version_item = DatasetVersionItem(**item)
                reviewed_items.append(version_item)
                actual = reference_image(version_item)
                expected = image.model_dump(mode="json")
                expected["id"] = local(image.id)
                for annotation in expected["annotations"]:
                    for key in ("id", "class_id", "source_model_id"):
                        if annotation[key] is not None:
                            annotation[key] = local(annotation[key])
                if actual.model_dump(mode="json") != expected:
                    raise ValidationError(
                        "Static comparison reference revisions do not match the dataset"
                    )
            _validate_lineage(record, reviewed_items, _at(job.get("created_at")), sections, local)
            if [row.id for row in evidence.models] != evidence.options.model_ids:
                raise ValidationError("Static comparison checkpoint identities are inconsistent")
            for model, outcome in zip(evidence.models, snapshot.results, strict=True):
                if model.id != outcome.model_id or [row.id for row in evidence.images] != [
                    row.image_id for row in outcome.images
                ]:
                    raise ValidationError("Static comparison image or model results are incomplete")
                for image, result in zip(evidence.images, outcome.images, strict=True):
                    if (
                        (image.exclusion and result.status != image.exclusion)
                        or (
                            not image.exclusion
                            and result.status in {"excluded_image", "unreviewed_image"}
                        )
                        or (result.status != "inferred" and result.raw_predictions)
                        or any(
                            not valid_prediction_mapping(model, row)
                            for row in result.raw_predictions
                        )
                    ):
                        raise ValidationError(
                            "Static comparison raw evidence disagrees with image or class identity"
                        )
            replayed = build_snapshot(
                evidence,
                {
                    row.model_id: (row.runtime_provider_version, row.images)
                    for row in snapshot.results
                },
                software_version=snapshot.software_version,
            )
            if replayed != snapshot:
                raise ValidationError("Static comparison agreement statistics do not replay")
            saved_ids.add(job["id"])
        except (ContractError, KeyError, TypeError, ValueError) as exc:
            raise ValidationError("Static comparison exchange record is invalid") from exc
    return saved_ids


def restore_static_comparisons(
    session: Session,
    sections: dict[str, list[dict[str, Any]]],
    id_map: dict[str, str],
) -> None:
    for original in sections.get("jobs", []):
        if original["job_type"] != STATIC_COMPARISON_JOB:
            continue
        job = session.get(Job, id_map[original["id"]])
        if job is None:
            raise ValidationError("Imported static comparison job is missing")
        job.request_json = {
            **deepcopy(original["request_json"]),
            "workflow_run_id": id_map.get(original["request_json"].get("workflow_run_id")),
            "workflow_node_run_id": id_map.get(
                original["request_json"].get("workflow_node_run_id")
            ),
        }
        if original["status"] != "succeeded":
            continue
        result = deepcopy(original["result_json"])
        evidence = StaticEvidence.model_validate(result["snapshot"]["evidence"])
        previous_ids = result["source_id_map"]
        links = {
            key: id_map.get(previous_ids.get(key, key), previous_ids.get(key, key))
            for key in sorted(_source_ids(evidence))
        }
        version = session.get(DatasetVersion, links[str(evidence.options.dataset_version_id)])
        if version is None:
            raise ValidationError("Imported static comparison lost its reviewed dataset")
        result.update(source_id_map=links, local_reference_sha256=version.manifest_sha256)
        job.result_json = result
    session.flush()
