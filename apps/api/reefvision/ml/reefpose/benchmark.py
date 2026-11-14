"""Reproducible synthetic engineering benchmarks for ReefPose-S."""

from __future__ import annotations

import math
import platform
import statistics
import time
from dataclasses import dataclass
from typing import Any

import torch

from reefvision.ml.reefpose.errors import ReefPoseValidationError
from reefvision.ml.reefpose.losses import ReefPoseLoss
from reefvision.ml.reefpose.model import ReefPoseConfig, ReefPoseS
from reefvision.ml.reefpose.targets import ReefPoseTargets
from reefvision.ml.reefpose.training import resolve_device


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    model: ReefPoseConfig
    device: str = "auto"
    batch_size: int = 1
    warmup_iterations: int = 5
    inference_iterations: int = 50
    training_steps: int = 20
    amp: bool = True
    seed: int = 1337

    def __post_init__(self) -> None:
        if self.batch_size < 1:
            raise ReefPoseValidationError("Benchmark batch size must be positive")
        if self.warmup_iterations < 0:
            raise ReefPoseValidationError("Benchmark warmup iterations cannot be negative")
        if self.inference_iterations < 1:
            raise ReefPoseValidationError("Benchmark inference iterations must be positive")
        if self.training_steps < 1:
            raise ReefPoseValidationError("Benchmark training steps must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model.to_dict(),
            "device": self.device,
            "batch_size": self.batch_size,
            "warmup_iterations": self.warmup_iterations,
            "inference_iterations": self.inference_iterations,
            "training_steps": self.training_steps,
            "amp_requested": self.amp,
            "seed": self.seed,
        }


def _synchronize(device: torch.device) -> None:
    if device.type == "cuda":
        torch.cuda.synchronize(device)


def _peak_memory(device: torch.device) -> int:
    if device.type != "cuda":
        return 0
    return int(torch.cuda.max_memory_allocated(device))


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def run_benchmark(config: BenchmarkConfig) -> dict[str, Any]:
    """Measure one fixed synthetic workload; this is not an accuracy evaluation."""

    device = resolve_device(config.device)
    amp_enabled = config.amp and device.type == "cuda"
    torch.manual_seed(config.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(config.seed)
    model = ReefPoseS(config.model).to(device)
    parameter_count = sum(parameter.numel() for parameter in model.parameters())
    trainable_parameter_count = sum(
        parameter.numel() for parameter in model.parameters() if parameter.requires_grad
    )
    images = torch.randn(
        config.batch_size,
        config.model.input_channels,
        config.model.input_height,
        config.model.input_width,
        device=device,
    )

    model.eval()
    with torch.inference_mode():
        for _ in range(config.warmup_iterations):
            with torch.amp.autocast(  # type: ignore[attr-defined]
                device_type=device.type, enabled=amp_enabled
            ):
                model(images)
        _synchronize(device)
        if device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(device)
        inference_durations: list[float] = []
        for _ in range(config.inference_iterations):
            _synchronize(device)
            started = time.perf_counter()
            with torch.amp.autocast(  # type: ignore[attr-defined]
                device_type=device.type, enabled=amp_enabled
            ):
                model(images)
            _synchronize(device)
            inference_durations.append(time.perf_counter() - started)
        inference_peak_memory = _peak_memory(device)

    total_inference_seconds = sum(inference_durations)
    mean_latency_seconds = statistics.fmean(inference_durations)

    model.train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=1e-4)
    scaler = torch.amp.GradScaler("cuda", enabled=amp_enabled)  # type: ignore[attr-defined]
    criterion = ReefPoseLoss()
    heatmap_height = config.model.input_height // config.model.heatmap_stride
    heatmap_width = config.model.input_width // config.model.heatmap_stride
    targets = ReefPoseTargets(
        heatmaps=torch.rand(
            config.batch_size,
            config.model.num_keypoints,
            heatmap_height,
            heatmap_width,
            device=device,
        ),
        heatmap_weights=torch.ones(config.batch_size, config.model.num_keypoints, device=device),
        visibility_targets=torch.ones(config.batch_size, config.model.num_keypoints, device=device),
    )
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    _synchronize(device)
    training_started = time.perf_counter()
    final_loss = 0.0
    for _ in range(config.training_steps):
        optimizer.zero_grad(set_to_none=True)
        with torch.amp.autocast(  # type: ignore[attr-defined]
            device_type=device.type, enabled=amp_enabled
        ):
            loss = criterion(model(images), targets).total
        scaler.scale(loss).backward()
        scaler.step(optimizer)
        scaler.update()
        final_loss = float(loss.detach())
    _synchronize(device)
    training_seconds = time.perf_counter() - training_started
    training_peak_memory = _peak_memory(device)

    device_name = (
        torch.cuda.get_device_name(device)
        if device.type == "cuda"
        else platform.processor() or "CPU"
    )
    return {
        "schema_version": "reefpose-benchmark-0001",
        "synthetic_fixture": True,
        "biological_accuracy_validated": False,
        "validation_notice": (
            "Synthetic tensors validate engineering performance only; real labeled animal data "
            "is required for biological accuracy evaluation."
        ),
        "configuration": config.to_dict(),
        "runtime": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "torch_version": str(torch.__version__),
            "cuda_version": torch.version.cuda,
            "cudnn_version": torch.backends.cudnn.version(),  # type: ignore[no-untyped-call]
            "device": str(device),
            "device_type": device.type,
            "device_name": device_name,
            "amp_enabled": amp_enabled,
        },
        "model": {
            "architecture": model.architecture_name,
            "architecture_version": model.architecture_version,
            "parameter_count": parameter_count,
            "trainable_parameter_count": trainable_parameter_count,
        },
        "inference": {
            "batch_size": config.batch_size,
            "iterations": config.inference_iterations,
            "mean_latency_ms": mean_latency_seconds * 1000.0,
            "p50_latency_ms": _percentile(inference_durations, 0.50) * 1000.0,
            "p95_latency_ms": _percentile(inference_durations, 0.95) * 1000.0,
            "images_per_second": (
                config.batch_size * config.inference_iterations / total_inference_seconds
            ),
            "peak_gpu_memory_bytes": inference_peak_memory,
        },
        "training": {
            "batch_size": config.batch_size,
            "steps": config.training_steps,
            "steps_per_second": config.training_steps / training_seconds,
            "images_per_second": config.batch_size * config.training_steps / training_seconds,
            "peak_gpu_memory_bytes": training_peak_memory,
            "final_synthetic_loss": final_loss,
        },
    }
