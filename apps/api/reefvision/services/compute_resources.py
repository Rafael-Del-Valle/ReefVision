"""Reserve local CPU or GPU capacity before handing a job to its usual processor."""

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Literal
from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from reefvision.db.models import (
    Job,
    PoseAppearanceStudy,
    Project,
    TrainingRun,
    WorkflowNodeRun,
    WorkflowRun,
)
from reefvision.db.models.job import LocalComputeLease, LocalComputeLimits
from reefvision.domain.errors import NotFoundError
from reefvision.repositories.jobs import JobRepository
from reefvision.schemas.jobs import (
    ComputeJob,
    ComputeJobPage,
    ComputeLimitsRequest,
    ComputeResources,
    JobResponse,
)
from reefvision.services.jobs import RUNNING_CANCELLABLE_JOB_TYPES, supports_retry

Pool = Literal["cpu", "gpu"]

# These jobs run their own nested provider steps inside a single reservation.
ORCHESTRATORS = {"workflow_run", "paired_model_comparison", "domain_shift_analysis"}
EXCLUSIVE = {"backup", "restore"}
MODEL_JOBS = {
    "inference",
    "training",
    "sam_image_proposals",
    "classification_inference",
    "classification_training",
    "video_tracking",
    "video_metric_depth_3d",
    "pose_evaluation",
    "temporal_reefpose",
    "pose_appearance",
    "reefpose_validation",
    "paired_model_comparison",
    "domain_shift_analysis",
    "static_comparison",
}
MODEL_NODES = MODEL_JOBS | {
    "pose_model_training",
    "model_training",
    "pose_inference",
    "detection_inference",
    "segmentation_inference",
    "semantic_segmentation_inference",
    "pose_appearance_study",
    "reefpose_appearance_replay",
    "temporal_reefpose_training",
    "temporal_reefpose_inference",
    "temporal_reefpose_evaluation",
    "prompt_assist_masks",
    "relative_depth_estimation",
    "video_metric_depth_3d",
}


@dataclass(frozen=True)
class Claim:
    job_id: str
    job_type: str
    pool: Pool
    token: str


@lru_cache(maxsize=1)
def _automatic_pool() -> Pool:
    from reefvision.domain.errors import ValidationError
    from reefvision.ml.providers import resolve_torch_device

    try:
        return "cpu" if resolve_torch_device("auto") == "cpu" else "gpu"
    except ValidationError:
        return "cpu"


def _device_pool(value: object) -> Pool:
    device = str(value or "auto").lower()
    if device in {"auto", ""}:
        return _automatic_pool()
    return "cpu" if device == "cpu" else "gpu"


def job_pool(session: Session, job: Job) -> Pool:
    if job.job_type == "workflow_run":
        nodes = select(WorkflowNodeRun).join(WorkflowRun).where(WorkflowRun.job_id == job.id)
        if job.status in {"queued", "running", "waiting_for_review"}:
            nodes = nodes.where(WorkflowNodeRun.status != "succeeded")
        for node in session.scalars(nodes):
            if node.node_type not in MODEL_NODES:
                continue
            device = node.parameters_json.get("device")
            if node.node_type == "reefpose_appearance_replay" and node.parameters_json.get(
                "study_id"
            ):
                study = session.get(PoseAppearanceStudy, node.parameters_json["study_id"])
                if study and study.project_id == job.project_id:
                    device = study.payload_json.get("inputs", {}).get("request", {}).get("device")
            if _device_pool(device) == "gpu":
                return "gpu"
        return "cpu"
    if job.job_type not in MODEL_JOBS:
        return "cpu"
    if job.job_type == "training":
        device = session.scalar(select(TrainingRun.device).where(TrainingRun.job_id == job.id))
        if device is not None:
            return _device_pool(device)
    return _device_pool(job.request_json.get("device"))


def _lock_dispatch(session: Session) -> None:
    # The profile database is SQLite. Acquire its writer lock before counting or changing slots.
    connection = session.connection()
    if connection.dialect.name == "sqlite":
        if not getattr(connection.connection.driver_connection, "in_transaction", False):
            connection.exec_driver_sql("BEGIN IMMEDIATE")
    else:
        session.execute(select(LocalComputeLimits).with_for_update())


def _limits(session: Session) -> ComputeLimitsRequest:
    saved = session.get(LocalComputeLimits, 1)
    return ComputeLimitsRequest(
        cpu_slots=saved.cpu_slots if saved else 1, gpu_slots=saved.gpu_slots if saved else 1
    )


def resources(session: Session) -> ComputeResources:
    occupied = {
        pool: count
        for pool, count in session.execute(
            select(LocalComputeLease.pool, func.count()).group_by(LocalComputeLease.pool)
        )
    }
    return ComputeResources(
        **_limits(session).model_dump(),
        cpu_in_use=occupied.get("cpu", 0),
        gpu_in_use=occupied.get("gpu", 0),
    )


def set_limits(session: Session, limits: ComputeLimitsRequest) -> ComputeResources:
    _lock_dispatch(session)
    session.merge(LocalComputeLimits(id=1, **limits.model_dump()))
    session.commit()
    return resources(session)


def _active(session: Session) -> list[tuple[LocalComputeLease, Job]]:
    return [
        (lease, job) for lease, job in session.execute(select(LocalComputeLease, Job).join(Job))
    ]


def _waiting(
    job: Job,
    pool: Pool,
    limits: ComputeLimitsRequest,
    active: list[tuple[LocalComputeLease, Job]],
    occupied: Counter[str],
) -> str | None:
    if any(other.job_type in EXCLUSIVE for _, other in active) or (
        active and job.job_type in EXCLUSIVE
    ):
        return "Waiting for exclusive access to the local profile."
    for _, parent in active:
        if parent.project_id == job.project_id and parent.job_type in ORCHESTRATORS:
            if job.request_json.get("created_by_workflow") or job.request_json.get(
                "paired_owner_run_id"
            ):
                return "Its parent workflow holds the compute slot."
            # Some older adapters commit a child before attaching its parent identifiers.
            if job.job_type in MODEL_JOBS:
                return "The current project workflow is using its provider."
    capacity = limits.cpu_slots if pool == "cpu" else limits.gpu_slots
    if capacity == 0:
        return f"The {pool.upper()} queue is paused."
    if occupied[pool] >= capacity:
        return f"Waiting for a free {pool.upper()} slot."
    return None


def claim_next(factory: sessionmaker[Session]) -> Claim | None:
    with factory() as session:
        queue = JobRepository.queued_statement().where(
            ~Job.id.in_(select(LocalComputeLease.job_id))
        )
        if session.scalar(queue.limit(1)) is None:
            return None
        _lock_dispatch(session)
        limits = _limits(session)
        active = _active(session)
        occupied = Counter(lease.pool for lease, _ in active)
        for job in session.scalars(queue.execution_options(yield_per=64, populate_existing=True)):
            pool = job_pool(session, job)
            reason = _waiting(job, pool, limits, active, occupied)
            if reason:
                if active and job.job_type in EXCLUSIVE and limits.cpu_slots:
                    break
                continue
            token = str(uuid4())
            now = datetime.now(UTC)
            session.add(
                LocalComputeLease(
                    job_id=job.id, token=token, pool=pool, claimed_at=now, heartbeat_at=now
                )
            )
            session.commit()
            return Claim(job.id, job.job_type, pool, token)
    return None


def release(factory: sessionmaker[Session], claim: Claim) -> None:
    with factory() as session:
        session.execute(
            delete(LocalComputeLease).where(
                LocalComputeLease.job_id == claim.job_id, LocalComputeLease.token == claim.token
            )
        )
        session.commit()


def heartbeat(factory: sessionmaker[Session], tokens: list[str]) -> None:
    with factory() as session:
        session.execute(
            update(LocalComputeLease)
            .where(LocalComputeLease.token.in_(tokens))
            .values(heartbeat_at=datetime.now(UTC))
        )
        session.commit()


def list_jobs(session: Session, project_id: str, limit: int, offset: int) -> ComputeJobPage:
    if session.get(Project, project_id) is None:
        raise NotFoundError("Project not found")
    limits = _limits(session)
    active = _active(session)
    leases = {row.job_id: row for row, _ in active}
    occupied = Counter(row.pool for row, _ in active)
    total = (
        session.scalar(select(func.count()).select_from(Job).where(Job.project_id == project_id))
        or 0
    )
    page = session.scalars(
        select(Job)
        .where(Job.project_id == project_id)
        .order_by(Job.created_at.desc(), Job.id.desc())
        .offset(offset)
        .limit(limit)
    )
    entries: list[ComputeJob] = []
    for job in page:
        lease = leases.get(job.id)
        pool: Pool = ("gpu" if lease.pool == "gpu" else "cpu") if lease else job_pool(session, job)
        reason = (
            _waiting(job, pool, limits, active, occupied)
            if job.status == "queued" and lease is None
            else None
        )
        training = (
            session.scalar(select(TrainingRun).where(TrainingRun.job_id == job.id))
            if job.job_type == "training" and job.status in {"failed", "cancelled"}
            else None
        )
        workflow_checkpoint = False
        if job.status == "failed" and job.job_type == "workflow_run":
            workflow_checkpoint = (
                session.scalar(
                    select(WorkflowNodeRun.id)
                    .join(WorkflowRun)
                    .where(WorkflowRun.job_id == job.id, WorkflowNodeRun.status == "succeeded")
                    .limit(1)
                )
                is not None
            )
        entries.append(
            ComputeJob(
                job=JobResponse.model_validate(job),
                pool=pool,
                admission="reserved"
                if lease
                else "waiting"
                if reason
                else "ready"
                if job.status == "queued"
                else "inactive",
                reason=reason,
                heartbeat_at=lease.heartbeat_at.replace(tzinfo=UTC) if lease else None,
                can_retry=supports_retry(job, training),
                can_cancel=job.status in {"queued", "waiting_for_review"}
                or (job.status == "running" and job.job_type in RUNNING_CANCELLABLE_JOB_TYPES),
                checkpoint_available=workflow_checkpoint
                or bool(
                    training
                    and training.provider_id == "reefpose"
                    and training.artifact_manifest_json.get("resume_checkpoint_sha256")
                ),
            )
        )
    return ComputeJobPage(items=entries, total=total)
