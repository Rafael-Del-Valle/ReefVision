"""Run paired model comparisons and preserve each independent group's contribution."""

from collections import defaultdict
from datetime import UTC, datetime
from statistics import fmean
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError as SchemaError
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import DatasetVersion, Job, Project
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.model_runtime import RuntimeSelectionResponse
from reefvision.schemas.paired_models_v15 import (
    ComparisonEvidence,
    ComparisonRequest,
    ComparisonSource,
    ComparisonTask,
    PairedGroup,
)
from reefvision.services.model_runtime import ModelRuntimeService, pinned_job_settings
from reefvision.storage.datasets import canonical_json_sha256

JOB_TYPE = "paired_model_comparison"
IMAGE_TASKS = {"detector", "mask"}
MODEL_TASKS = {
    "detector": {"detect"},
    "mask": {"segment", "semantic_segment"},
    "pose": {"pose"},
    "tracking": {"pose"},
    "event": {"pose"},
}
AGGREGATION = (
    "Within each group, average complete paired observations for each metric. "
    "Give each contributing group equal weight in the final mean. Difference is right minus left."
)


def summarize_groups(groups: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        parsed = [PairedGroup.model_validate(group) for group in groups]
    except SchemaError as exc:
        raise ValidationError("Invalid paired observation or metric") from exc
    if len(parsed) != len({group.group_id for group in parsed}):
        raise ValidationError("Each independent group must appear once")
    totals: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    detail = []
    missing: dict[tuple[str, str], int] = defaultdict(int)
    excluded = 0
    for group in parsed:
        pairs: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
        for observation in group.observations:
            if observation.exclusion:
                excluded += 1
                continue
            seen: set[tuple[str, str]] = set()
            for metric in observation.metrics:
                key = (metric.name, metric.unit)
                if key in seen:
                    raise ValidationError("Duplicate metric for the same paired observation")
                seen.add(key)
                if metric.left is None or metric.right is None:
                    missing[key] += 1
                else:
                    pairs[key].append((metric.left, metric.right))
        estimates = []
        for key, complete in sorted(pairs.items()):
            left_group, right_group = (fmean(side) for side in zip(*complete, strict=True))
            estimate = {
                "name": key[0],
                "unit": key[1],
                "left": left_group,
                "right": right_group,
                "right_minus_left": right_group - left_group,
                "paired_observations": len(complete),
            }
            estimates.append(estimate)
            totals[key].append(estimate)
        detail.append({"group_id": group.group_id, "metrics": estimates})
    if not totals:
        raise ValidationError("No independent group has a supported paired observation")
    metrics = []
    for key in sorted(totals.keys() | missing.keys()):
        contributing = totals[key]
        left = fmean(item["left"] for item in contributing) if contributing else None
        right = fmean(item["right"] for item in contributing) if contributing else None
        metrics.append(
            {
                "name": key[0],
                "unit": key[1],
                "left": left,
                "right": right,
                "right_minus_left": right - left
                if right is not None and left is not None
                else None,
                "groups": len(contributing),
                "paired_observations": sum(item["paired_observations"] for item in contributing),
                "missing_pairs": missing[key],
            }
        )
    return {
        "method": AGGREGATION,
        "metrics": metrics,
        "per_group": detail,
        "excluded_observations": excluded,
        "group_count": len(parsed),
    }


def _source(row: DatasetVersion | Job) -> ComparisonSource:
    if isinstance(row, DatasetVersion):
        if (
            row.status != "complete"
            or canonical_json_sha256(row.manifest_json) != row.manifest_sha256
        ):
            raise ValidationError("The frozen dataset manifest differs from its reviewed digest")
        return ComparisonSource(
            id=UUID(row.id),
            sha256=row.manifest_sha256,
            label=row.name,
            reference_id=UUID(row.id),
            reference_sha256=row.manifest_sha256,
        )
    receipt = row.result_json or {}
    if (
        row.job_type != "reefpose_validation"
        or row.status != "succeeded"
        or receipt.get("split") != "test"
    ):
        raise ValidationError("Choose a completed held-out ReefPose score for each model")
    return ComparisonSource.model_validate(
        {
            "id": row.id,
            "sha256": receipt["result_sha256"],
            "reference_id": receipt["reference_id"],
            "reference_sha256": receipt["reference_sha256"],
            "model_ids": list(receipt["models"]),
            "label": " · ".join(
                (
                    str(receipt.get("rater_id", "Reviewer")),
                    row.id[:8],
                    receipt["reference_sha256"][:10],
                )
            ),
        }
    )


def list_sources(session: Session, project_id: str, task: ComparisonTask) -> list[ComparisonSource]:
    if session.get(Project, project_id) is None:
        raise NotFoundError("Project not found")
    if task in IMAGE_TASKS:
        return [
            _source(row)
            for row in session.scalars(
                select(DatasetVersion)
                .where(DatasetVersion.project_id == project_id, DatasetVersion.status == "complete")
                .order_by(DatasetVersion.version_number.desc())
            )
        ]
    return [
        _source(row)
        for row in session.scalars(
            select(Job)
            .where(
                Job.project_id == project_id,
                Job.job_type == "reefpose_validation",
                Job.status == "succeeded",
            )
            .order_by(Job.completed_at.desc())
        )
        if (row.result_json or {}).get("split") == "test"
    ]


def _inputs(
    session: Session, settings: Settings, project_id: str, request: ComparisonRequest
) -> list[RuntimeSelectionResponse]:
    service = ModelRuntimeService(session, settings)
    choices = []
    for pin in (request.left, request.right):
        selected = service.get(project_id, str(pin.id))
        verified = service.verify(
            project_id, str(pin.id), model_id=str(selected.model_id), digest=pin.sha256
        )
        if verified.snapshot.task not in MODEL_TASKS[request.task]:
            raise ValidationError("The selected model is incompatible with the comparison task")
        choices.append(verified)
    if (
        choices[0].model_id == choices[1].model_id
        or choices[0].snapshot.checkpoint_sha256 == choices[1].snapshot.checkpoint_sha256
    ):
        raise ValidationError("Select two distinct model checkpoints")
    for index, source in enumerate(request.sources):
        row = (
            session.get(DatasetVersion, str(source.id))
            if request.task in IMAGE_TASKS
            else session.get(Job, str(source.id))
        )
        if row is None or row.project_id != project_id:
            raise NotFoundError("Comparison evidence not found in this project")
        if isinstance(row, Job):
            from reefvision.jobs.reefpose_validation import completed_report

            completed_report(session, project_id, row.id)
        current = _source(row)
        if current.sha256 != source.sha256:
            raise ConflictError("The comparison source changed after selection")
        if request.task not in IMAGE_TASKS and current.model_ids != [choices[index].model_id]:
            raise ValidationError("The selected score belongs to a different model")
    return choices


def submit(
    session: Session, settings: Settings, project_id: str, request: ComparisonRequest
) -> Job:
    _inputs(session, settings, project_id, request)
    payload = request.model_dump(mode="json")
    job = Job(
        id=str(uuid4()),
        project_id=project_id,
        job_type=JOB_TYPE,
        status="queued",
        progress_current=0,
        progress_total=1,
        request_json=payload,
    )
    session.add(job)
    session.commit()
    return job


def get_job(session: Session, project_id: str, job_id: str) -> Job:
    row = session.get(Job, job_id)
    if row is None or row.project_id != project_id or row.job_type != JOB_TYPE:
        raise NotFoundError("Paired model comparison not found in project")
    return row


def evaluate(
    session: Session,
    settings: Settings,
    project_id: str,
    request: ComparisonRequest,
    *,
    owner_run_id: str | None = None,
) -> tuple[list[RuntimeSelectionResponse], dict[str, Any], dict[str, Any]]:
    from reefvision.services.model_comparison_stills_v15 import compare_image_models
    from reefvision.services.model_comparison_video_v15 import compare_video_models

    models = _inputs(session, settings, project_id, request)
    task = request.task
    if task == "detector" or task == "mask":
        raw = compare_image_models(
            session,
            settings,
            project_id,
            task,
            {"dataset_version_id": str(request.sources[0].id)},
            [
                {
                    "model_id": str(model.model_id),
                    "checkpoint_sha256": model.snapshot.checkpoint_sha256,
                    **pinned_job_settings(model),
                }
                for model in models
            ],
            owner_run_id=owner_run_id,
        )
    else:
        raw = compare_video_models(
            session,
            project_id,
            task,
            [str(item.id) for item in request.sources],
            [str(model.model_id) for model in models],
        )
    return (
        models,
        ComparisonEvidence.model_validate(raw).model_dump(mode="json"),
        summarize_groups(raw["groups"]),
    )


def process_comparison(settings: Settings, factory: sessionmaker[Session], job_id: str) -> bool:
    with factory() as session:
        claim = session.execute(
            update(Job)
            .where(Job.id == job_id, Job.job_type == JOB_TYPE, Job.status == "queued")
            .values(status="running", started_at=datetime.now(UTC))
        )
        session.commit()
        if not getattr(claim, "rowcount", 0):
            return False
        job = session.get(Job, job_id)
        if not job or not job.project_id:
            raise ValidationError("Comparison has no owning project")
        project_id = job.project_id
        try:
            request = ComparisonRequest.model_validate(job.request_json)
            models, evidence, summary = evaluate(
                session, settings, project_id, request, owner_run_id=job_id
            )
            snapshot = {
                "schema_version": "paired-model-comparison-1.5",
                "project_id": project_id,
                "comparison_id": job.id,
                "selection": request.model_dump(mode="json"),
                "models": [
                    {
                        "model_id": str(model.model_id),
                        "receipt": model.snapshot.model_dump(mode="json"),
                    }
                    for model in models
                ],
                "evidence": evidence,
                "summary": summary,
            }
            session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "running")
                .values(
                    status="succeeded",
                    completed_at=datetime.now(UTC),
                    progress_current=1,
                    result_json={
                        "snapshot": snapshot,
                        "content_sha256": canonical_json_sha256(snapshot),
                        "source_id_map": {},
                    },
                )
            )
        except Exception as exc:
            session.rollback()
            session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "running")
                .values(status="failed", error_message=str(exc), completed_at=datetime.now(UTC))
            )
        session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "cancel_requested")
            .values(status="cancelled", completed_at=datetime.now(UTC), result_json=None)
        )
        session.commit()
    return True


def read_report(session: Session, project_id: str, job_id: str) -> dict[str, Any]:
    job = get_job(session, project_id, job_id)
    result = job.result_json or {}
    if job.status != "succeeded" or "snapshot" not in result:
        raise ConflictError("The comparison has no completed report")
    if canonical_json_sha256(result["snapshot"]) != result.get("content_sha256"):
        raise ConflictError("Stored comparison report checksum mismatch")
    return result


def replay(
    session: Session,
    settings: Settings,
    project_id: str,
    job_id: str,
    digest: str,
    *,
    owner_run_id: str | None = None,
) -> dict[str, Any]:
    result = read_report(session, project_id, job_id)
    if result["content_sha256"] != digest:
        raise ConflictError("The selected comparison digest changed")
    request = ComparisonRequest.model_validate(get_job(session, project_id, job_id).request_json)
    _, replayed, summary = evaluate(
        session, settings, project_id, request, owner_run_id=owner_run_id
    )
    original = result["snapshot"]["evidence"]
    mapping = result["source_id_map"]

    def normalized(groups: list[dict[str, Any]], ids: dict[str, str]) -> dict[str, list[str]]:
        return {
            group["group_id"]: sorted(
                canonical_json_sha256(
                    {**obs, "media_id": ids.get(obs["media_id"], obs["media_id"])}
                )
                for obs in group["observations"]
            )
            for group in groups
        }

    if (
        normalized(original["groups"], mapping) != normalized(replayed["groups"], {})
        or original["evaluation_status"] != replayed["evaluation_status"]
        or summary != result["snapshot"]["summary"]
        or (not mapping and original["source_sha256"] != replayed["source_sha256"])
    ):
        raise ConflictError("Recomputed observations differ from the frozen model comparison")
    return {"snapshot": result["snapshot"], "content_sha256": digest}
