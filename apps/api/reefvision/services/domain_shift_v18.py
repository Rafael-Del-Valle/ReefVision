"""Evaluate two declared acquisition domains using frozen grouped still evidence."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.domain_shift_v18 import DomainShiftDraft
from reefvision.schemas.image_adjustments_v18 import ImageAdjustmentPin
from reefvision.schemas.paired_models_v15 import ComparisonEvidence, ComparisonRequest
from reefvision.services.domain_shift_metrics_v18 import Lineage, summarize_domain_shift
from reefvision.services.model_comparison_stills_v15 import (
    ComparisonLineageOverlap,
    RecordedImageRuns,
    compare_image_models,
)
from reefvision.services.model_runtime import pinned_job_settings
from reefvision.services.paired_models_v15 import (
    _inputs,
    _normalized_groups,
)
from reefvision.services.paired_models_v15 import (
    get_job as get_comparison,
)
from reefvision.services.paired_models_v15 import (
    read_report as read_comparison,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.model_comparison_stills_v15 import read_comparison_raster

JOB_TYPE = "domain_shift_analysis"
VERSION = "domain-shift-0001"


def _source(session: Session, project_id: str, comparison_id: str) -> tuple[Job, dict[str, Any]]:
    source = get_comparison(session, project_id, comparison_id)
    result = read_comparison(session, project_id, comparison_id)
    snapshot = result["snapshot"]
    if snapshot["selection"]["task"] not in {"detector", "mask"}:
        raise ValidationError(
            "Domain shift uses a completed box or mask comparison of grouped stills"
        )
    if len(snapshot["evidence"].get("inference_job_ids", [])) != 2:
        raise ConflictError(
            "Create a new paired comparison with both original evaluation jobs pinned"
        )
    return source, result


def inspect_source(session: Session, project_id: str, comparison_id: str) -> dict[str, Any]:
    _, result = _source(session, project_id, comparison_id)
    snapshot = result["snapshot"]
    aliases = result.get("source_id_map", {})
    evidence = snapshot["evidence"]
    return {
        "id": comparison_id,
        "content_sha256": result["content_sha256"],
        "task": snapshot["selection"]["task"],
        "reference_sha256": evidence["reference_sha256"],
        "lineage": evidence["evaluation_status"],
        "model_labels": [row["receipt"]["display_name"] for row in snapshot["models"]],
        "groups": [
            {
                "group_id": group["group_id"],
                "images": [
                    {
                        "id": aliases.get(row["media_id"], row["media_id"]),
                        "exclusion": row.get("exclusion"),
                    }
                    for row in group["observations"]
                ],
            }
            for group in evidence["groups"]
        ],
    }


def list_sources(
    session: Session, project_id: str, offset: int, limit: int
) -> list[dict[str, Any]]:
    candidates = session.scalars(
        select(Job.id)
        .where(
            Job.project_id == project_id,
            Job.job_type == "paired_model_comparison",
            Job.status == "succeeded",
            Job.result_json["snapshot"]["selection"]["task"].as_string().in_(("detector", "mask")),
        )
        .order_by(Job.created_at.desc(), Job.id)
    ).yield_per(50)
    result = []
    for comparison_id in candidates:
        try:
            source = inspect_source(session, project_id, comparison_id)
        except (ValidationError, ConflictError):
            continue
        if offset:
            offset -= 1
            continue
        result.append({key: value for key, value in source.items() if key != "groups"})
        if len(result) == limit:
            break
    return result


def get_job(session: Session, project_id: str, job_id: str) -> Job:
    job = session.get(Job, job_id)
    if job is None or job.project_id != project_id or job.job_type != JOB_TYPE:
        raise NotFoundError("Domain shift analysis was not found in this project")
    return job


def _check_source(
    session: Session, project_id: str, draft: DomainShiftDraft
) -> tuple[Job, dict[str, Any]]:
    source, result = _source(session, project_id, str(draft.comparison_id))
    if result["content_sha256"] != draft.comparison_sha256:
        raise ConflictError("The saved paired comparison no longer matches the selected digest")
    return source, result


def submit(session: Session, project_id: str, draft: DomainShiftDraft) -> Job:
    _check_source(session, project_id, draft)
    row = Job(
        project_id=project_id,
        job_type=JOB_TYPE,
        status="queued",
        progress_total=1,
        request_json=draft.model_dump(mode="json"),
    )
    session.add(row)
    session.commit()
    return row


def evaluate(
    session: Session,
    settings: Settings,
    project_id: str,
    draft: DomainShiftDraft,
    *,
    owner_run_id: str,
) -> dict[str, Any]:
    job, previous = _check_source(session, project_id, draft)
    source = previous["snapshot"]
    evidence = source["evidence"]
    original_request = ComparisonRequest.model_validate(source["selection"])
    live_request = ComparisonRequest.model_validate(job.request_json)
    aliases = previous.get("source_id_map", {})
    if live_request.task != original_request.task or any(
        str(new.id) != aliases.get(str(old.id), str(old.id))
        for new, old in zip(
            [live_request.left, live_request.right, *live_request.sources],
            [original_request.left, original_request.right, *original_request.sources],
            strict=True,
        )
    ):
        raise ConflictError("The source comparison no longer points to its reviewed selections")
    models = _inputs(session, settings, project_id, live_request)
    if any(
        model.snapshot.model_dump(mode="json") != archived["receipt"]
        or str(model.model_id) != aliases.get(archived["model_id"], archived["model_id"])
        for model, archived in zip(models, source["models"], strict=True)
    ):
        raise ConflictError("The source comparison's reviewed model bindings changed")
    selected = [
        {
            "model_id": str(model.model_id),
            "checkpoint_sha256": model.snapshot.checkpoint_sha256,
            **pinned_job_settings(model),
        }
        for model in models
    ]
    baseline_job_ids = tuple(aliases.get(value, value) for value in evidence["inference_job_ids"])
    current_plan = {"dataset_version_id": str(live_request.sources[0].id)}
    args = (session, settings, project_id, live_request.task, current_plan, selected)
    archival_ids = {value: key for key, value in aliases.items()}
    current: dict[str, Any] = evidence
    lineage: Lineage = "overlap"
    reasons = []
    try:
        baseline_raw = compare_image_models(
            *args,
            recorded=RecordedImageRuns(
                (baseline_job_ids[0], baseline_job_ids[1]),
                lambda path: read_comparison_raster(settings, path),
                archival_ids,
                datetime.now(UTC),
            ),
        )
        baseline = ComparisonEvidence.model_validate(baseline_raw).model_dump(mode="json")
        if (
            baseline["source_sha256"] != evidence["source_sha256"]
            or baseline["reference_sha256"] != live_request.sources[0].sha256
            or _normalized_groups(baseline["groups"], {})
            != _normalized_groups(evidence["groups"], aliases)
        ):
            raise ConflictError(
                "Archived paired scores differ from their checked evaluation outputs"
            )
        current = baseline
        lineage = (
            "held_out"
            if baseline["evaluation_status"] == evidence["evaluation_status"] == "held_out"
            else "exploratory"
        )
        if lineage == "exploratory":
            reasons.append("Complete disjoint training and model-selection ancestry is unavailable")
        elif draft.preprocessing == "adjusted":
            current = compare_image_models(
                *args,
                owner_run_id=owner_run_id,
                adjusted_inputs={
                    str(pin.image_id): ImageAdjustmentPin.model_validate(
                        pin.model_dump(exclude={"image_id"})
                    )
                    for pin in draft.adjustments
                },
            )
            lineage = current["evaluation_status"]
    except ComparisonLineageOverlap as exc:
        reasons.append(str(exc))
        lineage = "overlap"
    observed = ComparisonEvidence.model_validate(current).model_dump(mode="json")
    return {
        "schema_version": VERSION,
        "project_id": project_id,
        "declaration": draft.model_dump(mode="json"),
        "reference": {
            "id": current_plan["dataset_version_id"],
            "manifest_sha256": live_request.sources[0].sha256,
            "original_manifest_sha256": evidence["reference_sha256"],
            "split": "test",
        },
        "models": [
            {
                "id": str(model.model_id),
                "runtime_id": str(model.id),
                "runtime_sha256": model.content_sha256,
                "checkpoint_sha256": model.snapshot.checkpoint_sha256,
                "class_mapping": model.snapshot.model_dump(mode="json")["class_mapping"],
                "label": model.snapshot.display_name,
            }
            for model in models
        ],
        "observed_evidence": observed,
        "preprocessing_executed": draft.preprocessing if lineage == "held_out" else "unscored",
        "lineage_reasons": reasons,
        "summary": summarize_domain_shift(draft, observed["groups"], lineage),
    }


def process_domain_shift(settings: Settings, factory: sessionmaker[Session], job_id: str) -> bool:
    with factory() as session:
        claim = session.execute(
            update(Job)
            .where(Job.id == job_id, Job.job_type == JOB_TYPE, Job.status == "queued")
            .values(status="running", started_at=datetime.now(UTC), error_message=None)
        )
        session.commit()
        if not getattr(claim, "rowcount", 0):
            return False
        row = session.get(Job, job_id)
        if row is None or row.project_id is None:
            raise ValidationError("The domain shift analysis has no owning project")
        project_id = row.project_id
        try:
            draft = DomainShiftDraft.model_validate(row.request_json)
            snapshot = evaluate(session, settings, project_id, draft, owner_run_id=row.id)
        except (ConflictError, ValidationError, NotFoundError, ValueError) as exc:
            session.rollback()
            session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "running")
                .values(status="failed", error_message=str(exc), completed_at=datetime.now(UTC))
            )
        else:
            session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "running")
                .values(
                    status="succeeded",
                    progress_current=1,
                    completed_at=datetime.now(UTC),
                    result_json={
                        "snapshot": snapshot,
                        "content_sha256": canonical_json_sha256(snapshot),
                    },
                )
            )
        session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "cancel_requested")
            .values(status="cancelled", completed_at=datetime.now(UTC), result_json=None)
        )
        session.commit()
        return True


def read_report(
    session: Session, project_id: str, job_id: str, digest: str | None = None
) -> dict[str, Any]:
    row = get_job(session, project_id, job_id)
    result = row.result_json or {}
    if row.status != "succeeded" or "snapshot" not in result:
        raise ConflictError("The domain shift analysis has no frozen report")
    snapshot = result["snapshot"]
    if canonical_json_sha256(snapshot) != result.get("content_sha256") or (
        digest is not None and digest != result["content_sha256"]
    ):
        raise ConflictError("The domain shift report checksum does not match")
    draft = DomainShiftDraft.model_validate(row.request_json)
    _check_source(session, project_id, draft)
    if (
        summarize_domain_shift(
            DomainShiftDraft.model_validate(snapshot["declaration"]),
            snapshot["observed_evidence"]["groups"],
            snapshot["summary"]["lineage"],
        )
        != snapshot["summary"]
    ):
        raise ConflictError("Frozen domain shift estimates differ from their held-out scores")
    return result
