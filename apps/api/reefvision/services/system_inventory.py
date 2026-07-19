"""Comprehensive, read-only runtime inventory for diagnostics and acceptance."""

from __future__ import annotations

import os
import platform
import sqlite3
import sys
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job
from reefvision.services.resource_scheduler import collect_resource_inventory

_RELEVANT_PACKAGES = (
    "reefvision",
    "fastapi",
    "uvicorn",
    "sqlalchemy",
    "alembic",
    "pydantic",
    "pydantic-settings",
    "numpy",
    "pillow",
    "opencv-python",
    "torch",
    "torchvision",
    "ultralytics",
    "segment-anything",
    "mobile-sam",
    "sam2",
    "transformers",
    "timm",
    "nnunetv2",
    "scipy",
    "scikit-learn",
    "pandas",
    "psutil",
)


def _package_versions() -> dict[str, str | None]:
    output: dict[str, str | None] = {}
    for name in _RELEVANT_PACKAGES:
        try:
            output[name] = version(name)
        except PackageNotFoundError:
            output[name] = None
    return output


def _memory_inventory() -> dict[str, Any]:
    try:
        import psutil

        virtual = psutil.virtual_memory()
        swap = psutil.swap_memory()
        process = psutil.Process()
        return {
            "total_bytes": int(virtual.total),
            "available_bytes": int(virtual.available),
            "used_bytes": int(virtual.used),
            "percent_used": float(virtual.percent),
            "swap_total_bytes": int(swap.total),
            "swap_used_bytes": int(swap.used),
            "process_rss_bytes": int(process.memory_info().rss),
            "process_vms_bytes": int(process.memory_info().vms),
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _cpu_inventory() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "logical_count": os.cpu_count(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
    }
    try:
        import psutil

        frequency = psutil.cpu_freq()
        payload.update(
            {
                "physical_count": psutil.cpu_count(logical=False),
                "current_frequency_mhz": float(frequency.current) if frequency else None,
                "maximum_frequency_mhz": float(frequency.max) if frequency else None,
                "load_percent": float(psutil.cpu_percent(interval=0.05)),
            }
        )
    except Exception:
        pass
    return payload


def _gpu_inventory() -> list[dict[str, Any]]:
    inventory = collect_resource_inventory()
    output = [
        {
            "device_id": item.device_id,
            "index": item.index,
            "name": item.name,
            "total_bytes": item.total_bytes,
            "free_bytes": item.free_bytes,
        }
        for item in inventory.gpus
    ]
    try:
        import torch

        for item in output:
            properties = torch.cuda.get_device_properties(int(item["index"]))
            item.update(
                {
                    "compute_capability": f"{properties.major}.{properties.minor}",
                    "multi_processor_count": int(properties.multi_processor_count),
                    "torch_cuda_version": torch.version.cuda,
                    "cudnn_version": (
                        int(torch.backends.cudnn.version())
                        if torch.backends.cudnn.is_available()
                        else None
                    ),
                }
            )
    except Exception:
        pass
    return output


def _filesystem_inventory(settings: Settings) -> dict[str, Any]:
    import shutil

    usage = shutil.disk_usage(settings.resolved_data_dir)
    database_path: Path | None = None
    try:
        url = make_url(settings.resolved_database_url)
        if url.get_backend_name() == "sqlite" and url.database:
            database_path = Path(url.database)
    except Exception:
        pass
    probe = settings.resolved_data_dir / ".diagnostic-write-probe"
    writable = False
    error: str | None = None
    try:
        probe.write_text("reefvision", encoding="utf-8")
        writable = probe.read_text(encoding="utf-8") == "reefvision"
    except Exception as exc:
        error = str(exc)
    finally:
        probe.unlink(missing_ok=True)
    return {
        "data_directory": str(settings.resolved_data_dir),
        "total_bytes": int(usage.total),
        "used_bytes": int(usage.used),
        "free_bytes": int(usage.free),
        "writable": writable,
        "write_probe_error": error,
        "database_path": str(database_path) if database_path else None,
        "database_size_bytes": (
            database_path.stat().st_size
            if database_path is not None and database_path.is_file()
            else None
        ),
    }


def _sqlite_lock_probe(settings: Settings) -> dict[str, Any]:
    try:
        url = make_url(settings.resolved_database_url)
    except Exception as exc:
        return {"supported": False, "error": str(exc)}
    if url.get_backend_name() != "sqlite" or not url.database:
        return {"supported": False, "backend": url.get_backend_name()}
    database_path = Path(url.database)
    try:
        connection = sqlite3.connect(str(database_path), timeout=0.15)
        try:
            connection.execute("PRAGMA busy_timeout = 150")
            connection.execute("BEGIN IMMEDIATE")
            connection.rollback()
            return {"supported": True, "write_lock_available": True, "error": None}
        finally:
            connection.close()
    except sqlite3.OperationalError as exc:
        return {
            "supported": True,
            "write_lock_available": False,
            "error": str(exc),
        }


def _database_inventory(factory: sessionmaker[Session], settings: Settings) -> dict[str, Any]:
    output: dict[str, Any] = {"url_backend": make_url(settings.resolved_database_url).get_backend_name()}
    try:
        with factory() as session:
            output["quick_check"] = session.scalar(text("PRAGMA quick_check"))
            output["integrity_check"] = session.scalar(text("PRAGMA integrity_check"))
            output["journal_mode"] = session.scalar(text("PRAGMA journal_mode"))
            output["foreign_keys"] = bool(session.scalar(text("PRAGMA foreign_keys")))
            output["busy_timeout_ms"] = session.scalar(text("PRAGMA busy_timeout"))
            output["page_count"] = session.scalar(text("PRAGMA page_count"))
            output["page_size"] = session.scalar(text("PRAGMA page_size"))
            output["active_job_count"] = int(
                session.scalar(
                    select(func.count(Job.id)).where(
                        Job.status.in_(
                            (
                                "queued",
                                "blocked",
                                "running",
                                "pause_requested",
                                "paused",
                                "cancel_requested",
                            )
                        )
                    )
                )
                or 0
            )
            output["failed_job_count"] = int(
                session.scalar(select(func.count(Job.id)).where(Job.status == "failed"))
                or 0
            )
    except Exception as exc:
        output["error"] = str(exc)
    output["lock_probe"] = _sqlite_lock_probe(settings)
    return output


def _environment_inventory() -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in sorted(os.environ.items()):
        normalized = key.upper()
        if normalized.startswith("REEFVISION_"):
            values[key] = value
        elif normalized in {
            "CUDA_VISIBLE_DEVICES",
            "CUDA_HOME",
            "CONDA_DEFAULT_ENV",
            "VIRTUAL_ENV",
            "PYTHONPATH",
            "PATH",
        }:
            values[key] = value
        elif any(
            token in normalized
            for token in ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "PRIVATE_KEY")
        ):
            values[key] = "<present>" if value else "<empty>"
    return values


def collect_system_inventory(
    settings: Settings,
    factory: sessionmaker[Session],
) -> dict[str, Any]:
    return {
        "collected_at": datetime.now(UTC).isoformat(),
        "platform": {
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "architecture": platform.architecture(),
            "machine": platform.machine(),
            "python_version": sys.version,
            "python_executable": sys.executable,
            "process_id": os.getpid(),
        },
        "cpu": _cpu_inventory(),
        "memory": _memory_inventory(),
        "gpus": _gpu_inventory(),
        "filesystem": _filesystem_inventory(settings),
        "database": _database_inventory(factory, settings),
        "packages": _package_versions(),
        "environment": _environment_inventory(),
        "worker": {
            "background_worker_enabled": settings.background_worker_enabled,
            "worker_concurrency": settings.worker_concurrency,
            "worker_poll_seconds": settings.worker_poll_seconds,
            "safe_mode": settings.safe_mode,
        },
    }
