"""Queue and read immutable static count comparisons using existing job storage."""

from collections.abc import Mapping
from datetime import UTC
from typing import Any, cast
from uuid import UUID

from pydantic import ValidationError as ContractError
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from reefvision import __version__
from reefvision.config import Settings
from reefvision.db.models import (
    DatasetVersion,
    DatasetVersionItem,
    ImageAsset,
    Job,
    ModelRegistration,
    Project,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.domain.static_count_agreement import (
    count_pairs,
    paired_difference,
    score_image,
    statistics,
)
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.static_comparison import (
    LineageStatus,
    ReferenceAnnotation,
    StaticClass,
    StaticComparisonRecord,
    StaticComparisonRequest,
    StaticDatasetOption,
    StaticEvidence,
    StaticImageResult,
    StaticModelEvidence,
    StaticModelOption,
    StaticModelResult,
    StaticOptions,
    StaticReferenceImage,
    StaticSnapshot,
    StaticSummary,
)
from reefvision.services.static_comparison_lineage import detector_lineage
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.static_comparison import verify_static_content

STATIC_COMPARISON_JOB = "static_comparison"

LIMITATIONS = [
    "The reference contains bounding boxes from a frozen human-reviewed dataset. "
    "Its review history may include explicitly accepted predictions.",
    "Bias is model count minus reference count. Percentage errors use positive reference "
    "counts. Absolute errors also include zero references.",
    "Totals require predictions for every selected class. Paired model differences use the "
    "common scored images for each endpoint. A negative change favors the second model.",
    "Numerical agreement excludes inference failures, missing inputs and class mismatches. "
    "Review these cases in the image results.",
    "Confidence intervals resample at least five confirmed independent groups, retaining "
    "all images within each sampled group.",
    "Bland-Altman limits require one pair per confirmed independent group and approximately "
    "normal differences with constant variance. ICC also requires one pair per independent group.",
    "ICC(A,1) measures absolute agreement. ICC(C,1) measures consistency after accounting "
    "for a fixed offset between methods.",
    "Held-out status reflects the recorded training, model selection and sampling groups. "
    "Group keys must represent the broadest shared sampling unit.",
]


def _project(session: Session, project_id: str) -> None:
    if session.get(Project, project_id) is None:
        raise NotFoundError("Project not found")


def _model_mapping(model: ModelRegistration) -> tuple[list[str], dict[str, UUID | None]]:
    raw_labels = model.class_map_json.get("labels", [])
    raw_mapping = model.class_map_json.get("mapping", {})
    if not isinstance(raw_labels, list) or not isinstance(raw_mapping, dict):
        raise ValidationError("Registered detector class mapping is invalid")
    labels = [str(label) for label in raw_labels]
    if len(set(labels)) != len(labels):
        raise ValidationError("Registered detector class labels must be unique")
    try:
        mapping = {
            label: UUID(str(raw_mapping[label])) if raw_mapping.get(label) else None
            for label in labels
        }
    except ValueError as exc:
        raise ValidationError(
            "Registered detector class mapping must use project class IDs"
        ) from exc
    return labels, mapping


def _classes(version: DatasetVersion) -> list[StaticClass]:
    return [
        StaticClass.model_validate({"id": row["id"], "name": row["name"]})
        for row in version.class_map_json
    ]


def comparison_options(session: Session, project_id: str, limit: int, offset: int) -> StaticOptions:
    _project(session, project_id)
    reviewed = (
        select(
            DatasetVersionItem.dataset_version_id.label("version_id"),
            func.count().label("reviewed_count"),
            func.sum(case((DatasetVersionItem.split == "test", 1), else_=0)).label("test_count"),
        )
        .where(DatasetVersionItem.image_annotation_status == "reviewed")
        .group_by(DatasetVersionItem.dataset_version_id)
        .subquery()
    )
    datasets = cast(
        list[tuple[DatasetVersion, int, int]],
        session.execute(
            select(DatasetVersion, reviewed.c.reviewed_count, reviewed.c.test_count)
            .join(reviewed, DatasetVersion.id == reviewed.c.version_id)
            .where(DatasetVersion.project_id == project_id, DatasetVersion.status == "complete")
            .order_by(DatasetVersion.created_at.desc(), DatasetVersion.id)
            .offset(offset)
            .limit(limit)
        ).all(),
    )
    models = session.scalars(
        select(ModelRegistration)
        .where(
            ModelRegistration.project_id == project_id,
            ModelRegistration.purpose == "detector",
            ModelRegistration.task == "detect",
        )
        .order_by(ModelRegistration.display_name, ModelRegistration.id)
        .offset(offset)
        .limit(limit)
    )
    model_options = []
    for model in models:
        if (model.metadata_json or {}).get("exchange_media_missing"):
            continue
        _, mapping = _model_mapping(model)
        mapped = sorted({value for value in mapping.values() if value is not None})
        if mapped:
            model_options.append(
                StaticModelOption(
                    id=UUID(model.id), name=model.display_name, mapped_class_ids=mapped
                )
            )
    return StaticOptions(
        datasets=[
            StaticDatasetOption(
                id=UUID(row.id),
                name=row.name,
                reviewed_count=count,
                test_reviewed_count=test_count,
                classes=_classes(row),
            )
            for row, count, test_count in datasets
        ],
        models=model_options,
    )


def reference_image(item: DatasetVersionItem) -> StaticReferenceImage:
    status = item.image_annotation_status
    return StaticReferenceImage(
        id=UUID(item.image_id),
        name=item.original_filename,
        image_sha256=item.image_sha256,
        item_sha256=item.snapshot_sha256,
        group_key=item.group_key,
        split=item.split,
        exclusion=None
        if status == "reviewed"
        else "excluded_image"
        if status == "excluded"
        else "unreviewed_image",
        annotations=[
            ReferenceAnnotation.model_validate(
                {
                    "id": row["id"],
                    "revision": row["revision"],
                    "class_id": row["label_class_id"],
                    "source_model_id": row.get("source_model_id"),
                }
            )
            for row in item.annotation_snapshot_json
        ],
    )


def selection_runs(session: Session, project_id: str) -> list[Job]:
    return list(
        session.scalars(
            select(Job).where(
                Job.project_id == project_id,
                Job.job_type == "learning_evaluation",
                Job.status == "succeeded",
            )
        )
    )


def freeze_evidence(
    session: Session, settings: Settings, project_id: str, options: StaticComparisonRequest
) -> StaticEvidence:
    version = session.get(DatasetVersion, str(options.dataset_version_id))
    if version is None or version.project_id != project_id:
        raise NotFoundError("Reviewed dataset version not found in this project")
    if (
        version.status != "complete"
        or canonical_json_sha256(version.manifest_json) != version.manifest_sha256
    ):
        raise ValidationError("Reference must be a complete immutable dataset version")
    classes = [
        row for row in _classes(version) if not options.class_ids or row.id in options.class_ids
    ]
    class_ids = {row.id for row in classes}
    if not class_ids or set(options.class_ids) - class_ids:
        raise ValidationError("Choose classes belonging to the frozen reference dataset")
    items = session.scalars(
        select(DatasetVersionItem)
        .where(DatasetVersionItem.dataset_version_id == version.id)
        .order_by(DatasetVersionItem.image_id)
    )
    images = [
        reference_image(item) for item in items if options.split == "all" or item.split == "test"
    ]
    if not any(row.exclusion is None for row in images):
        raise ValidationError("The selected split has no frozen human-reviewed images")
    if options.independent_groups and any(
        not row.group_key for row in images if row.exclusion is None
    ):
        raise ValidationError(
            "Every reviewed image needs a frozen group key to confirm independent sampling groups"
        )
    runs = selection_runs(session, project_id)
    models = []
    for model_id in options.model_ids:
        model = session.get(ModelRegistration, str(model_id))
        if model is None or model.project_id != project_id:
            raise NotFoundError("Registered detector was not found in this project")
        if model.purpose != "detector" or model.task != "detect":
            raise ValidationError("Choose a registered bounding-box detector")
        labels, mapping = _model_mapping(model)
        if not class_ids.intersection(mapping.values()):
            raise ValidationError(
                f"{model.display_name} has no mapping to the selected reference classes"
            )
        verify_static_content(settings, model.managed_path, model.sha256, fresh=True)
        models.append(
            StaticModelEvidence(
                id=UUID(model.id),
                name=model.display_name,
                checkpoint_sha256=model.sha256,
                provider_name=model.provider_name,
                registration_provider_version=model.provider_version,
                labels=labels,
                mapping=mapping,
                lineage=detector_lineage(session, model, images, runs),
            )
        )
    return StaticEvidence(
        options=options,
        reference_name=version.name,
        reference_sha256=version.manifest_sha256,
        classes=classes,
        images=images,
        models=models,
        outside_split_image_count=version.image_count - len(images),
    )


def submit_static_comparison(
    session: Session,
    settings: Settings,
    project_id: str,
    options: StaticComparisonRequest,
    *,
    workflow_run_id: str | None = None,
    workflow_node_run_id: str | None = None,
) -> JobResponse:
    evidence = freeze_evidence(session, settings, project_id, options)
    inputs = evidence.model_dump(mode="json")
    job = Job(
        job_type=STATIC_COMPARISON_JOB,
        project_id=project_id,
        status="queued",
        progress_current=0,
        progress_total=len(evidence.images) * len(evidence.models),
        request_json={
            "evidence": inputs,
            "evidence_sha256": canonical_json_sha256(inputs),
            "workflow_run_id": workflow_run_id,
            "workflow_node_run_id": workflow_node_run_id,
        },
    )
    session.add(job)
    session.commit()
    return JobResponse.model_validate(job)


def build_snapshot(
    evidence: StaticEvidence,
    observations: Mapping[UUID, tuple[str | None, list[StaticImageResult]]],
    *,
    software_version: str = __version__,
) -> StaticSnapshot:
    groups = {row.id: row.group_key for row in evidence.images}
    requests: list[UUID | None] = [None, *(row.id for row in evidence.classes)]
    options = evidence.options
    results = []
    pair_maps = []
    for model in evidence.models:
        provider_version, inferred = observations[model.id]
        by_id = {row.image_id: row for row in inferred}
        images = [
            score_image(
                image,
                model,
                evidence.classes,
                by_id.get(image.id)
                or StaticImageResult(
                    image_id=image.id,
                    status=image.exclusion or "prediction_missing",
                ),
            )
            for image in evidence.images
        ]
        pairs = {class_id: count_pairs(images, groups, class_id) for class_id in requests}
        pair_maps.append(pairs)
        results.append(
            StaticModelResult(
                model_id=model.id,
                runtime_provider_version=provider_version,
                images=images,
                total_statistics=statistics(list(pairs[None].values()), options),
                class_statistics={
                    cls.id: statistics(list(pairs[cls.id].values()), options)
                    for cls in evidence.classes
                },
            )
        )
    paired = (
        {
            class_id: paired_difference(pair_maps[0][class_id], pair_maps[1][class_id], options)
            for class_id in requests
        }
        if len(pair_maps) == 2
        else {}
    )
    statuses = {row.lineage.status for row in evidence.models}
    status: LineageStatus = (
        "overlap"
        if "overlap" in statuses
        else ("exploratory" if "exploratory" in statuses else "held_out")
    )
    return StaticSnapshot(
        software_version=software_version,
        evidence=evidence,
        evaluation_status=status,
        results=results,
        total_model_difference=paired.get(None),
        class_model_differences={key: value for key, value in paired.items() if key is not None},
        limitations=LIMITATIONS,
    )


def record_from_job(job: Job) -> StaticComparisonRecord:
    try:
        record = StaticComparisonRecord.model_validate(
            {
                **(job.result_json or {}),
                "id": job.id,
                "project_id": job.project_id,
            }
        )
    except ContractError as exc:
        raise ValidationError("Saved static comparison is invalid") from exc
    if record.content_sha256 != canonical_json_sha256(record.snapshot.model_dump(mode="json")):
        raise ValidationError("Saved static comparison checksum does not match")
    return record


def read_static_comparison(
    session: Session,
    project_id: str,
    identifier: str,
    settings: Settings | None = None,
) -> StaticComparisonRecord:
    job = session.get(Job, identifier)
    if job is None or job.project_id != project_id or job.job_type != STATIC_COMPARISON_JOB:
        raise NotFoundError("Saved static comparison not found")
    if job.status != "succeeded":
        raise ConflictError("This comparison has no saved result")
    record = record_from_job(job)
    evidence = record.snapshot.evidence
    id_map = record.source_id_map
    version_key = str(evidence.options.dataset_version_id)
    version = session.get(DatasetVersion, id_map.get(version_key, version_key))
    if (
        version is None
        or version.project_id != project_id
        or version.manifest_sha256 != record.local_reference_sha256
        or canonical_json_sha256(version.manifest_json) != record.local_reference_sha256
    ):
        record.stale = True
        return record
    source_rows = cast(
        list[tuple[ImageAsset, DatasetVersionItem]],
        session.execute(
            select(ImageAsset, DatasetVersionItem)
            .join(DatasetVersionItem, DatasetVersionItem.image_id == ImageAsset.id)
            .where(DatasetVersionItem.dataset_version_id == version.id)
        ).all(),
    )
    image_sources = {image.id: (image, item) for image, item in source_rows}
    for image in evidence.images:
        key = str(image.id)
        source = image_sources.get(id_map.get(key, key))
        if source is None:
            record.stale = True
            return record
        asset, item = source
        if (
            asset.project_id != project_id
            or asset.sha256 != image.image_sha256
            or item.snapshot_sha256 != image.item_sha256
        ):
            record.stale = True
            return record
        if settings is not None and not (asset.metadata_json or {}).get("exchange_media_missing"):
            try:
                verify_static_content(settings, asset.managed_path, asset.sha256)
            except (NotFoundError, ValidationError):
                record.stale = True
                return record
    runs = selection_runs(session, project_id)
    for model in evidence.models:
        key = str(model.id)
        registered = session.get(ModelRegistration, id_map.get(key, key))
        if (
            registered is None
            or registered.project_id != project_id
            or (registered.sha256 != model.checkpoint_sha256)
        ):
            record.stale = True
            return record
        try:
            labels, mapping = _model_mapping(registered)
        except ValidationError:
            record.stale = True
            return record
        expected = {
            label: UUID(id_map.get(str(value), str(value))) if value is not None else None
            for label, value in model.mapping.items()
        }
        if labels != model.labels or mapping != expected:
            record.stale = True
            return record
        if settings is not None and not (registered.metadata_json or {}).get(
            "exchange_media_missing"
        ):
            try:
                verify_static_content(settings, registered.managed_path, model.checkpoint_sha256)
            except (NotFoundError, ValidationError):
                record.stale = True
                return record
        if (
            not id_map
            and detector_lineage(session, registered, evidence.images, runs) != model.lineage
        ):
            record.stale = True
            return record
    return record


def list_static_comparisons(
    session: Session,
    project_id: str,
    limit: int,
    offset: int,
    *,
    completed_only: bool = False,
) -> list[StaticSummary]:
    _project(session, project_id)
    statement = select(Job).where(
        Job.project_id == project_id, Job.job_type == STATIC_COMPARISON_JOB
    )
    if completed_only:
        statement = statement.where(Job.status == "succeeded")
    jobs = session.scalars(
        statement.order_by(Job.created_at.desc(), Job.id).offset(offset).limit(limit)
    )
    summaries = []
    for job in jobs:
        raw: dict[str, Any] = (job.request_json or {}).get("evidence", {})
        saved = (job.result_json or {}).get("snapshot", {})
        created = job.created_at
        summaries.append(
            StaticSummary(
                id=UUID(job.id),
                status=job.status,
                created_at=created if created.tzinfo else created.replace(tzinfo=UTC),
                reference_name=raw.get("reference_name", ""),
                model_names=[row["name"] for row in raw.get("models", [])],
                evaluation_status=saved.get("evaluation_status"),
            )
        )
    return summaries
