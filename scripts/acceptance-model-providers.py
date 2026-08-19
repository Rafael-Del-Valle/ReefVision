"""Run real ReefVision SAM2/Depth Anything provider hardware acceptance.

The harness never downloads weights. Missing or unverifiable checkpoints are
reported as BLOCKED and all evidence is written below the untracked .artifacts
directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPOSITORY_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

STATUS_VALUES = {"PASS", "FAIL", "BLOCKED", "SKIPPED", "NOT RUN"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unavailable"


def result(status: str, **details: Any) -> dict[str, Any]:
    if status not in STATUS_VALUES:
        raise ValueError(f"Unsupported acceptance status: {status}")
    return {"status": status, **details}


def default_data_dir() -> Path:
    configured = os.environ.get("REEFVISION_DATA_DIR")
    if configured:
        return Path(configured)
    appdata = os.environ.get("APPDATA")
    return Path(appdata) / "org.reefvision.desktop" if appdata else Path.home() / ".reefvision"


def load_verified_catalog_asset(
    data_dir: Path, catalog_id: str
) -> tuple[Path | None, dict[str, Any], str | None]:
    manifest_path = data_dir / "models" / "catalog-models" / "manifest.json"
    if not manifest_path.is_file():
        return None, {}, f"Managed model manifest is missing: {manifest_path}"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    record = manifest.get("assets", {}).get(catalog_id)
    if not isinstance(record, dict):
        return None, {}, f"No managed manifest asset exists for {catalog_id}"
    relative = record.get("relative_path")
    if not isinstance(relative, str):
        return None, record, "Managed asset has no relative_path"
    path = (data_dir / relative).resolve()
    try:
        path.relative_to(data_dir.resolve())
    except ValueError:
        return None, record, "Managed asset path escapes the ReefVision data directory"
    if not path.is_file():
        return None, record, f"Managed checkpoint is missing: {path}"
    expected_size = record.get("size_bytes")
    expected_sha = record.get("sha256")
    if path.stat().st_size != expected_size:
        return None, record, "Managed checkpoint size does not match its manifest"
    actual_sha = sha256_file(path)
    if actual_sha != expected_sha:
        return None, record, "Managed checkpoint SHA-256 does not match its manifest"
    return path, record, None


def checkpoint_identity(
    *, catalog_id: str | None, path: Path | None, record: dict[str, Any]
) -> dict[str, Any]:
    return {
        "catalog_id": catalog_id,
        "path": str(path) if path else None,
        "sha256": record.get("sha256"),
        "size_bytes": record.get("size_bytes"),
        "provider_version": record.get("provider_version"),
        "source_url": record.get("source_url"),
    }


def timed_provider_run(
    *, provider: Any, checkpoint: Path, device: str, infer: Callable[[Any], dict[str, Any]]
) -> dict[str, Any]:
    import torch

    started = time.perf_counter()
    loaded_at: float | None = None
    try:
        if device == "cuda":
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
        provider.load_model(checkpoint, device)
        loaded_at = time.perf_counter()
        output = infer(provider)
        if device == "cuda":
            torch.cuda.synchronize()
        finished = time.perf_counter()
        actual = getattr(provider, "_device", None)
        actual_device = f"cuda:{actual}" if isinstance(actual, int) else str(actual)
        if device == "cuda" and not actual_device.startswith("cuda"):
            return result(
                "FAIL",
                device_requested=device,
                device_actually_used=actual_device,
                failure_class="SilentDeviceFallback",
                failure_message="CUDA was requested but the provider did not use CUDA",
                fallback_behavior="unexpected CPU fallback",
            )
        return result(
            "PASS",
            device_requested=device,
            device_actually_used=actual_device,
            load_result="PASS",
            inference_result="PASS",
            load_elapsed_seconds=round(loaded_at - started, 6),
            inference_elapsed_seconds=round(finished - loaded_at, 6),
            elapsed_seconds=round(finished - started, 6),
            peak_cuda_memory_bytes=(
                torch.cuda.max_memory_allocated() if device == "cuda" else None
            ),
            fallback_behavior="none",
            **output,
        )
    except Exception as exc:
        return result(
            "FAIL",
            device_requested=device,
            device_actually_used=str(getattr(provider, "_device", "unknown")),
            load_result="PASS" if loaded_at is not None else "FAIL",
            inference_result="FAIL" if loaded_at is not None else "NOT RUN",
            elapsed_seconds=round(time.perf_counter() - started, 6),
            failure_class=type(exc).__name__,
            failure_message=str(exc),
            fallback_behavior="none",
        )
    finally:
        provider.unload_model()


def write_input(path: Path) -> None:
    import numpy as np
    from PIL import Image

    y, x = np.mgrid[0:256, 0:384]
    pixels = np.stack(
        ((x * 255 // 383), (y * 255 // 255), ((x // 24 + y // 24) % 2) * 180 + 40),
        axis=-1,
    ).astype("uint8")
    Image.fromarray(pixels, mode="RGB").save(path)


def sam_infer(input_path: Path) -> Callable[[Any], dict[str, Any]]:
    def run(provider: Any) -> dict[str, Any]:
        import numpy as np

        from reefvision.ml.providers import PixelBox

        prediction = provider.predict_from_box(
            provider.prepare_image(input_path),
            PixelBox(x_min=96, y_min=64, x_max=288, y_max=192),
        )
        mask = np.asarray(prediction.mask)
        if mask.shape != (256, 384) or not np.isfinite(mask).all() or not mask.any():
            raise ValueError(f"Invalid SAM2 mask: shape={mask.shape}, nonempty={bool(mask.any())}")
        return {
            "output_dimensions": list(mask.shape),
            "output_type": str(mask.dtype),
            "output_nonzero_count": int(mask.sum()),
            "prompt": {"box": [96, 64, 288, 192]},
        }

    return run


def depth_infer(input_path: Path, output_dir: Path, device: str) -> Callable[[Any], dict[str, Any]]:
    def run(provider: Any) -> dict[str, Any]:
        import numpy as np

        prediction = provider.predict_depth(input_path, output_dir / "depth", device=device)
        depth = np.load(prediction.relative_depth_path, allow_pickle=False)
        if depth.shape != (256, 384) or not np.isfinite(depth).all():
            raise ValueError(f"Invalid depth output: shape={depth.shape}")
        if float(depth.max()) <= float(depth.min()):
            raise ValueError("Depth output is constant")
        return {
            "output_dimensions": list(depth.shape),
            "output_type": str(depth.dtype),
            "minimum_value": float(depth.min()),
            "maximum_value": float(depth.max()),
            "depth_kind": "relative_monocular_depth",
            "relative_monocular_depth_is_metric": False,
            "relative_depth_path": str(prediction.relative_depth_path),
            "preview_path": str(prediction.preview_path),
        }

    return run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--depth-checkpoint", type=Path)
    parser.add_argument("--output-root", type=Path, default=REPOSITORY_ROOT / ".artifacts")
    args = parser.parse_args()

    import torch

    from reefvision.ml.catalog_expansion import UnifiedSegmentAnythingAssistProvider
    from reefvision.ml.depth_anything_v2_provider import TransformersDepthAnythingV2Provider
    from reefvision.ml.providers import resolve_torch_device

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    evidence_dir = args.output_root / f"model-provider-acceptance-{stamp}"
    evidence_dir.mkdir(parents=True, exist_ok=False)
    input_path = evidence_dir / "deterministic-hardware-input.png"
    write_input(input_path)
    cuda_available = torch.cuda.is_available()
    hardware = {
        "os": platform.platform(),
        "python": sys.version,
        "pytorch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "cuda_available": cuda_available,
        "cuda_device_count": torch.cuda.device_count(),
        "gpu_name": torch.cuda.get_device_name(0) if cuda_available else None,
        "total_gpu_vram_bytes": (
            torch.cuda.get_device_properties(0).total_memory if cuda_available else None
        ),
        "dependencies": {
            name: package_version(name)
            for name in ("transformers", "ultralytics", "accelerate", "safetensors")
        },
    }
    report: dict[str, Any] = {
        "schema_version": "reefvision-model-provider-acceptance-v1",
        "reefvision_commit_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, text=True
        ).strip(),
        "timestamp": datetime.now(UTC).isoformat(),
        "hardware": hardware,
        "input": {
            "path": str(input_path),
            "kind": "deterministic_synthetic_hardware_execution_only",
            "establishes_biological_accuracy": False,
        },
        "results": {},
    }

    sam_path, sam_record, sam_error = load_verified_catalog_asset(
        args.data_dir.resolve(), "sam2/image/base"
    )
    report["models"] = {
        "sam2": checkpoint_identity(catalog_id="sam2/image/base", path=sam_path, record=sam_record)
    }
    if sam_error or sam_path is None:
        blocked = result(
            "BLOCKED", failure_class="CheckpointUnavailable", failure_message=sam_error
        )
        report["results"]["sam2_cpu"] = blocked
        report["results"]["sam2_cuda"] = blocked.copy()
    else:
        report["results"]["sam2_cpu"] = timed_provider_run(
            provider=UnifiedSegmentAnythingAssistProvider(),
            checkpoint=sam_path,
            device="cpu",
            infer=sam_infer(input_path),
        )
        report["results"]["sam2_cuda"] = (
            timed_provider_run(
                provider=UnifiedSegmentAnythingAssistProvider(),
                checkpoint=sam_path,
                device="cuda",
                infer=sam_infer(input_path),
            )
            if cuda_available
            else result(
                "BLOCKED",
                failure_class="CudaUnavailable",
                failure_message="torch.cuda.is_available() is false",
            )
        )

    depth_path = args.depth_checkpoint.resolve() if args.depth_checkpoint else None
    depth_record: dict[str, Any] = {}
    depth_error: str | None = None
    if depth_path is None:
        depth_error = (
            "No verified Depth Anything V2 checkpoint is cataloged or staged; "
            "pass a verified local Transformers ZIP with --depth-checkpoint"
        )
    elif not depth_path.is_file():
        depth_error = f"Depth checkpoint is missing: {depth_path}"
    else:
        depth_record = {
            "sha256": sha256_file(depth_path),
            "size_bytes": depth_path.stat().st_size,
            "provider_version": package_version("transformers"),
        }
    report["models"]["depth_anything_v2"] = checkpoint_identity(
        catalog_id=None, path=depth_path, record=depth_record
    )
    if depth_error or depth_path is None:
        blocked = result(
            "BLOCKED", failure_class="CheckpointUnavailable", failure_message=depth_error
        )
        report["results"]["depth_anything_v2_cpu"] = blocked
        report["results"]["depth_anything_v2_cuda"] = blocked.copy()
    else:
        report["results"]["depth_anything_v2_cpu"] = timed_provider_run(
            provider=TransformersDepthAnythingV2Provider(),
            checkpoint=depth_path,
            device="cpu",
            infer=depth_infer(input_path, evidence_dir / "depth-cpu", "cpu"),
        )
        report["results"]["depth_anything_v2_cuda"] = (
            timed_provider_run(
                provider=TransformersDepthAnythingV2Provider(),
                checkpoint=depth_path,
                device="cuda",
                infer=depth_infer(input_path, evidence_dir / "depth-cuda", "cuda"),
            )
            if cuda_available
            else result(
                "BLOCKED",
                failure_class="CudaUnavailable",
                failure_message="torch.cuda.is_available() is false",
            )
        )

    try:
        resolve_torch_device("cuda:99")
        unavailable = result(
            "FAIL",
            failure_class="UnexpectedDeviceAcceptance",
            failure_message="cuda:99 was accepted",
        )
    except Exception as exc:
        unavailable = result(
            "PASS",
            device_requested="cuda:99",
            device_actually_used=None,
            failure_class=type(exc).__name__,
            failure_message=str(exc),
            fallback_behavior="none; request rejected before provider execution",
        )
    report["results"]["unavailable_device_recovery"] = unavailable
    report["results"]["cuda_oom_recovery"] = result(
        "NOT RUN",
        test_kind="neither simulated nor real hardware OOM",
        failure_class="NoProductionRecoveryContract",
        failure_message=(
            "Providers clear CUDA cache on unload but have no explicit OOM "
            "catch/retry/fallback contract; no unsafe VRAM exhaustion was attempted"
        ),
        software_oom_recovery_path="NOT RUN",
        real_hardware_oom_evidence="NOT RUN",
    )
    report_path = evidence_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(report_path)
    return 1 if any(item["status"] == "FAIL" for item in report["results"].values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
