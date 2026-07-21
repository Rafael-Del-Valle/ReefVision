"""Run sequential local provider software acceptance without downloading assets.

This harness uses a deterministic generated image, loads one checkpoint at a
time, performs real forward inference, unloads it, and proves a second load.
Results are append-only provider acceptance records.  Passing this harness is a
software/runtime claim only; it is not scientific validation on coral imagery.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, ImageDraw
from sqlalchemy import select

from reefvision.config import Settings
from reefvision.db.models import ProviderModelAsset
from reefvision.db.session import create_database_engine, create_session_factory
from reefvision.ml.provider_contract import ProviderLifecycleError
from reefvision.ml.provider_lifecycle import ProviderRuntimeManager
from reefvision.schemas.provider_lifecycle import (
    ProviderInferenceRequest,
    TrustedExternalModelRegisterRequest,
)
from reefvision.services.provider_lifecycle import ProviderLifecycleService


def default_data_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "org.reefvision.desktop"
    return Path.home() / ".reefvision"


def runtime_versions() -> dict[str, str]:
    output = {"python": platform.python_version()}
    for package in (
        "torch",
        "torchvision",
        "ultralytics",
        "segment-anything",
        "transformers",
        "safetensors",
    ):
        try:
            output[package] = version(package)
        except PackageNotFoundError:
            output[package] = "missing"
    return output


def deterministic_input(data_dir: Path) -> Path:
    destination = data_dir / "provider-acceptance" / "inputs" / "gradient-shapes-v1.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (256, 256), color=(12, 28, 54))
    draw = ImageDraw.Draw(image)
    for index in range(256):
        draw.line((0, index, 255, index), fill=(index, 255 - index, (index * 3) % 256))
    draw.ellipse((48, 40, 190, 184), fill=(242, 181, 45), outline=(255, 255, 255), width=4)
    draw.rectangle((92, 94, 224, 228), fill=(30, 170, 132), outline=(8, 45, 68), width=5)
    temporary = destination.with_suffix(".png.part")
    image.save(temporary, format="PNG")
    os.replace(temporary, destination)
    return destination


@contextmanager
def block_network_downloads() -> Iterator[None]:
    """Fail closed if a provider attempts network access during local inference."""

    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection

    def blocked_connect(self: socket.socket, address: Any) -> None:
        del self, address
        raise RuntimeError("Provider acceptance blocks all implicit network downloads")

    def blocked_create_connection(*args: Any, **kwargs: Any) -> socket.socket:
        del args, kwargs
        raise RuntimeError("Provider acceptance blocks all implicit network downloads")

    socket.socket.connect = blocked_connect  # type: ignore[assignment]
    socket.create_connection = blocked_create_connection
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.create_connection = original_create_connection


def _summary(response: Any) -> dict[str, Any]:
    outputs = list(response.outputs)
    masks = [item for item in outputs if item.get("polygon") or item.get("raster_mask_png_base64")]
    return {
        "request_id": response.request_id,
        "output_count": len(outputs),
        "mask_count": len(masks),
        "empty_result": bool(response.metadata.get("empty_result", not outputs)),
        "source_width": response.metadata.get("source_width"),
        "source_height": response.metadata.get("source_height"),
        "ranked": [item.get("rank") for item in outputs] == list(range(1, len(outputs) + 1)),
        "mask_representations": sorted(
            {
                str(item.get("mask_representation"))
                for item in masks
                if item.get("mask_representation")
            }
        ),
        "relative_depth": response.metadata.get("relative_depth_only"),
        "prompt_provenance_present": bool(response.metadata.get("prompt_provenance")),
        "text_prompts": response.metadata.get("text_prompts"),
    }


def _cases(asset: ProviderModelAsset) -> list[tuple[str, dict[str, Any]]]:
    capabilities = asset.capabilities_json
    common = {"imgsz": 256, "confidence": 0.99, "iou": 0.45}
    if asset.task != "assist_segmentation":
        if capabilities.get("text_prompt"):
            return [("text_prompt", {**common, "text_prompts": ["coral", "fish"]})]
        return [("forward", common)]
    common = {"imgsz": 256, "confidence": 0.0, "iou": 0.45}
    cases: list[tuple[str, dict[str, Any]]] = []
    if capabilities.get("point_prompt"):
        parameters: dict[str, Any] = {**common, "positive_points": [[128, 128]]}
        if capabilities.get("negative_point_prompt"):
            parameters["negative_points"] = [[20, 20]]
        cases.append(("point_prompt", parameters))
    if capabilities.get("box_prompt"):
        cases.append(("box_prompt", {**common, "box": [45, 38, 225, 230]}))
    if capabilities.get("mixed_point_box_prompt"):
        cases.append(
            (
                "mixed_point_box_prompt",
                {
                    **common,
                    "positive_points": [[128, 128]],
                    "negative_points": [[20, 20]],
                    "box": [45, 38, 225, 230],
                },
            )
        )
    return cases


def _peak_memory() -> int | None:
    try:
        import torch

        return int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None
    except Exception:
        return None


def _reset_peak_memory() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
    except Exception:
        return


def run_asset(
    service: ProviderLifecycleService,
    asset: ProviderModelAsset,
    *,
    run_id: str,
    image_path: Path,
    device: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    load_result = "not_run"
    inference_result = "not_run"
    unload_result = "not_run"
    warnings: list[str] = []
    failure_reason: str | None = None
    details: dict[str, Any] = {
        "validation_kind": "software_acceptance",
        "scientific_validation": False,
        "packaged_desktop_validation": False,
        "cases": [],
    }
    _reset_peak_memory()
    resolved_device = device
    try:
        loaded = service.load(asset.id, device)
        resolved_device = loaded.resolved_device or device
        load_result = "passed"
        for case_name, parameters in _cases(asset):
            request_id = f"{run_id}:{asset.id}:{case_name}"
            response = service.infer(
                asset.id,
                ProviderInferenceRequest(
                    request_id=request_id,
                    source_path=str(image_path),
                    device=device,
                    parameters=parameters,
                ),
            )
            details["cases"].append({"case": case_name, **_summary(response)})
        inference_result = "passed"
    except Exception as exc:
        failure_reason = str(exc)
        if load_result == "not_run":
            load_result = "failed"
        else:
            inference_result = "failed"
    finally:
        try:
            service.unload(asset.id)
            unload_result = "passed"
        except Exception as exc:
            unload_result = "failed"
            failure_reason = failure_reason or str(exc)

    if load_result == inference_result == unload_result == "passed":
        try:
            service.load(asset.id, device)
            service.unload(asset.id)
            details["reload_after_unload"] = "passed"
        except Exception as exc:
            details["reload_after_unload"] = "failed"
            failure_reason = str(exc)
            load_result = "failed"
    else:
        details["reload_after_unload"] = "not_run"

    execution_time_ms = round((time.perf_counter() - started) * 1000)
    refreshed = service.session.get(ProviderModelAsset, asset.id)
    if refreshed is None:
        raise RuntimeError("Provider asset disappeared during acceptance")
    service.persist_acceptance(
        asset=refreshed,
        run_id=run_id,
        device=str(resolved_device),
        runtime_versions=runtime_versions(),
        load_result=load_result,
        inference_result=inference_result,
        unload_result=unload_result,
        peak_memory_bytes=_peak_memory(),
        execution_time_ms=execution_time_ms,
        warnings=warnings,
        failure_reason=failure_reason,
        test_input_identifier="reefvision:deterministic-gradient-shapes-v1",
        details=details,
    )
    return {
        "model_id": asset.model_id,
        "provider_id": asset.provider_id,
        "device": resolved_device,
        "load": load_result,
        "inference": inference_result,
        "unload": unload_result,
        "reload": details["reload_after_unload"],
        "execution_time_ms": execution_time_ms,
        "peak_memory_bytes": _peak_memory(),
        "failure_reason": failure_reason,
        "cases": details["cases"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--model-id", action="append", default=None)
    parser.add_argument("--original-sam", type=Path, default=None)
    parser.add_argument("--depth-anything", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_dir = args.data_dir.expanduser().resolve()
    runtime_config_dir = data_dir / "provider-acceptance" / "runtime"
    runtime_config_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("ULTRALYTICS_OFFLINE", "true")
    os.environ.setdefault("YOLO_CONFIG_DIR", str(runtime_config_dir))
    settings = Settings(
        data_dir=data_dir,
        database_url=args.database_url,
        background_worker_enabled=False,
    )
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    runtime = ProviderRuntimeManager()
    run_id = str(uuid4())
    report: dict[str, Any] = {
        "run_id": run_id,
        "validation_kind": "software_acceptance",
        "scientific_validation": False,
        "packaged_desktop_validation": False,
        "device_request": args.device,
        "results": [],
    }
    try:
        with factory() as session:
            service = ProviderLifecycleService(session, settings, runtime)
            discovery = service.discover()
            report["discovery"] = discovery.model_dump(mode="json")
            if args.original_sam is not None:
                service.register_external(
                    TrustedExternalModelRegisterRequest(
                        model_id="external/meta-sam/vit-b",
                        provider_id="segment_anything",
                        architecture="Meta Segment Anything ViT-B",
                        task="assist_segmentation",
                        checkpoint_path=str(args.original_sam.resolve()),
                        source="trusted_external_meta_checkpoint",
                        revision="sam_vit_b_01ec64",
                        confirmed=True,
                    )
                )
            if args.depth_anything is not None:
                service.register_external(
                    TrustedExternalModelRegisterRequest(
                        model_id="external/depth-anything-v2/small",
                        provider_id="depth_anything_v2",
                        architecture="Depth Anything V2 Small",
                        task="depth",
                        checkpoint_path=str(args.depth_anything.resolve()),
                        source="trusted_external_huggingface_folder",
                        revision="local-folder",
                        confirmed=True,
                    )
                )
            image_path = deterministic_input(data_dir)
            statement = select(ProviderModelAsset).order_by(ProviderModelAsset.model_id)
            if args.model_id:
                statement = statement.where(ProviderModelAsset.model_id.in_(args.model_id))
            assets = list(session.scalars(statement))
            with block_network_downloads():
                for index, asset in enumerate(assets, start=1):
                    print(f"[{index}/{len(assets)}] {asset.model_id}", flush=True)
                    result = run_asset(
                        service,
                        asset,
                        run_id=run_id,
                        image_path=image_path,
                        device=args.device,
                    )
                    report["results"].append(result)
                    outcome = (
                        "PASS"
                        if result["load"]
                        == result["inference"]
                        == result["unload"]
                        == result["reload"]
                        == "passed"
                        else "FAIL"
                    )
                    print(
                        f"  {outcome} {result['execution_time_ms']} ms"
                        + (f" — {result['failure_reason']}" if result["failure_reason"] else ""),
                        flush=True,
                    )
    except ProviderLifecycleError as exc:
        print(f"Provider acceptance could not continue: {exc}", file=sys.stderr)
        return 2
    finally:
        runtime.unload()
        engine.dispose()

    failed = [
        item
        for item in report["results"]
        if not all(item[key] == "passed" for key in ("load", "inference", "unload", "reload"))
    ]
    report["passed_count"] = len(report["results"]) - len(failed)
    report["failed_count"] = len(failed)
    report["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    output = args.output or data_dir / "provider-acceptance" / f"acceptance-{run_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".part")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    print(f"Acceptance report: {output}")
    print(f"Passed: {report['passed_count']}; failed: {report['failed_count']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
