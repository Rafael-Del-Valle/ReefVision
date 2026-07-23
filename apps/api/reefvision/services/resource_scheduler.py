"""Deterministic local resource scheduling for queued jobs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import Job

_ACTIVE_STATUSES = (
    "running",
    "pause_requested",
    "cancel_requested",
)


@dataclass(frozen=True, slots=True)
class GPUInventory:
    index: int
    device_id: str
    name: str
    total_bytes: int
    free_bytes: int


@dataclass(frozen=True, slots=True)
class ResourceInventory:
    cpu_count: int
    available_ram_bytes: int | None
    gpus: tuple[GPUInventory, ...]


@dataclass(frozen=True, slots=True)
class ResourceDecision:
    eligible: bool
    assignment: dict[str, Any]
    blockers: tuple[str, ...]


def collect_resource_inventory() -> ResourceInventory:
    cpu_count = max(1, os.cpu_count() or 1)
    available_ram: int | None = None
    try:
        import psutil

        available_ram = int(psutil.virtual_memory().available)
    except Exception:
        pass
    gpus: list[GPUInventory] = []
    try:
        import torch

        if torch.cuda.is_available():
            for index in range(torch.cuda.device_count()):
                properties = torch.cuda.get_device_properties(index)
                try:
                    free_bytes, total_bytes = torch.cuda.mem_get_info(index)
                except Exception:
                    total_bytes = int(properties.total_memory)
                    free_bytes = total_bytes
                gpus.append(
                    GPUInventory(
                        index=index,
                        device_id=f"cuda:{index}",
                        name=str(properties.name),
                        total_bytes=int(total_bytes),
                        free_bytes=int(free_bytes),
                    )
                )
    except Exception:
        pass
    return ResourceInventory(
        cpu_count=cpu_count,
        available_ram_bytes=available_ram,
        gpus=tuple(gpus),
    )


def _assigned_gpu_indices(job: Job) -> list[int]:
    assignment = dict(job.resource_assignment_json or {})
    raw = assignment.get("gpu_indices")
    if isinstance(raw, list):
        return [int(value) for value in raw if isinstance(value, int)]
    single = assignment.get("gpu_index")
    return [single] if isinstance(single, int) else []


def _parse_requested_gpu_indices(value: str) -> list[int] | None:
    normalized = value.strip().casefold()
    if normalized in {"", "auto", "gpu", "cuda"}:
        return None
    tokens = [token.strip() for token in normalized.split(",") if token.strip()]
    indices: list[int] = []
    for token in tokens:
        if token.startswith("cuda:"):
            token = token.split(":", 1)[1]
        if not token.isdigit():
            raise ValueError("invalid CUDA device list")
        index = int(token)
        if index in indices:
            raise ValueError("duplicate CUDA device")
        indices.append(index)
    if not indices:
        raise ValueError("empty CUDA device list")
    return indices


class ResourceScheduler:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _active_reservations(self) -> list[Job]:
        return list(self.session.scalars(select(Job).where(Job.status.in_(_ACTIVE_STATUSES))))

    def evaluate(self, job: Job) -> ResourceDecision:
        requirements = dict(job.resource_requirements_json or {})
        inventory = collect_resource_inventory()
        active = self._active_reservations()
        requested_threads = max(1, int(requirements.get("cpu_threads", 1)))
        requested_ram = max(
            0,
            int(
                requirements.get(
                    "minimum_ram_bytes",
                    requirements.get("ram_bytes", 0),
                )
                or 0
            ),
        )
        reserved_threads = sum(
            max(1, int((item.resource_requirements_json or {}).get("cpu_threads", 1)))
            for item in active
            if item.id != job.id
        )
        reserved_ram = sum(
            max(
                0,
                int(
                    (item.resource_requirements_json or {}).get(
                        "minimum_ram_bytes",
                        (item.resource_requirements_json or {}).get("ram_bytes", 0),
                    )
                    or 0
                ),
            )
            for item in active
            if item.id != job.id
        )
        blockers: list[str] = []
        if requested_threads > max(1, inventory.cpu_count - reserved_threads):
            blockers.append(
                f"Requires {requested_threads} CPU threads; "
                f"{max(0, inventory.cpu_count - reserved_threads)} are unreserved."
            )
        if (
            requested_ram > 0
            and inventory.available_ram_bytes is not None
            and requested_ram > max(0, inventory.available_ram_bytes - reserved_ram)
        ):
            blockers.append(
                f"Requires {requested_ram} RAM bytes; insufficient unreserved memory is available."
            )
        if requirements.get("disk_intensive") and any(
            bool((item.resource_requirements_json or {}).get("disk_intensive"))
            for item in active
            if item.id != job.id
        ):
            blockers.append("Another disk-intensive job is currently running.")

        requested_device = str(requirements.get("device", "auto") or "auto").casefold()
        requested_gpu_count_raw = int(requirements.get("gpu_count", 0) or 0)
        gpu_required = (
            bool(requirements.get("gpu_required", False))
            or requested_gpu_count_raw > 0
            or requested_device.startswith("cuda")
            or requested_device in {"gpu"}
        )
        requested_gpu_count = max(1, requested_gpu_count_raw or 1) if gpu_required else 0
        minimum_vram_per_gpu = max(
            0,
            int(
                requirements.get(
                    "minimum_vram_bytes_per_gpu",
                    requirements.get("minimum_vram_bytes", 0),
                )
                or 0
            ),
        )
        exclusive_gpu = bool(requirements.get("exclusive_gpu", False))
        explicit_indices: list[int] | None = None
        if gpu_required:
            try:
                explicit_indices = _parse_requested_gpu_indices(requested_device)
            except ValueError:
                blockers.append("The requested CUDA device list is invalid.")
            if explicit_indices is not None:
                if requested_gpu_count_raw and len(explicit_indices) != requested_gpu_count:
                    blockers.append(
                        "The explicit CUDA device list does not match the requested gpu_count."
                    )
                requested_gpu_count = len(explicit_indices)

        selected_gpus: list[GPUInventory] = []
        if gpu_required:
            reserved_by_gpu: dict[int, int] = {}
            exclusive_gpus: set[int] = set()
            assigned_gpus: set[int] = set()
            for active_job in active:
                if active_job.id == job.id:
                    continue
                active_requirements = dict(active_job.resource_requirements_json or {})
                active_vram_per_gpu = max(
                    0,
                    int(
                        active_requirements.get(
                            "minimum_vram_bytes_per_gpu",
                            active_requirements.get("minimum_vram_bytes", 0),
                        )
                        or 0
                    ),
                )
                for gpu_index in _assigned_gpu_indices(active_job):
                    assigned_gpus.add(gpu_index)
                    reserved_by_gpu[gpu_index] = (
                        reserved_by_gpu.get(gpu_index, 0) + active_vram_per_gpu
                    )
                    if bool(active_requirements.get("exclusive_gpu", False)):
                        exclusive_gpus.add(gpu_index)

            candidates = list(inventory.gpus)
            if explicit_indices is not None:
                by_index = {item.index: item for item in candidates}
                missing = [index for index in explicit_indices if index not in by_index]
                if missing:
                    blockers.append(
                        "Requested CUDA devices are unavailable: "
                        + ", ".join(str(index) for index in missing)
                    )
                candidates = [by_index[index] for index in explicit_indices if index in by_index]

            candidates = [
                item
                for item in candidates
                if item.index not in exclusive_gpus
                and (not exclusive_gpu or item.index not in assigned_gpus)
                and item.free_bytes - reserved_by_gpu.get(item.index, 0)
                >= minimum_vram_per_gpu
            ]
            if explicit_indices is None:
                candidates.sort(
                    key=lambda item: (
                        -(item.free_bytes - reserved_by_gpu.get(item.index, 0)),
                        item.index,
                    )
                )
            else:
                explicit_order = {index: position for position, index in enumerate(explicit_indices)}
                candidates.sort(key=lambda item: explicit_order[item.index])

            if len(candidates) >= requested_gpu_count:
                selected_gpus = candidates[:requested_gpu_count]
            elif not blockers:
                blockers.append(
                    f"Requires {requested_gpu_count} compatible GPUs; "
                    f"only {len(candidates)} satisfy VRAM and exclusivity requirements."
                )

        assignment: dict[str, Any] = {
            "assigned_at": datetime.now(UTC).isoformat(),
            "cpu_threads": requested_threads,
            "reserved_ram_bytes": requested_ram,
            "scheduler": "reefvision-local-v2",
        }
        if selected_gpus:
            gpu_indices = [item.index for item in selected_gpus]
            assignment_device = (
                selected_gpus[0].device_id
                if len(selected_gpus) == 1
                else ",".join(str(index) for index in gpu_indices)
            )
            assignment.update(
                {
                    "device": assignment_device,
                    "gpu_index": gpu_indices[0],
                    "gpu_indices": gpu_indices,
                    "gpu_count": len(selected_gpus),
                    "gpu_name": selected_gpus[0].name,
                    "gpu_names": [item.name for item in selected_gpus],
                    "gpu_total_bytes": selected_gpus[0].total_bytes,
                    "gpu_total_bytes_by_device": [item.total_bytes for item in selected_gpus],
                    "gpu_free_bytes_at_assignment": selected_gpus[0].free_bytes,
                    "gpu_free_bytes_by_device_at_assignment": [
                        item.free_bytes for item in selected_gpus
                    ],
                    "reserved_vram_bytes": minimum_vram_per_gpu,
                    "reserved_vram_bytes_per_gpu": minimum_vram_per_gpu,
                    "exclusive_gpu": exclusive_gpu,
                    "cuda_visible_devices": ",".join(str(index) for index in gpu_indices),
                }
            )
        else:
            assignment.update(
                {
                    "device": "cpu",
                    "gpu_index": None,
                    "gpu_indices": [],
                    "gpu_count": 0,
                }
            )
        return ResourceDecision(
            eligible=not blockers,
            assignment=assignment,
            blockers=tuple(blockers),
        )
