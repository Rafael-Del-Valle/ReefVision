"""Collect reproducible Phase 11 Windows/CPU/CUDA hardware evidence.

This script intentionally performs no network access and does not download models.
It validates that the local Python/provider runtime can execute on CPU and, when
requested, on CUDA. Biological/model-quality validation remains separate.
"""

from __future__ import annotations

import argparse
import ctypes
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "reefvision-phase11-hardware-profile-0001"


def git_value(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def windows_memory_bytes() -> int | None:
    if sys.platform != "win32":
        return None

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(MemoryStatusEx)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.ullTotalPhys)


def timed_torch_matmul(device: str, size: int) -> dict[str, Any]:
    import torch

    if device.startswith("cuda"):
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    a = torch.randn((size, size), device=device)
    b = torch.randn((size, size), device=device)

    if device.startswith("cuda"):
        torch.cuda.synchronize()

    started = time.perf_counter()
    result = a @ b

    if device.startswith("cuda"):
        torch.cuda.synchronize()

    duration = time.perf_counter() - started
    checksum = float(result[:8, :8].sum().detach().cpu().item())

    payload: dict[str, Any] = {
        "device": device,
        "matrix_size": size,
        "duration_seconds": duration,
        "finite_checksum": checksum,
        "passed": bool(result.isfinite().all().detach().cpu().item()),
    }

    if device.startswith("cuda"):
        payload["peak_memory_allocated_bytes"] = int(
            torch.cuda.max_memory_allocated()
        )

    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--require-cuda",
        action="store_true",
        help="Fail unless CUDA is available and a CUDA execution check passes.",
    )
    parser.add_argument(
        "--expected-gpu-substring",
        default="",
        help="Fail unless at least one CUDA device name contains this text.",
    )
    args = parser.parse_args()

    import torch

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    source_commit = git_value("rev-parse", "HEAD")
    source_dirty = bool(git_value("status", "--porcelain"))

    cuda_available = bool(torch.cuda.is_available())
    cuda_devices: list[dict[str, Any]] = []
    if cuda_available:
        for index in range(torch.cuda.device_count()):
            properties = torch.cuda.get_device_properties(index)
            cuda_devices.append(
                {
                    "index": index,
                    "name": torch.cuda.get_device_name(index),
                    "total_memory_bytes": int(properties.total_memory),
                    "compute_capability": [
                        int(properties.major),
                        int(properties.minor),
                    ],
                }
            )

    if args.require_cuda and not cuda_available:
        raise RuntimeError("CUDA is required for this Phase 11 hardware run.")

    if args.expected_gpu_substring:
        expected = args.expected_gpu_substring.casefold()
        if not any(expected in item["name"].casefold() for item in cuda_devices):
            names = ", ".join(item["name"] for item in cuda_devices) or "none"
            raise RuntimeError(
                f"Expected GPU containing {args.expected_gpu_substring!r}; found: {names}"
            )

    cpu_check = timed_torch_matmul("cpu", 1024)
    cuda_check: dict[str, Any] | None = None
    if cuda_available:
        cuda_check = timed_torch_matmul("cuda:0", 2048)

    disk = shutil.disk_usage(output.parent)

    report = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "source_commit": source_commit,
        "source_tree_clean": not source_dirty,
        "network_access_performed": False,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": platform.python_version(),
            "logical_cpu_count": __import__("os").cpu_count(),
            "physical_memory_bytes": windows_memory_bytes(),
            "disk_total_bytes": disk.total,
            "disk_free_bytes": disk.free,
        },
        "runtime": {
            "torch": torch.__version__,
            "torch_cuda_runtime": torch.version.cuda,
            "ultralytics": package_version("ultralytics"),
            "opencv_contrib_python": package_version("opencv-contrib-python"),
            "numpy": package_version("numpy"),
            "pillow": package_version("pillow"),
        },
        "cuda": {
            "available": cuda_available,
            "device_count": len(cuda_devices),
            "devices": cuda_devices,
        },
        "execution_checks": {
            "cpu": cpu_check,
            "cuda": cuda_check,
        },
    }

    passed = bool(cpu_check["passed"])
    if args.require_cuda:
        passed = passed and cuda_check is not None and bool(cuda_check["passed"])

    report["status"] = "PASS" if passed else "FAIL"

    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
