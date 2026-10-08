"""Packaged ReefVision provider CPU/CUDA acceptance.

This module is intentionally invoked from the frozen desktop sidecar. It uses
only explicitly supplied local, checksum-verified checkpoints and deterministic
synthetic imagery. The resulting evidence proves packaged runtime execution,
not biological model accuracy.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from PIL import Image

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.ml.depth_anything_v2_provider import TransformersDepthAnythingV2Provider
from reefvision.ml.providers import (
    DetectionSettings,
    UltralyticsDetectionProvider,
    resolve_torch_device,
)

REPORT_FILENAME = "provider-hardware-acceptance.json"
DETECTION_CATALOG_ID = "ultralytics/yolo11/detect/n"
DEPTH_CATALOG_ID = "transformers/depth_anything_v2/small"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _explicit_local_asset(models: dict[str, Any], kind: str) -> tuple[Path, dict[str, Any]]:
    """Verify researcher-selected inputs without searching installer/user caches."""
    record = models.get(kind)
    if not isinstance(record, dict) or not record.get("path"):
        raise RuntimeError(f"An explicit local {kind} model and checksum manifest are required.")
    path = Path(str(record["path"])).expanduser()
    if not path.is_absolute() or not path.exists():
        raise RuntimeError(f"Explicit local model is missing or not absolute: {path}")
    path = path.resolve()
    files = record.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError(f"An explicit checksum manifest is required for {path}")
    verified = set()
    for item in files:
        if not isinstance(item, dict):
            raise RuntimeError("Malformed explicit checksum manifest")
        file_path = Path(str(item.get("path") or ""))
        if not file_path.is_absolute():
            raise RuntimeError("Explicit model files must have absolute paths")
        file_path = file_path.resolve()
        if (path.is_file() and file_path != path) or (
            path.is_dir() and not file_path.is_relative_to(path)
        ):
            raise RuntimeError(f"Checksum manifest file is outside the selected model: {file_path}")
        if not file_path.is_file():
            raise RuntimeError(f"Explicit model file is missing: {file_path}")
        if file_path.stat().st_size != item.get("size_bytes"):
            raise RuntimeError(f"Explicit model size mismatch: {file_path}")
        if sha256_file(file_path) != item.get("sha256"):
            raise RuntimeError(f"Explicit model checksum mismatch: {file_path}")
        verified.add(file_path)
    actual = {p.resolve() for p in path.rglob("*") if p.is_file()} if path.is_dir() else {path}
    if actual != verified:
        raise RuntimeError(f"Checksum manifest does not cover every model file: {path}")
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
        with (
            patch("socket.socket.connect", side_effect=RuntimeError("Acceptance network blocked")),
            patch(
                "socket.create_connection", side_effect=RuntimeError("Acceptance network blocked")
            ),
        ):
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
        parameter = next(iter(network.parameters()), None) if network is not None else None
        actual_device = str(parameter.device) if parameter is not None else "unknown"
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

    manifest_name = os.environ.get("REEFVISION_ACCEPTANCE_MODEL_MANIFEST")
    if not manifest_name:
        raise RuntimeError(
            "Set REEFVISION_ACCEPTANCE_MODEL_MANIFEST to an explicit local "
            "model checksum manifest. No bundled checkpoint or developer "
            "cache is used."
        )
    manifest_path = Path(manifest_name)
    if not manifest_path.is_absolute() or not manifest_path.is_file():
        raise RuntimeError("Acceptance model manifest must be an existing absolute local path.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    models = manifest.get("models")
    if not isinstance(models, dict):
        raise RuntimeError("Acceptance manifest must contain a models object.")
    detection_path, detection_record = _explicit_local_asset(models, "detection")
    depth_asset = _explicit_local_asset(models, "depth") if models.get("depth") else None

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
    model_required = {
        "status": "MODEL_REQUIRED",
        "failure_message": (
            "Register/provide a compatible local depth model to test this optional capability."
        ),
    }
    results["depth_anything_v2_cpu"] = (
        _depth_run(
            depth_asset[0],
            input_path,
            settings.resolved_data_dir / "provider-acceptance-output",
            "cpu",
        )
        if depth_asset
        else dict(model_required)
    )

    if cuda_available:
        results["yolo11n_cuda"] = _detection_run(
            detection_path,
            input_path,
            "cuda",
        )
        results["depth_anything_v2_cuda"] = (
            _depth_run(
                depth_asset[0],
                input_path,
                settings.resolved_data_dir / "provider-acceptance-output",
                "cuda",
            )
            if depth_asset
            else dict(model_required)
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
        "invalid_device_rejection",
    ]
    if cuda_available:
        required.append("yolo11n_cuda")
    if depth_asset:
        required.append("depth_anything_v2_cpu")
        if cuda_available:
            required.append("depth_anything_v2_cuda")

    status = "PASS" if all(results[name]["status"] == "PASS" for name in required) else "FAIL"

    payload = {
        "schema_version": "reefvision-packaged-provider-acceptance-0002",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "status": status,
        "packaged_runtime": bool(getattr(sys, "frozen", False)),
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
                int(torch.cuda.get_device_properties(0).total_memory) if cuda_available else None
            ),
        },
        "model_policy": "explicit_local_models_only",
        "model_inputs": {
            "source_manifest": str(manifest_path),
            "detection": {"path": str(detection_path), "manifest": detection_record},
            "depth": (
                {"path": str(depth_asset[0]), "manifest": depth_asset[1]} if depth_asset else None
            ),
        },
        "required_results": required,
        "optional_depth_tested": depth_asset is not None,
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
