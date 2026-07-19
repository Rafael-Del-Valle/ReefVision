"""Unified provider readiness, device, model-integrity, and benchmark service."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import platform
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision import __version__
from reefvision.config import Settings
from reefvision.db.models import ModelRegistration
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.provider_capabilities import (
    ProviderBenchmarkComparisonResponse,
    ProviderBenchmarkCreateRequest,
    ProviderBenchmarkRecord,
    ProviderCapabilityListResponse,
    ProviderCapabilityResponse,
    ProviderDependencyStatus,
    ProviderDeviceStatus,
    ProviderModelAssetStatus,
)
from reefvision.storage.projects import resolve_managed_project_path


@dataclass(frozen=True)
class _Dependency:
    package: str
    import_name: str
    required: bool = True
    minimum_version: str | None = None


@dataclass(frozen=True)
class _ProviderSpec:
    provider_id: str
    display_name: str
    description: str
    tasks: tuple[str, ...]
    prompts: tuple[str, ...]
    dependencies: tuple[_Dependency, ...]
    training: bool
    inference: bool
    video: bool
    batching: bool
    cpu: bool
    cuda: bool
    mixed_precision: bool
    offline_import: bool
    estimated_vram: dict[str, int]


_GIB = 1024**3
_PROVIDER_SPECS: tuple[_ProviderSpec, ...] = (
    _ProviderSpec(
        provider_id="mock",
        display_name="Mock provider",
        description="Deterministic provider-free acceptance and UI testing.",
        tasks=("detect", "segment", "classify", "depth", "embed", "track"),
        prompts=("box", "positive_point", "negative_point", "brush"),
        dependencies=(),
        training=False,
        inference=True,
        video=True,
        batching=True,
        cpu=True,
        cuda=False,
        mixed_precision=False,
        offline_import=True,
        estimated_vram={"default": 0},
    ),
    _ProviderSpec(
        provider_id="ultralytics",
        display_name="Ultralytics YOLO",
        description="Detection, instance segmentation, classification, training, and tracking.",
        tasks=("detect", "segment", "classify", "track"),
        prompts=(),
        dependencies=(
            _Dependency("ultralytics", "ultralytics"),
            _Dependency("torch", "torch"),
        ),
        training=True,
        inference=True,
        video=True,
        batching=True,
        cpu=True,
        cuda=True,
        mixed_precision=True,
        offline_import=True,
        estimated_vram={
            "nano_640_batch1": 1 * _GIB,
            "small_640_batch8": 4 * _GIB,
            "xlarge_1920_batch2": 11 * _GIB,
        },
    ),
    _ProviderSpec(
        provider_id="efficientvit_sam",
        display_name="EfficientViT-SAM",
        description="Prompt-based image segmentation using points, boxes, and mask refinement.",
        tasks=("prompt_segment", "automatic_mask"),
        prompts=("box", "positive_point", "negative_point", "brush", "existing_mask"),
        dependencies=(
            _Dependency("torch", "torch"),
            _Dependency("efficientvit", "efficientvit"),
        ),
        training=False,
        inference=True,
        video=False,
        batching=True,
        cpu=True,
        cuda=True,
        mixed_precision=True,
        offline_import=True,
        estimated_vram={"l0_1024": 2 * _GIB, "l2_1024": 5 * _GIB},
    ),
    _ProviderSpec(
        provider_id="sam2",
        display_name="SAM 2",
        description="Prompt segmentation for images and temporally propagated video masks.",
        tasks=("prompt_segment", "video_mask_propagation", "automatic_mask"),
        prompts=("box", "positive_point", "negative_point", "existing_mask"),
        dependencies=(
            _Dependency("torch", "torch"),
            _Dependency("sam2", "sam2"),
        ),
        training=False,
        inference=True,
        video=True,
        batching=True,
        cpu=False,
        cuda=True,
        mixed_precision=True,
        offline_import=True,
        estimated_vram={"tiny_1024": 4 * _GIB, "large_1024": 12 * _GIB},
    ),
    _ProviderSpec(
        provider_id="nnunet",
        display_name="nnU-Net v2",
        description="Semantic segmentation training and inference for curated mask datasets.",
        tasks=("semantic_segment",),
        prompts=(),
        dependencies=(
            _Dependency("torch", "torch"),
            _Dependency("nnunetv2", "nnunetv2"),
        ),
        training=True,
        inference=True,
        video=False,
        batching=False,
        cpu=True,
        cuda=True,
        mixed_precision=True,
        offline_import=True,
        estimated_vram={"2d_512": 6 * _GIB, "2d_full_resolution": 12 * _GIB},
    ),
    _ProviderSpec(
        provider_id="depth_anything_v2",
        display_name="Depth Anything V2",
        description="Relative or calibrated monocular depth maps for images and video frames.",
        tasks=("depth",),
        prompts=(),
        dependencies=(
            _Dependency("torch", "torch"),
            _Dependency("transformers", "transformers"),
        ),
        training=False,
        inference=True,
        video=True,
        batching=True,
        cpu=True,
        cuda=True,
        mixed_precision=True,
        offline_import=True,
        estimated_vram={"small_518": 2 * _GIB, "large_518": 7 * _GIB},
    ),
    _ProviderSpec(
        provider_id="torchvision_embeddings",
        display_name="Torchvision embeddings",
        description="Image and crop embeddings for diversity-aware active learning.",
        tasks=("embed_image", "embed_crop", "embed_mask", "embed_video_frame"),
        prompts=(),
        dependencies=(
            _Dependency("torch", "torch"),
            _Dependency("torchvision", "torchvision"),
        ),
        training=False,
        inference=True,
        video=True,
        batching=True,
        cpu=True,
        cuda=True,
        mixed_precision=True,
        offline_import=True,
        estimated_vram={"resnet50_batch32": 3 * _GIB, "vit_large_batch8": 9 * _GIB},
    ),
)


def _package_version(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class ProviderCapabilityService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.benchmark_path = settings.resolved_data_dir / "provider-benchmarks.json"

    def _dependencies(self, spec: _ProviderSpec) -> list[ProviderDependencyStatus]:
        output: list[ProviderDependencyStatus] = []
        for dependency in spec.dependencies:
            installed = importlib.util.find_spec(dependency.import_name) is not None
            observed_version = _package_version(dependency.package) if installed else None
            message = None
            if not installed:
                message = f"Install the optional {dependency.package} provider dependency."
            output.append(
                ProviderDependencyStatus(
                    package=dependency.package,
                    import_name=dependency.import_name,
                    installed=installed,
                    version=observed_version,
                    required=dependency.required,
                    minimum_version=dependency.minimum_version,
                    message=message,
                )
            )
        return output

    def _devices(self) -> list[ProviderDeviceStatus]:
        devices = [
            ProviderDeviceStatus(
                device_id="cpu",
                kind="cpu",
                display_name=platform.processor() or "CPU",
                available=True,
                supports_mixed_precision=False,
            )
        ]
        try:
            import torch
        except ImportError:
            return devices
        if torch.cuda.is_available():
            for index in range(torch.cuda.device_count()):
                properties = torch.cuda.get_device_properties(index)
                free_memory = None
                try:
                    free_memory, _total = torch.cuda.mem_get_info(index)
                except (RuntimeError, TypeError):
                    pass
                major = getattr(properties, "major", None)
                minor = getattr(properties, "minor", None)
                capability = (
                    f"{major}.{minor}" if major is not None and minor is not None else None
                )
                devices.append(
                    ProviderDeviceStatus(
                        device_id=f"cuda:{index}",
                        kind="cuda",
                        display_name=str(properties.name),
                        available=True,
                        total_memory_bytes=int(properties.total_memory),
                        free_memory_bytes=int(free_memory) if free_memory is not None else None,
                        compute_capability=capability,
                        supports_mixed_precision=True,
                    )
                )
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            devices.append(
                ProviderDeviceStatus(
                    device_id="mps",
                    kind="mps",
                    display_name="Apple Metal Performance Shaders",
                    available=True,
                    supports_mixed_precision=True,
                )
            )
        return devices

    def _model_assets(self, spec: _ProviderSpec) -> list[ProviderModelAssetStatus]:
        models = list(
            self.session.scalars(
                select(ModelRegistration).order_by(ModelRegistration.created_at, ModelRegistration.id)
            )
        )
        output: list[ProviderModelAssetStatus] = []
        for model in models:
            provider_name = str(getattr(model, "provider_name", "") or "").casefold()
            provider_id = str(getattr(model, "provider_id", "") or "").casefold()
            if spec.provider_id.casefold() not in {provider_name, provider_id}:
                continue
            messages: list[str] = []
            try:
                path = resolve_managed_project_path(self.settings, model.managed_path)
                exists = path.is_file()
            except ValidationError:
                path = Path(model.managed_path)
                exists = False
                messages.append("Managed model path failed project-root validation.")
            expected = getattr(model, "sha256", None)
            observed = None
            verified = None
            size_bytes = None
            if exists:
                size_bytes = path.stat().st_size
                if expected:
                    observed = _sha256(path)
                    verified = observed == expected
                    if not verified:
                        messages.append("Model checksum does not match its registration.")
            else:
                messages.append("Registered model file is missing.")
            task = str(getattr(model, "task", "") or getattr(model, "purpose", ""))
            compatible = task in spec.tasks or (
                task == "segmenter" and "segment" in spec.tasks
            )
            if not compatible:
                messages.append("Registered task is not advertised by this provider.")
            output.append(
                ProviderModelAssetStatus(
                    model_id=model.id,
                    name=str(getattr(model, "name", model.id)),
                    task=task,
                    managed_path=model.managed_path,
                    expected_sha256=expected,
                    observed_sha256=observed,
                    checksum_verified=verified,
                    exists=exists,
                    size_bytes=size_bytes,
                    compatible=compatible,
                    messages=messages,
                )
            )
        return output

    def _read_benchmarks(self) -> list[ProviderBenchmarkRecord]:
        if not self.benchmark_path.is_file():
            return []
        try:
            payload = json.loads(self.benchmark_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        records: list[ProviderBenchmarkRecord] = []
        for item in payload:
            try:
                records.append(ProviderBenchmarkRecord.model_validate(item))
            except ValueError:
                continue
        return records

    def _write_benchmarks(self, records: list[ProviderBenchmarkRecord]) -> None:
        self.benchmark_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.benchmark_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                [record.model_dump(mode="json") for record in records],
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, self.benchmark_path)

    def list(self) -> ProviderCapabilityListResponse:
        devices = self._devices()
        benchmark_records = self._read_benchmarks()
        providers: list[ProviderCapabilityResponse] = []
        for spec in _PROVIDER_SPECS:
            dependencies = self._dependencies(spec)
            assets = self._model_assets(spec)
            missing_required = [item.package for item in dependencies if item.required and not item.installed]
            broken_assets = [item.model_id for item in assets if not item.exists or item.checksum_verified is False]
            warnings: list[str] = []
            remediation: list[str] = []
            if missing_required:
                warnings.append("Required optional packages are not installed: " + ", ".join(missing_required))
                remediation.append("Install the provider from the Model Catalog or use offline import.")
            if broken_assets:
                warnings.append(f"{len(broken_assets)} registered model assets are missing or corrupted.")
                remediation.append("Reinstall affected model assets after reviewing their registration checksums.")
            compatible_device = any(
                device.available
                and ((device.kind == "cpu" and spec.cpu) or (device.kind == "cuda" and spec.cuda) or device.kind == "mps")
                for device in devices
            )
            if not compatible_device:
                warnings.append("No compatible execution device is available.")
                remediation.append("Install a compatible runtime or choose a provider that supports CPU execution.")
            if missing_required or not compatible_device:
                health = "unavailable"
            elif broken_assets:
                health = "degraded"
            else:
                health = "ready"
            provider_version = next((item.version for item in dependencies if item.version), None)
            recent = [
                item for item in benchmark_records if item.provider_id == spec.provider_id
            ][-20:]
            providers.append(
                ProviderCapabilityResponse(
                    provider_id=spec.provider_id,
                    display_name=spec.display_name,
                    description=spec.description,
                    health=health,
                    supported_tasks=list(spec.tasks),
                    supported_prompt_types=list(spec.prompts),
                    supports_training=spec.training,
                    supports_inference=spec.inference,
                    supports_video=spec.video,
                    supports_batching=spec.batching,
                    supports_cpu=spec.cpu,
                    supports_cuda=spec.cuda,
                    supports_mixed_precision=spec.mixed_precision,
                    supports_offline_import=spec.offline_import,
                    provider_version=provider_version,
                    dependencies=dependencies,
                    devices=devices,
                    model_assets=assets,
                    estimated_vram_bytes=dict(spec.estimated_vram),
                    recent_benchmarks=recent,
                    warnings=warnings,
                    remediation=remediation,
                )
            )
        return ProviderCapabilityListResponse(
            generated_at=datetime.now(UTC),
            reefvision_version=__version__,
            providers=providers,
        )

    def get(self, provider_id: str) -> ProviderCapabilityResponse:
        result = next(
            (item for item in self.list().providers if item.provider_id == provider_id),
            None,
        )
        if result is None:
            raise NotFoundError("Provider capability record not found")
        return result

    def record_benchmark(
        self,
        request: ProviderBenchmarkCreateRequest,
    ) -> ProviderBenchmarkRecord:
        if request.provider_id not in {item.provider_id for item in _PROVIDER_SPECS}:
            raise ValidationError("Unknown provider id")
        latencies = [float(value) for value in request.latencies_ms]
        if any(not math.isfinite(value) or value < 0 for value in latencies):
            raise ValidationError("Benchmark latencies must be finite and non-negative")
        record = ProviderBenchmarkRecord(
            provider_id=request.provider_id,
            model_id=request.model_id,
            device_id=request.device_id,
            task=request.task,
            input_width=request.input_width,
            input_height=request.input_height,
            batch_size=request.batch_size,
            sample_count=request.sample_count,
            warmup_count=request.warmup_count,
            mean_latency_ms=statistics.fmean(latencies),
            median_latency_ms=statistics.median(latencies),
            p95_latency_ms=_percentile(latencies, 0.95),
            throughput_per_second=request.sample_count / request.elapsed_seconds,
            peak_ram_bytes=request.peak_ram_bytes,
            peak_vram_bytes=request.peak_vram_bytes,
            quality_metrics=dict(request.quality_metrics),
            parameters=dict(request.parameters),
            recorded_at=datetime.now(UTC),
        )
        records = self._read_benchmarks()
        records.append(record)
        self._write_benchmarks(records[-10_000:])
        return record

    def compare_benchmarks(
        self,
        *,
        provider_id: str | None = None,
        task: str | None = None,
    ) -> ProviderBenchmarkComparisonResponse:
        records = [
            item
            for item in self._read_benchmarks()
            if (provider_id is None or item.provider_id == provider_id)
            and (task is None or item.task == task)
        ]
        fastest = max(records, key=lambda item: item.throughput_per_second, default=None)
        with_vram = [item for item in records if item.peak_vram_bytes is not None]
        lowest_vram = min(with_vram, key=lambda item: item.peak_vram_bytes or 0, default=None)
        warnings = [] if records else ["No matching provider benchmark records are available."]
        return ProviderBenchmarkComparisonResponse(
            records=sorted(records, key=lambda item: item.recorded_at, reverse=True),
            fastest_record=fastest,
            lowest_vram_record=lowest_vram,
            warnings=warnings,
        )
