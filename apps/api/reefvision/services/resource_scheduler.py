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
        gpu_required = (
            bool(requirements.get("gpu_required", False))
            or requested_device.startswith("cuda")
            or requested_device in {"gpu"}
        )
        minimum_vram = max(0, int(requirements.get("minimum_vram_bytes", 0) or 0))
        exclusive_gpu = bool(requirements.get("exclusive_gpu", False))
        selected_gpu: GPUInventory | None = None
        if gpu_required:
            reserved_by_gpu: dict[int, int] = {}
            exclusive_gpus: set[int] = set()
            for active_job in active:
                if active_job.id == job.id:
                    continue
                active_assignment = dict(active_job.resource_assignment_json or {})
                gpu_index = active_assignment.get("gpu_index")
                if not isinstance(gpu_index, int):
                    continue
                active_requirements = dict(active_job.resource_requirements_json or {})
                reserved_by_gpu[gpu_index] = reserved_by_gpu.get(gpu_index, 0) + max(
                    0,
                    int(active_requirements.get("minimum_vram_bytes", 0) or 0),
                )
                if bool(active_requirements.get("exclusive_gpu", False)):
                    exclusive_gpus.add(gpu_index)
            candidates = list(inventory.gpus)
            if requested_device.startswith("cuda:"):
                try:
                    requested_index = int(requested_device.split(":", 1)[1])
                    candidates = [item for item in candidates if item.index == requested_index]
                except ValueError:
                    blockers.append("The requested CUDA device identifier is invalid.")
                    candidates = []
            candidates = [
                item
                for item in candidates
                if item.index not in exclusive_gpus
                and (
                    not exclusive_gpu
                    or not any(
                        (active_job.resource_assignment_json or {}).get("gpu_index") == item.index
                        for active_job in active
                        if active_job.id != job.id
                    )
                )
                and item.free_bytes - reserved_by_gpu.get(item.index, 0) >= minimum_vram
            ]
            if candidates:
                selected_gpu = max(
                    candidates,
                    key=lambda item: (
                        item.free_bytes - reserved_by_gpu.get(item.index, 0),
                        -item.index,
                    ),
                )
            elif not blockers:
                blockers.append("No compatible GPU has the requested free VRAM and exclusivity.")

        assignment: dict[str, Any] = {
            "assigned_at": datetime.now(UTC).isoformat(),
            "cpu_threads": requested_threads,
            "reserved_ram_bytes": requested_ram,
            "scheduler": "reefvision-local-v1",
        }
        if selected_gpu is not None:
            assignment.update(
                {
                    "device": selected_gpu.device_id,
                    "gpu_index": selected_gpu.index,
                    "gpu_name": selected_gpu.name,
                    "gpu_total_bytes": selected_gpu.total_bytes,
                    "gpu_free_bytes_at_assignment": selected_gpu.free_bytes,
                    "reserved_vram_bytes": minimum_vram,
                    "exclusive_gpu": exclusive_gpu,
                }
            )
        else:
            assignment.update({"device": "cpu", "gpu_index": None})
        return ResourceDecision(
            eligible=not blockers,
            assignment=assignment,
            blockers=tuple(blockers),
        )
