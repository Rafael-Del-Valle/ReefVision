"""Queued and replayable local appearance inference with atomic result publication."""

import math
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, PoseAppearanceStudy, Project
from reefvision.domain.errors import ConflictError, WorkflowExecutionCancelled
from reefvision.repositories.jobs import JobRepository
from reefvision.schemas.pose_appearance import AppearanceRequest
from reefvision.services.pose_appearance import calculate, freeze_inputs, study_row
from reefvision.storage.datasets import canonical_json_sha256

JOB_TYPE = "pose_appearance"
NUMERICAL_TOLERANCE = 0.00001


def _submit(
    session: Session, project: str, operation: UUID, payload: dict[str, Any], device: str
) -> Job:
    session.execute(update(Project).where(Project.id == project).values(id=Project.id))
    identifier = str(uuid5(UUID(project), "reefpose-appearance-" + str(operation)))
    existing = session.get(Job, identifier)
    if existing is not None:
        if existing.job_type != JOB_TYPE or existing.request_json != payload:
            raise ConflictError("This appearance operation already has different pinned inputs")
        return existing
    job = Job(
        id=identifier,
        project_id=project,
        job_type=JOB_TYPE,
        status="queued",
        progress_total=1,
        request_json={**payload, "device": device},
    )
    session.add(job)
    session.commit()
    return job


def submit(session: Session, settings: Settings, project: str, request: AppearanceRequest) -> Job:
    payload = request.model_dump(mode="json")
    identifier = str(uuid5(UUID(project), "reefpose-appearance-" + str(request.operation_id)))
    previous = session.get(Job, identifier)
    if previous is not None and previous.job_type == JOB_TYPE:
        if previous.request_json.get("request_sha256") != canonical_json_sha256(payload):
            raise ConflictError("This appearance operation already has a different request")
        return previous
    inputs = freeze_inputs(session, settings, project, request)
    return _submit(
        session,
        project,
        request.operation_id,
        {
            "inputs": inputs,
            "request_sha256": canonical_json_sha256(payload),
            "device": request.device,
        },
        request.device,
    )


def submit_replay(
    session: Session, project: str, study_id: str, expected: str, operation: UUID
) -> Job:
    row = study_row(session, project, study_id)
    if row.content_sha256 != expected:
        raise ConflictError("The pinned appearance study digest is different")
    device = row.payload_json["inputs"]["request"]["device"]
    return _submit(
        session,
        project,
        operation,
        {"study_id": row.id, "study_sha256": expected, "device": device},
        device,
    )


def equivalent(expected: Any, actual: Any) -> bool:
    if isinstance(expected, (float, int)) and not isinstance(expected, bool):
        return isinstance(actual, (float, int)) and math.isclose(
            expected, actual, rel_tol=0, abs_tol=NUMERICAL_TOLERANCE
        )
    if isinstance(expected, (list, tuple)):
        return (
            isinstance(actual, (list, tuple))
            and len(expected) == len(actual)
            and all(equivalent(a, b) for a, b in zip(expected, actual, strict=True))
        )
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and expected.keys() == actual.keys()
            and all(equivalent(value, actual[key]) for key, value in expected.items())
        )
    return bool(expected == actual)


def replay(
    session: Session, settings: Settings, project: str, row: PoseAppearanceStudy, check: Any
) -> dict[str, Any]:
    result = calculate(
        session, settings, project, row.payload_json["inputs"], row.source_id_map_json, check
    )
    expected = dict(row.payload_json["result"])
    expected.pop("device")
    actual = dict(result)
    actual.pop("device")
    if not equivalent(expected, actual):
        raise ConflictError(
            "Replayed crop pixels, decisions, or scores differ from the frozen study"
        )
    return {
        "study_id": row.id,
        "study_sha256": row.content_sha256,
        "actual_device": result["device"],
        "replayed": True,
        "absolute_tolerance": NUMERICAL_TOLERANCE,
        "result_sha256": canonical_json_sha256(result),
    }


def _enforce_heldout_protocol(session: Session, project: str, snapshot: dict[str, Any]) -> None:
    reference = snapshot["inputs"]["reference"]
    if reference is None:
        return
    testing = {x["video_sha256"] for x in reference["annotation_sources"] if x["split"] == "test"}

    def protocol(value: dict[str, Any]) -> dict[str, Any]:
        req = value["inputs"]["request"]
        return {
            "model": value["inputs"]["model"]["sha256"],
            "algorithm": value["result"]["method"],
            "gap": req["minimum_gap_seconds"],
            "margin": req["minimum_margin"],
            "maximum_false_rate": req["maximum_development_false_rate"],
            "heldout_limits": (
                req.get("maximum_heldout_false_rate"),
                req.get("maximum_heldout_missed_rate"),
            ),
            "reference_labels": sorted(
                (x["split"], x["video_sha256"], x["annotation_sha256"])
                for x in value["inputs"]["reference"]["annotation_sources"]
            ),
            "test_reference": value["inputs"]["reference"]["rater"],
        }

    current = protocol(snapshot)
    for prior in session.scalars(
        select(PoseAppearanceStudy).where(PoseAppearanceStudy.project_id == project)
    ):
        prior_ref = prior.payload_json["inputs"]["reference"]
        if (
            prior_ref
            and prior.payload_json["inputs"]["model"]["sha256"] == current["model"]
            and testing
            & {x["video_sha256"] for x in prior_ref["annotation_sources"] if x["split"] == "test"}
            and protocol(prior.payload_json) != current
        ):
            raise ConflictError(
                "This held-out recording and checkpoint already have a frozen appearance protocol"
            )


def process_appearance(settings: Settings, factory: sessionmaker[Session], job_id: str) -> bool:
    with factory() as session:
        job = JobRepository(session).get_for_update(job_id)
        if (
            job is None
            or job.job_type != JOB_TYPE
            or job.status != "queued"
            or job.project_id is None
        ):
            return False
        job.status = "running"
        job.started_at = datetime.now(UTC)
        session.commit()
        project = job.project_id
        last_check = 0.0

        def check() -> None:
            nonlocal last_check
            now = time.monotonic()
            if now - last_check >= 0.25:
                last_check = now
                if session.scalar(select(Job.status).where(Job.id == job_id)) != "running":
                    raise WorkflowExecutionCancelled("Appearance calculation was cancelled")

        try:
            payload = job.request_json
            if "study_id" in payload:
                row = study_row(session, project, payload["study_id"])
                if row.content_sha256 != payload["study_sha256"]:
                    raise ConflictError("The pinned study has a different digest")
                output = replay(session, settings, project, row, check)
            else:
                inputs = payload["inputs"]
                result = calculate(session, settings, project, inputs, {}, check)
                snapshot = {"inputs": inputs, "result": result}
                session.execute(update(Project).where(Project.id == project).values(id=Project.id))
                _enforce_heldout_protocol(session, project, snapshot)
                row = PoseAppearanceStudy(
                    project_id=project,
                    operation_id=inputs["request"]["operation_id"],
                    model_id=inputs["model"]["id"],
                    reference_id=inputs["request"]["reference_id"],
                    payload_json=snapshot,
                    request_sha256=payload["request_sha256"],
                    content_sha256=canonical_json_sha256(snapshot),
                )
                session.add(row)
                session.flush()
                output = {"study_id": row.id, "study_sha256": row.content_sha256, "replayed": False}
            job = JobRepository(session).get_for_update(job_id)
            if job is None or job.status != "running":
                raise WorkflowExecutionCancelled("Appearance calculation was cancelled")
            job.status = "succeeded"
            job.progress_current = 1
            job.result_json = output
        except Exception as exc:
            session.rollback()
            job = JobRepository(session).get_for_update(job_id)
            if job is None:
                raise
            cancelled = job.status == "cancel_requested" or isinstance(
                exc, WorkflowExecutionCancelled
            )
            job.status = "cancelled" if cancelled else "failed"
            job.error_message = None if cancelled else str(exc)
            job.result_json = None
        job.completed_at = datetime.now(UTC)
        session.commit()
        return True
