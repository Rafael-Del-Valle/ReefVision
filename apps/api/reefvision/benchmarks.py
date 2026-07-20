"""Repeatable ReefVision latency, throughput, RAM, and VRAM benchmarks."""

from __future__ import annotations

import gc
import json
import math
import os
import statistics
import time
import tracemalloc
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import numpy as np
from PIL import Image

T = TypeVar("T")


@dataclass(frozen=True)
class BenchmarkResult:
    name: str
    iterations: int
    warmup_iterations: int
    minimum_ms: float
    median_ms: float
    mean_ms: float
    p95_ms: float
    maximum_ms: float
    operations_per_second: float
    throughput_per_second: float | None
    throughput_unit: str | None
    peak_python_bytes: int
    process_rss_bytes: int | None
    cuda_peak_allocated_bytes: int | None
    cuda_peak_reserved_bytes: int | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkSuiteResult:
    schema_version: int
    generated_at_unix: float
    platform: str
    python_version: str
    results: tuple[BenchmarkResult, ...]
    skipped: dict[str, str]


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _process_rss() -> int | None:
    try:
        import psutil

        return int(psutil.Process(os.getpid()).memory_info().rss)
    except ImportError:
        if os.name == "nt":
            return None
        try:
            import resource

            getrusage = getattr(resource, "getrusage", None)
            rusage_self = getattr(resource, "RUSAGE_SELF", None)
            if getrusage is None or rusage_self is None:
                return None
            observed = int(getrusage(rusage_self).ru_maxrss)
            return observed * 1024
        except ImportError:
            return None


def _cuda_reset() -> bool:
    try:
        import torch

        if not torch.cuda.is_available():
            return False
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
        return True
    except ImportError:
        return False


def _cuda_peaks(enabled: bool) -> tuple[int | None, int | None]:
    if not enabled:
        return None, None
    import torch

    torch.cuda.synchronize()
    return int(torch.cuda.max_memory_allocated()), int(torch.cuda.max_memory_reserved())


def run_benchmark(
    name: str,
    operation: Callable[[], T],
    *,
    iterations: int = 10,
    warmup_iterations: int = 2,
    throughput_amount: float | None = None,
    throughput_unit: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> BenchmarkResult:
    if iterations < 1 or warmup_iterations < 0:
        raise ValueError("Benchmark iteration counts are invalid")
    for _ in range(warmup_iterations):
        operation()
    gc.collect()
    cuda_enabled = _cuda_reset()
    tracemalloc.start()
    durations: list[float] = []
    try:
        for _ in range(iterations):
            started = time.perf_counter_ns()
            operation()
            elapsed = time.perf_counter_ns() - started
            durations.append(elapsed / 1_000_000)
        _, peak_python = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    median = statistics.median(durations)
    mean = statistics.fmean(durations)
    operations_per_second = 1000.0 / mean if mean > 0 else math.inf
    throughput = None
    if throughput_amount is not None:
        throughput = throughput_amount * operations_per_second
    cuda_allocated, cuda_reserved = _cuda_peaks(cuda_enabled)
    return BenchmarkResult(
        name=name,
        iterations=iterations,
        warmup_iterations=warmup_iterations,
        minimum_ms=min(durations),
        median_ms=median,
        mean_ms=mean,
        p95_ms=_percentile(durations, 0.95),
        maximum_ms=max(durations),
        operations_per_second=operations_per_second,
        throughput_per_second=throughput,
        throughput_unit=throughput_unit,
        peak_python_bytes=int(peak_python),
        process_rss_bytes=_process_rss(),
        cuda_peak_allocated_bytes=cuda_allocated,
        cuda_peak_reserved_bytes=cuda_reserved,
        metadata=dict(metadata or {}),
    )


def _image_paths(root: Path) -> list[Path]:
    return sorted((root / "images").glob("*.png"))


def synthetic_benchmark_suite(root: Path) -> BenchmarkSuiteResult:
    """Run provider-free benchmarks against a generated synthetic acceptance bundle."""

    import platform
    import sys

    image_paths = _image_paths(root)
    if not image_paths:
        raise ValueError("Synthetic acceptance bundle contains no images")
    first_image = image_paths[0]
    mask_path = root / "masks" / "known-area-rectangle.png"
    output_root = root / "benchmark-output"
    output_root.mkdir(parents=True, exist_ok=True)
    results: list[BenchmarkResult] = []
    skipped: dict[str, str] = {}

    results.append(
        run_benchmark(
            "project_opening",
            lambda: tuple(path.stat().st_size for path in root.rglob("*") if path.is_file()),
            metadata={"file_count": sum(1 for path in root.rglob("*") if path.is_file())},
        )
    )
    results.append(
        run_benchmark(
            "gallery_rendering_data",
            lambda: [
                (path.name, path.stat().st_size, path.suffix.casefold()) for path in image_paths
            ],
            throughput_amount=float(len(image_paths)),
            throughput_unit="images",
        )
    )

    def switch_image() -> tuple[int, int]:
        with Image.open(first_image) as image:
            image.load()
            width, height = image.size
            return int(width), int(height)

    results.append(run_benchmark("image_switching", switch_image))
    annotation_path = output_root / "annotation.json"

    def save_annotation() -> None:
        temporary = annotation_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"class": "synthetic coral", "bbox": [40, 50, 80, 60]}),
            encoding="utf-8",
        )
        os.replace(temporary, annotation_path)

    results.append(run_benchmark("annotation_save_latency", save_annotation))

    with Image.open(mask_path) as source:
        base_mask = np.asarray(source.convert("L"), dtype=np.uint8) > 0

    def raster_edit() -> int:
        edited = base_mask.copy()
        edited[60:90, 80:140] = True
        edited[72:78, 92:98] = False
        return int(edited.sum())

    results.append(run_benchmark("raster_editing", raster_edit))
    large_mask = np.tile(base_mask, (6, 6))

    def composite_large_mask() -> int:
        overlay = np.zeros((*large_mask.shape, 4), dtype=np.uint8)
        overlay[large_mask] = (255, 255, 255, 128)
        return int(overlay[..., 3].sum())

    results.append(run_benchmark("large_mask_compositing", composite_large_mask, iterations=5))

    def snapshot_dataset() -> str:
        import hashlib

        digest = hashlib.sha256()
        for path in image_paths:
            digest.update(path.read_bytes())
        return digest.hexdigest()

    results.append(run_benchmark("dataset_snapshot_creation", snapshot_dataset))
    archive_path = output_root / "export.zip"

    def export_archive() -> int:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in image_paths:
                archive.write(path, arcname=path.name)
        return archive_path.stat().st_size

    source_bytes = float(sum(path.stat().st_size for path in image_paths))
    results.append(
        run_benchmark(
            "export_throughput",
            export_archive,
            iterations=5,
            throughput_amount=source_bytes,
            throughput_unit="source_bytes",
        )
    )

    trajectory_path = root / "video" / "identity-crossing-trajectories.json"
    results.append(
        run_benchmark(
            "tracking_frame_data",
            lambda: json.loads(trajectory_path.read_text(encoding="utf-8")),
            throughput_amount=30,
            throughput_unit="frames",
        )
    )

    relative_depth = np.load(root / "depth" / "relative-depth.npy", allow_pickle=False)
    results.append(
        run_benchmark(
            "depth_map_processing",
            lambda: np.percentile(relative_depth, [5, 50, 95]),
            throughput_amount=float(relative_depth.size),
            throughput_unit="pixels",
        )
    )

    skipped.update(
        {
            "model_loading": "Requires a selected registered model checkpoint.",
            "inference_throughput": "Requires a selected provider and checkpoint.",
            "video_decoding": "Provider-free suite validates AVI structure only.",
            "tracking_fps": "Requires a selected detector/tracker provider.",
            "embedding_generation": "Requires a selected embedding provider.",
            "workflow_scheduling": "Covered by the persisted workflow benchmark endpoint.",
        }
    )
    return BenchmarkSuiteResult(
        schema_version=1,
        generated_at_unix=time.time(),
        platform=platform.platform(),
        python_version=sys.version,
        results=tuple(results),
        skipped=skipped,
    )


def write_benchmark_suite(path: Path, suite: BenchmarkSuiteResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(suite)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def summarize_benchmarks(results: Iterable[BenchmarkResult]) -> dict[str, float]:
    return {result.name: result.median_ms for result in results}
