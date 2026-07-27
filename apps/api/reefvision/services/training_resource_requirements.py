"""Translate persisted training resource limits into scheduler reservations."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from reefvision.db.models import Job, TrainingRun
from reefvision.domain.errors import NotFoundError, ValidationError

_GIB = 1024**3


def _positive_int(value: object, *, default: int, name: str) -> int:
    candidate: str | bytes | bytearray | int | float
    if value is None:
        candidate = default
    elif isinstance(value, (str, bytes, bytearray, int, float)):
        candidate = value
    else:
        raise ValidationError(f"{name} must be an integer")
    try:
        result = int(candidate)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be an integer") from exc
    if result < 0:
        raise ValidationError(f"{name} cannot be negative")
    return result


def _gib_to_bytes(value: object, *, name: str) -> int:
    if not isinstance(value, (str, bytes, bytearray, int, float)):
        raise ValidationError(f"{name} must be a number")
    try:
        amount = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be a number") from exc
    if amount < 0:
        raise ValidationError(f"{name} cannot be negative")
    return int(amount * _GIB)


def training_scheduler_requirements(run: TrainingRun) -> dict[str, Any]:
    limits = dict(run.resource_limits_json or {})
    configured_devices = limits.get("allowed_devices")
    requested_device = run.device
    if isinstance(configured_devices, list) and configured_devices:
        normalized = [str(item).strip() for item in configured_devices if str(item).strip()]
        if requested_device == "auto" and len(normalized) == 1:
            requested_device = normalized[0]

    gpu_count = _positive_int(limits.get("gpu_count"), default=0, name="gpu_count")
    normalized_device = requested_device.strip().casefold()
    if gpu_count == 0 and (
        normalized_device.startswith("cuda")
        or normalized_device in {"gpu"}
        or bool(normalized_device and normalized_device[0].isdigit())
    ):
        gpu_count = max(1, len([item for item in requested_device.split(",") if item.strip()]))
    gpu_preferred = (
        normalized_device == "auto" and gpu_count == 0 and bool(limits.get("prefer_gpu", True))
    )
    minimum_vram_bytes_per_gpu = limits.get("minimum_vram_bytes_per_gpu")
    if minimum_vram_bytes_per_gpu is None and limits.get("minimum_vram_gb_per_gpu") is not None:
        minimum_vram_bytes_per_gpu = _gib_to_bytes(
            limits["minimum_vram_gb_per_gpu"],
            name="minimum_vram_gb_per_gpu",
        )
    minimum_vram_bytes_per_gpu = _positive_int(
        minimum_vram_bytes_per_gpu,
        default=0,
        name="minimum_vram_bytes_per_gpu",
    )
    minimum_ram_bytes = limits.get("minimum_ram_bytes")
    if minimum_ram_bytes is None and limits.get("minimum_ram_gb") is not None:
        minimum_ram_bytes = _gib_to_bytes(
            limits["minimum_ram_gb"],
            name="minimum_ram_gb",
        )
    minimum_ram_bytes = _positive_int(
        minimum_ram_bytes,
        default=0,
        name="minimum_ram_bytes",
    )
    cpu_threads = _positive_int(
        limits.get("cpu_threads", limits.get("max_workers", 2)),
        default=2,
        name="cpu_threads",
    )
    return {
        "device": requested_device,
        "gpu_required": gpu_count > 0,
        "gpu_preferred": gpu_preferred,
        "gpu_count": gpu_count,
        "minimum_vram_bytes_per_gpu": minimum_vram_bytes_per_gpu,
        "minimum_ram_bytes": minimum_ram_bytes,
        "cpu_threads": max(1, cpu_threads),
        "exclusive_gpu": bool(limits.get("exclusive_gpu", gpu_count > 0 or gpu_preferred)),
        "disk_intensive": bool(limits.get("disk_intensive", True)),
    }


def apply_training_scheduler_requirements(
    session: Session,
    run_id: str,
) -> dict[str, Any]:
    run = session.get(TrainingRun, run_id)
    if run is None:
        raise NotFoundError("Training run not found")
    if run.job_id is None:
        raise ValidationError("Training run has no queued background job")
    job = session.get(Job, run.job_id)
    if job is None:
        raise NotFoundError("Training background job not found")
    if job.status not in {"queued", "blocked"}:
        raise ValidationError("Training resources can be configured only before execution")
    requirements = training_scheduler_requirements(run)
    job.resource_requirements_json = requirements
    job.request_json = {
        **dict(job.request_json or {}),
        "requested_training_device": run.device,
        "requested_gpu_count": requirements["gpu_count"],
    }
    session.commit()
    session.refresh(job)
    return requirements
