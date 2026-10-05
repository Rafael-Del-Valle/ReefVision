"""Packaged ReefVision provider CPU/CUDA acceptance.

This module is intentionally invoked from the frozen desktop sidecar. It uses
only installer-bundled, checksum-verified checkpoints and deterministic
synthetic imagery. The resulting evidence proves packaged runtime execution,
not biological model accuracy.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.ml.depth_anything_v2_provider import TransformersDepthAnythingV2Provider
from reefvision.ml.providers import (
    DetectionSettings,
    UltralyticsDetectionProvider,
    resolve_torch_device,
)
from reefvision.services.bundled_models import install_bundled_catalog_models
from reefvision.storage.catalog_models import catalog_manifest_record

REPORT_FILENAME = "provider-hardware-acceptance.json"
DETECTION_CATALOG_ID = "ultralytics/yolo11/detect/n"
DEPTH_CATALOG_ID = "transformers/depth_anything_v2/small"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _managed_asset(
    settings: Settings,
    catalog_id: str,
) -> tuple[Path, dict[str, Any]]:
    record = catalog_manifest_record(settings, catalog_id)
    if record is None:
        raise RuntimeError(f"Managed bundled checkpoint is missing: {catalog_id}")

    relative = record.get("relative_path")
    if not isinstance(relative, str) or not relative:
        raise RuntimeError(f"Managed bundled checkpoint has no relative_path: {catalog_id}")

    path = (settings.resolved_data_dir / relative).resolve()
    try:
        path.relative_to(settings.resolved_data_dir.resolve())
    except ValueError as exc:
        raise RuntimeError(f"Managed checkpoint escaped data root: {catalog_id}") from exc

    files = record.get("files")
    if isinstance(files, list) and files:
        for item in files:
            if not isinstance(item, dict):
                raise RuntimeError(f"Malformed managed manifest entry: {catalog_id}")
            file_relative = item.get("relative_path")
            if not isinstance(file_relative, str) or not file_relative:
                raise RuntimeError(f"Managed manifest file has no path: {catalog_id}")
            file_path = (settings.resolved_data_dir / file_relative).resolve()
            try:
                file_path.relative_to(settings.resolved_data_dir.resolve())
            except ValueError as exc:
                raise RuntimeError(
                    f"Managed checkpoint file escaped data root: {catalog_id}"
                ) from exc
            if not file_path.is_file():
                raise RuntimeError(f"Managed checkpoint file is missing: {file_path}")
            if file_path.stat().st_size != int(item["size_bytes"]):
                raise RuntimeError(f"Managed checkpoint size mismatch: {file_path}")
            if sha256_file(file_path) != str(item["sha256"]):
                raise RuntimeError(f"Managed checkpoint checksum mismatch: {file_path}")

    if not path.exists():
        raise RuntimeError(f"Managed checkpoint path is missing: {path}")
    return path, record


def _write_input(path: Path) -> None:
    import numpy as np

    y, x = np.mgrid[0:256, 0:384]
    pixels = np.stack(
        (
            (x * 255 // 383),
            (y * 255 // 255),
            ((x // 24 + y // 24) % 2) * 180 + 40,
        ),
        axis=-1,
    ).astype("uint8")
    Image.fromarray(pixels, mode="RGB").save(path)


def _timed_run(
    device: str,
    action: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    import torch

    if device == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    started = time.perf_counter()
    try:
        details = action()
        if device == "cuda":
            torch.cuda.synchronize()
        elapsed = time.perf_counter() - started
        return {
            "status": "PASS",
            "device_requested": device,
            "elapsed_seconds": round(elapsed, 6),
            "peak_cuda_memory_bytes": (
                int(torch.cuda.max_memory_allocated()) if device == "cuda" else None
            ),
            "fallback_behavior": "none",
            **details,
        }
    except Exception as exc:
        return {
            "status": "FAIL",
            "device_requested": device,
            "elapsed_seconds": round(time.perf_counter() - started, 6),
            "failure_class": type(exc).__name__,
            "failure_message": str(exc),
            "fallback_behavior": "none",
        }


def _detection_run(
    checkpoint: Path,
    input_path: Path,
    device: str,
) -> dict[str, Any]:
    provider = UltralyticsDetectionProvider()

    def action() -> dict[str, Any]:
        provider.load_model(checkpoint, device)
        predictions = provider.predict(
            input_path,
            DetectionSettings(
                confidence_threshold=0.01,
                iou_threshold=0.7,
                device=device,
            ),
        )
        model = getattr(provider, "_model", None)
        network = getattr(model, "model", None)
        parameters = list(network.parameters()) if network is not None else []
        actual_device = str(parameters[0].device) if parameters else "unknown"
        if device == "cpu" and actual_device != "cpu":
            raise RuntimeError(f"CPU detection used unexpected device: {actual_device}")
        if device == "cuda" and not actual_device.startswith("cuda"):
            raise RuntimeError(f"CUDA detection silently used: {actual_device}")
        return {
            "device_actually_used": actual_device,
            "prediction_count": len(predictions),
            "provider": provider.provider_name,
            "provider_version": provider.provider_version,
            "checkpoint_sha256": sha256_file(checkpoint),
        }

    try:
        return _timed_run(device, action)
    finally:
        provider.unload_model()


def _depth_run(
    checkpoint: Path,
    input_path: Path,
    output_root: Path,
    device: str,
) -> dict[str, Any]:
    import numpy as np

    provider = TransformersDepthAnythingV2Provider()

    def action() -> dict[str, Any]:
        provider.load_model(checkpoint, device)
        prediction = provider.predict_depth(
            input_path,
            output_root / f"depth-{device}",
            device=device,
        )
        depth = np.load(prediction.relative_depth_path, allow_pickle=False)
        actual_device = str(getattr(provider, "_device", "unknown"))
        if device == "cpu" and actual_device != "cpu":
            raise RuntimeError(f"CPU depth inference used unexpected device: {actual_device}")
        if device == "cuda" and not actual_device.startswith("cuda"):
            raise RuntimeError(f"CUDA depth inference silently used: {actual_device}")
        if depth.shape != (256, 384):
            raise RuntimeError(f"Unexpected depth output shape: {depth.shape}")
        if not np.isfinite(depth).all():
            raise RuntimeError("Depth output contains non-finite values")
        if float(depth.max()) <= float(depth.min()):
            raise RuntimeError("Depth output is constant")
        return {
            "device_actually_used": actual_device,
            "provider": provider.provider_name,
            "provider_version": provider.provider_version,
            "output_dimensions": list(depth.shape),
            "minimum_value": float(depth.min()),
            "maximum_value": float(depth.max()),
            "depth_kind": "relative_monocular_depth",
            "relative_monocular_depth_is_metric": False,
        }

    try:
        return _timed_run(device, action)
    finally:
        provider.unload_model()


def run_packaged_provider_acceptance(settings: Settings) -> int:
    """Run packaged providers on CPU/CUDA and write machine-readable evidence."""

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["YOLO_AUTOINSTALL"] = "false"

    settings.ensure_directories()
    report_path = settings.resolved_data_dir / REPORT_FILENAME
    report_path.unlink(missing_ok=True)

    installed, warnings = install_bundled_catalog_models(settings)

    detection_path, detection_record = _managed_asset(
        settings,
        DETECTION_CATALOG_ID,
    )
    depth_path, depth_record = _managed_asset(
        settings,
        DEPTH_CATALOG_ID,
    )

    input_path = settings.resolved_data_dir / "provider-acceptance-input.png"
    _write_input(input_path)

    import torch

    cuda_available = bool(torch.cuda.is_available())
    gpu_name = torch.cuda.get_device_name(0) if cuda_available else None

    results: dict[str, dict[str, Any]] = {}
    results["yolo11n_cpu"] = _detection_run(
        detection_path,
        input_path,
        "cpu",
    )
    results["depth_anything_v2_cpu"] = _depth_run(
        depth_path,
        input_path,
        settings.resolved_data_dir / "provider-acceptance-output",
        "cpu",
    )

    if cuda_available:
        results["yolo11n_cuda"] = _detection_run(
            detection_path,
            input_path,
            "cuda",
        )
        results["depth_anything_v2_cuda"] = _depth_run(
            depth_path,
            input_path,
            settings.resolved_data_dir / "provider-acceptance-output",
            "cuda",
        )
    else:
        blocked = {
            "status": "BLOCKED",
            "failure_class": "CudaUnavailable",
            "failure_message": "torch.cuda.is_available() is false",
        }
        results["yolo11n_cuda"] = dict(blocked)
        results["depth_anything_v2_cuda"] = dict(blocked)

    try:
        resolve_torch_device("cuda:99")
    except ValidationError as exc:
        results["invalid_device_rejection"] = {
            "status": "PASS",
            "device_requested": "cuda:99",
            "failure_class": type(exc).__name__,
            "failure_message": str(exc),
            "fallback_behavior": "none; rejected before provider execution",
        }
    else:
        results["invalid_device_rejection"] = {
            "status": "FAIL",
            "device_requested": "cuda:99",
            "failure_class": "UnexpectedDeviceAcceptance",
            "failure_message": "cuda:99 was accepted",
        }

    required = [
        "yolo11n_cpu",
        "depth_anything_v2_cpu",
        "invalid_device_rejection",
    ]
    if cuda_available:
        required.extend(["yolo11n_cuda", "depth_anything_v2_cuda"])

    status = (
        "PASS"
        if all(results[name]["status"] == "PASS" for name in required)
        else "FAIL"
    )

    payload = {
        "schema_version": "reefvision-packaged-provider-acceptance-0001",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "status": status,
        "packaged_runtime": bool(getattr(__import__("sys"), "frozen", False)),
        "network_downloads_allowed": False,
        "hardware": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "torch": torch.__version__,
            "torch_cuda_runtime": torch.version.cuda,
            "cuda_available": cuda_available,
            "cuda_device_count": torch.cuda.device_count(),
            "gpu_name": gpu_name,
            "total_gpu_vram_bytes": (
                int(torch.cuda.get_device_properties(0).total_memory)
                if cuda_available
                else None
            ),
        },
        "bundled_models": {
            "installed_catalog_ids": installed,
            "warnings": warnings,
            "detection": {
                "catalog_id": DETECTION_CATALOG_ID,
                "path": str(detection_path),
                "manifest": detection_record,
            },
            "depth": {
                "catalog_id": DEPTH_CATALOG_ID,
                "path": str(depth_path),
                "manifest": depth_record,
            },
        },
        "input": {
            "path": str(input_path),
            "kind": "deterministic_synthetic_execution_only",
            "establishes_biological_accuracy": False,
        },
        "results": results,
    }

    temporary = report_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, report_path)
    print(report_path)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if status == "PASS" else 1
