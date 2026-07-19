"""Background execution for real provider benchmark jobs."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, Job, ModelRegistration
from reefvision.domain.errors import ValidationError
from reefvision.ml.depth_runtime import generate_depth_map
from reefvision.ml.provider_hub import assist_provider_for_name
from reefvision.ml.providers import PixelBox, PixelPoint
from reefvision.schemas.provider_capabilities import ProviderBenchmarkCreateRequest
from reefvision.services.provider_capabilities import ProviderCapabilityService
from reefvision.storage.projects import resolve_managed_project_path


def _rss_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except Exception:
        return None


def _resolved_device(requested: str) -> str:
    normalized = requested.strip().casefold()
    if normalized not in {"", "auto", "gpu", "cuda"}:
        return requested
    try:
        import torch

        return "cuda:0" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _reset_cuda_peak(device: str) -> None:
    if not device.startswith("cuda"):
        return
    try:
        import torch

        torch.cuda.synchronize(device)
        torch.cuda.reset_peak_memory_stats(device)
    except Exception:
        return


def _cuda_peak(device: str) -> int | None:
    if not device.startswith("cuda"):
        return None
    try:
        import torch

        torch.cuda.synchronize(device)
        return int(torch.cuda.max_memory_allocated(device))
    except Exception:
        return None


def _mock_runner(width: int, height: int, batch_size: int) -> Callable[[Path | None], dict[str, float]]:
    side = max(8, min(512, int((width * height) ** 0.5)))
    seed = np.arange(side * side, dtype=np.float32).reshape(side, side)

    def run(_: Path | None) -> dict[str, float]:
        value = seed
        for _batch in range(batch_size):
            value = np.tanh(value * 0.0001 + 0.5)
        return {"output_mean": float(value.mean())}

    return run


def _ultralytics_runner(
    model_path: Path,
    *,
    task: str,
    device: str,
    width: int,
    height: int,
    batch_size: int,
    parameters: dict[str, Any],
) -> tuple[Callable[[Path | None], dict[str, float]], Callable[[], None]]:
    try:
        from ultralytics import YOLO
    except Exception as exc:
        raise ValidationError(f"Ultralytics is unavailable: {exc}") from exc

    model = YOLO(str(model_path))
    image_size: int | tuple[int, int] = max(width, height)

    def run(image_path: Path | None) -> dict[str, float]:
        if image_path is None:
            raise ValidationError("Ultralytics benchmarks require a managed image")
        results = model.predict(
            source=[str(image_path)] * batch_size,
            imgsz=image_size,
            device=device,
            conf=float(parameters.get("confidence", 0.25)),
            iou=float(parameters.get("iou_threshold", 0.45)),
            max_det=int(parameters.get("max_det", 1000)),
            verbose=False,
        )
        detections = 0
        mask_instances = 0
        for result in results:
            boxes = getattr(result, "boxes", None)
            masks = getattr(result, "masks", None)
            detections += int(len(boxes)) if boxes is not None else 0
            mask_instances += int(len(masks)) if masks is not None else 0
        return {
            "detections": float(detections),
            "mask_instances": float(mask_instances),
            "task_matches": 1.0 if str(getattr(model, "task", task)) == task else 0.0,
        }

    def close() -> None:
        nonlocal model
        model = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            return

    return run, close


def _assist_runner(
    provider_name: str,
    model_path: Path,
    image_path: Path,
    *,
    device: str,
) -> tuple[Callable[[Path | None], dict[str, float]], Callable[[], None]]:
    provider = assist_provider_for_name(provider_name)
    provider.load_model(model_path, device)
    prepared = provider.prepare_image(image_path)
    with Image.open(image_path) as source:
        width, height = source.size
    center = PixelPoint(x=width / 2.0, y=height / 2.0)
    context = PixelBox(
        x_min=width * 0.2,
        y_min=height * 0.2,
        x_max=width * 0.8,
        y_max=height * 0.8,
    )

    def run(_: Path | None) -> dict[str, float]:
        prediction = provider.predict_from_points(
            prepared,
            positive_points=[center],
            negative_points=[],
            context_box=context,
        )
        return {
            "mask_score": float(prediction.score),
            "mask_area_pixels": float(np.asarray(prediction.mask, dtype=bool).sum()),
        }

    return run, provider.unload_model


def _depth_runner(
    provider_id: str,
    model_id: str,
    *,
    device: str,
    local_files_only: bool,
    maximum_metric_depth: float | None,
) -> Callable[[Path | None], dict[str, float]]:
    runtime_provider = (
        provider_id
        if provider_id in {"luminance_relative", "depth_anything_v2_relative", "depth_anything_v2_metric"}
        else "depth_anything_v2_relative"
    )

    def run(image_path: Path | None) -> dict[str, float]:
        if image_path is None:
            raise ValidationError("Depth benchmarks require a managed image")
        values, _metadata = generate_depth_map(
            image_path,
            provider_id=runtime_provider,
            model_id=model_id,
            device=device,
            local_files_only=local_files_only,
            maximum_metric_depth=maximum_metric_depth,
        )
        finite = values[np.isfinite(values)]
        return {
            "finite_fraction": float(finite.size / max(values.size, 1)),
            "mean_depth": float(finite.mean()) if finite.size else 0.0,
        }

    return run


def _prepare_runner(
    settings: Settings,
    factory: sessionmaker[Session],
    request: dict[str, Any],
) -> tuple[Callable[[Path | None], dict[str, float]], Callable[[], None], list[Path], str]:
    provider_id = str(request["provider_id"])
    task = str(request["task"])
    device = _resolved_device(str(request.get("device_id", "auto")))
    image_ids = [str(value) for value in request.get("image_ids", [])]
    with factory() as session:
        images = list(
            session.scalars(select(ImageAsset).where(ImageAsset.id.in_(image_ids)))
        )
        image_paths = [
            resolve_managed_project_path(settings, image.managed_path) for image in images
        ]
        model = (
            session.get(ModelRegistration, str(request["model_id"]))
            if request.get("model_id")
            and provider_id
            not in {
                "depth_anything_v2",
                "depth_anything_v2_relative",
                "depth_anything_v2_metric",
            }
            else None
        )
        model_path = (
            resolve_managed_project_path(settings, model.managed_path)
            if model is not None
            else None
        )
        provider_name = model.provider_name if model is not None else provider_id

    if provider_id == "mock":
        return (
            _mock_runner(
                int(request.get("input_width", 640)),
                int(request.get("input_height", 640)),
                int(request.get("batch_size", 1)),
            ),
            lambda: None,
            image_paths,
            device,
        )
    if provider_id == "ultralytics":
        if model_path is None:
            raise ValidationError("Ultralytics benchmarks require a registered model")
        runner, close = _ultralytics_runner(
            model_path,
            task=task,
            device=device,
            width=int(request.get("input_width", 640)),
            height=int(request.get("input_height", 640)),
            batch_size=int(request.get("batch_size", 1)),
            parameters=dict(request.get("parameters") or {}),
        )
        return runner, close, image_paths, device
    if provider_id in {"segment_anything", "efficientvit_sam", "mobile_sam", "sam2"}:
        if model_path is None or not image_paths:
            raise ValidationError("Prompt-assist benchmarks require a registered model and image")
        runner, close = _assist_runner(
            provider_name,
            model_path,
            image_paths[0],
            device=device,
        )
        return runner, close, image_paths, device
    if provider_id in {
        "depth_anything_v2",
        "depth_anything_v2_relative",
        "depth_anything_v2_metric",
        "luminance_relative",
    }:
        model_id = str(request.get("model_id") or "depth-anything/Depth-Anything-V2-Small-hf")
        runner = _depth_runner(
            provider_id,
            model_id,
            device=device,
            local_files_only=bool(request.get("local_files_only", True)),
            maximum_metric_depth=(
                float(request["maximum_metric_depth"])
                if request.get("maximum_metric_depth") is not None
                else None
            ),
        )
        return runner, lambda: None, image_paths, device
    raise ValidationError(f"Queued benchmark execution is not implemented for {provider_id}")


def process_provider_benchmark_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "provider_benchmark" or job.status != "queued":
            return False
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.heartbeat_at = job.started_at
        job.error_message = None
        job.result_json = {"stage": "preparing"}
        session.commit()
        request = dict(job.request_json)

    runner: Callable[[Path | None], dict[str, float]] | None = None
    close: Callable[[], None] = lambda: None
    try:
        runner, close, image_paths, device = _prepare_runner(settings, factory, request)
        warmup_count = int(request.get("warmup_count", 0))
        sample_count = int(request.get("sample_count", 1))
        total = warmup_count + sample_count
        _reset_cuda_peak(device)
        baseline_ram = _rss_bytes()
        peak_ram = baseline_ram
        metric_sums: dict[str, float] = {}
        latencies: list[float] = []
        sample_paths = image_paths or [None]

        for index in range(total):
            with factory() as session:
                job = session.get(Job, job_id)
                if job is None:
                    return False
                if job.status == "cancel_requested":
                    job.status = "cancelled"
                    job.completed_at = datetime.now(UTC)
                    job.result_json = {"stage": "cancelled"}
                    session.commit()
                    return True
            path = sample_paths[index % len(sample_paths)]
            started = time.perf_counter()
            metrics = runner(path)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if index >= warmup_count:
                latencies.append(elapsed_ms)
                for key, value in metrics.items():
                    metric_sums[key] = metric_sums.get(key, 0.0) + float(value)
            current_ram = _rss_bytes()
            if current_ram is not None:
                peak_ram = max(peak_ram or current_ram, current_ram)
            with factory() as session:
                job = session.get(Job, job_id)
                if job is None:
                    return False
                job.progress_current = index + 1
                job.progress_total = total
                job.heartbeat_at = datetime.now(UTC)
                job.checkpoint_json = {
                    "completed_iterations": index + 1,
                    "warmup_count": warmup_count,
                    "sample_count": sample_count,
                }
                job.result_json = {
                    "stage": "benchmarking",
                    "device_id": device,
                    "completed_iterations": index + 1,
                }
                session.commit()

        elapsed_seconds = sum(latencies) / 1000.0
        quality_metrics = {
            key: value / sample_count for key, value in metric_sums.items()
        }
        benchmark_request = ProviderBenchmarkCreateRequest(
            provider_id=str(request["provider_id"]),
            model_id=(str(request["model_id"]) if request.get("model_id") else None),
            device_id=device,
            task=str(request["task"]),
            input_width=int(request.get("input_width", 640)),
            input_height=int(request.get("input_height", 640)),
            batch_size=int(request.get("batch_size", 1)),
            sample_count=sample_count,
            warmup_count=warmup_count,
            latencies_ms=latencies,
            elapsed_seconds=max(elapsed_seconds, 1e-9),
            peak_ram_bytes=(
                max((peak_ram or 0) - (baseline_ram or 0), 0)
                if peak_ram is not None
                else None
            ),
            peak_vram_bytes=_cuda_peak(device),
            quality_metrics=quality_metrics,
            parameters={
                **dict(request.get("parameters") or {}),
                "execution_mode": "queued_provider_benchmark",
            },
        )
        with factory() as session:
            record = ProviderCapabilityService(session, settings).record_benchmark(
                benchmark_request
            )
            job = session.get(Job, job_id)
            if job is None:
                return False
            job.status = "succeeded"
            job.progress_current = total
            job.progress_total = total
            job.completed_at = datetime.now(UTC)
            job.heartbeat_at = job.completed_at
            job.result_json = {
                "stage": "completed",
                "benchmark": record.model_dump(mode="json"),
            }
            session.commit()
        return True
    except Exception as exc:
        with factory() as session:
            job = session.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = datetime.now(UTC)
                job.result_json = {"stage": "failed", "error": str(exc)}
                session.commit()
        return False
    finally:
        try:
            close()
        except Exception:
            pass
