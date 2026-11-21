"""Trace detector training, warm starts, and local model-selection exposure."""

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    DatasetVersion,
    DatasetVersionItem,
    Job,
    ModelRegistration,
    TrainingRun,
)
from reefvision.schemas.static_comparison import LineageDataset, StaticLineage, StaticReferenceImage


@dataclass(frozen=True)
class LineageLookup:
    get_model: Callable[[str], ModelRegistration | None]
    get_training: Callable[[str], TrainingRun | None]
    get_dataset: Callable[[str], DatasetVersion | None]
    get_items: Callable[[str, set[str]], Sequence[DatasetVersionItem]]


def detector_lineage(
    session: Session,
    model: ModelRegistration,
    reference_images: Sequence[StaticReferenceImage],
    selection_runs: Sequence[Job],
) -> StaticLineage:
    return trace_detector_lineage(
        model,
        reference_images,
        selection_runs,
        LineageLookup(
            get_model=lambda identifier: session.get(ModelRegistration, identifier),
            get_training=lambda identifier: session.get(TrainingRun, identifier),
            get_dataset=lambda identifier: session.get(DatasetVersion, identifier),
            get_items=lambda identifier, splits: session.scalars(
                select(DatasetVersionItem).where(
                    DatasetVersionItem.dataset_version_id == identifier,
                    DatasetVersionItem.split.in_(splits),
                )
            ).all(),
        ),
    )


def trace_detector_lineage(
    model: ModelRegistration,
    reference_images: Sequence[StaticReferenceImage],
    selection_runs: Sequence[Job],
    lookup: LineageLookup,
) -> StaticLineage:
    runs: set[str] = set()
    selection_ids: set[str] = set()
    checkpoints: dict[UUID, str] = {}
    datasets: dict[tuple[str, str], set[str]] = defaultdict(set)
    unknown: set[str] = set()
    reviewed = [row for row in reference_images if row.exclusion is None]
    exposed_images: set[str] = set()
    exposed_hashes: set[str] = set()
    exposed_groups: set[str] = set()
    overlap: set[UUID] = set()

    def include(dataset_id: object, splits: list[str], expected_sha: str | None = None) -> None:
        version = lookup.get_dataset(dataset_id) if isinstance(dataset_id, str) else None
        if (
            version is None
            or version.project_id != model.project_id
            or version.status != "complete"
            or (expected_sha is not None and expected_sha != version.manifest_sha256)
        ):
            unknown.add("An upstream dataset or immutable manifest is unavailable")
            return
        known_splits = datasets[(version.id, version.manifest_sha256)]
        requested = set(splits) - known_splits
        known_splits.update(splits)
        if not requested:
            return
        rows = lookup.get_items(version.id, requested)
        if not rows or any(not row.group_key for row in rows):
            unknown.add("Training or model-selection sampling groups are incomplete")
        exposed_images.update(row.image_id for row in rows)
        exposed_hashes.update(row.image_sha256 for row in rows)
        exposed_groups.update(row.group_key for row in rows if row.group_key)

    def follow(current: ModelRegistration, visited: set[str]) -> None:
        if current.id in visited:
            unknown.add("Detector checkpoint ancestry contains a cycle")
            return
        checkpoints[UUID(current.id)] = current.sha256
        metadata = current.metadata_json or {}
        run_id = metadata.get("source_training_run_id")
        run = lookup.get_training(run_id) if isinstance(run_id, str) else None
        if (
            run is None
            or run.project_id != model.project_id
            or run.status != "completed"
            or run.task != "detect"
            or metadata.get("source_dataset_version_id") != run.dataset_version_id
            or metadata.get("source_dataset_manifest_sha256") != run.dataset_manifest_sha256
            or metadata.get("source_split_manifest_sha256") != run.split_manifest_sha256
        ):
            unknown.add(f"Complete training lineage is unavailable for {current.display_name}")
        else:
            runs.add(run.id)
            include(run.dataset_version_id, ["train", "validation"], run.dataset_manifest_sha256)
            if run.initial_checkpoint_source == "registered_model":
                parent = (
                    lookup.get_model(run.initial_checkpoint_model_id)
                    if run.initial_checkpoint_model_id
                    else None
                )
                if (
                    parent is None
                    or parent.project_id != model.project_id
                    or (
                        run.resolved_model_checksum and parent.sha256 != run.resolved_model_checksum
                    )
                ):
                    unknown.add("A warm-start checkpoint or matching checksum is unavailable")
                else:
                    follow(parent, visited | {current.id})
            elif run.initial_checkpoint_source != "scratch":
                unknown.add("The external pretrained checkpoint has no verifiable image lineage")

        relevant_jobs = {
            row.id
            for row in selection_runs
            if current.id
            in (
                (row.request_json or {}).get("candidate_model_id"),
                (row.request_json or {}).get("incumbent_model_id"),
            )
        }
        promoted_by = metadata.get("promoted_by_evaluation_id")
        if promoted_by and promoted_by not in relevant_jobs:
            unknown.add("The deployment's model-selection evidence is unavailable")
        for row in selection_runs:
            if row.id not in relevant_jobs:
                continue
            selection_ids.add(row.id)
            config = row.request_json or {}
            split = config.get("split")
            if split not in {"test", "validation"}:
                unknown.add("A model-selection run has an unknown evaluation split")
                continue
            include(config.get("dataset_version_id"), [split])

    follow(model, set())
    if any(not row.group_key for row in reviewed):
        unknown.add("Reviewed reference sampling groups are incomplete")
    for image in reviewed:
        if (
            str(image.id) in exposed_images
            or image.image_sha256 in exposed_hashes
            or (image.group_key is not None and image.group_key in exposed_groups)
            or any(row.source_model_id in checkpoints for row in image.annotations)
        ):
            overlap.add(image.id)
    reasons = sorted(unknown)
    if overlap:
        reasons.insert(
            0, "Known reference overlap by image, content, group, or reviewed model origin"
        )
    return StaticLineage(
        status="overlap" if overlap else "exploratory" if unknown else "held_out",
        reasons=reasons,
        training_run_ids=sorted(UUID(identifier) for identifier in runs),
        model_selection_job_ids=sorted(UUID(identifier) for identifier in selection_ids),
        checkpoint_dependencies=checkpoints,
        datasets=[
            LineageDataset(id=identifier, manifest_sha256=digest, splits=sorted(splits))
            for (identifier, digest), splits in sorted(datasets.items())
        ],
        overlapping_image_ids=sorted(overlap),
    )
