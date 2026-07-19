"""Unified ML-provider capability, health, memory, and benchmark schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ProviderHealth = Literal["ready", "degraded", "unavailable"]
DeviceKind = Literal["cpu", "cuda", "mps", "directml", "unknown"]


class ProviderDependencyStatus(BaseModel):
    package: str
    import_name: str
    installed: bool
    version: str | None = None
    required: bool = True
    minimum_version: str | None = None
    message: str | None = None


class ProviderDeviceStatus(BaseModel):
    device_id: str
    kind: DeviceKind
    display_name: str
    available: bool
    total_memory_bytes: int | None = Field(default=None, ge=0)
    free_memory_bytes: int | None = Field(default=None, ge=0)
    compute_capability: str | None = None
    supports_mixed_precision: bool = False
    warnings: list[str] = Field(default_factory=list)


class ProviderModelAssetStatus(BaseModel):
    model_id: str
    name: str
    task: str
    managed_path: str
    expected_sha256: str | None = None
    observed_sha256: str | None = None
    checksum_verified: bool | None = None
    exists: bool
    size_bytes: int | None = Field(default=None, ge=0)
    compatible: bool
    messages: list[str] = Field(default_factory=list)


class ProviderBenchmarkRecord(BaseModel):
    provider_id: str
    model_id: str | None = None
    device_id: str
    task: str
    input_width: int = Field(ge=1)
    input_height: int = Field(ge=1)
    batch_size: int = Field(ge=1)
    sample_count: int = Field(ge=1)
    warmup_count: int = Field(default=0, ge=0)
    mean_latency_ms: float = Field(ge=0)
    median_latency_ms: float = Field(ge=0)
    p95_latency_ms: float = Field(ge=0)
    throughput_per_second: float = Field(ge=0)
    peak_ram_bytes: int | None = Field(default=None, ge=0)
    peak_vram_bytes: int | None = Field(default=None, ge=0)
    quality_metrics: dict[str, float] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime


class ProviderCapabilityResponse(BaseModel):
    provider_id: str
    display_name: str
    description: str
    health: ProviderHealth
    supported_tasks: list[str]
    supported_prompt_types: list[str]
    supports_training: bool
    supports_inference: bool
    supports_video: bool
    supports_batching: bool
    supports_cpu: bool
    supports_cuda: bool
    supports_mixed_precision: bool
    supports_offline_import: bool
    provider_version: str | None = None
    dependencies: list[ProviderDependencyStatus]
    devices: list[ProviderDeviceStatus]
    model_assets: list[ProviderModelAssetStatus]
    estimated_vram_bytes: dict[str, int] = Field(default_factory=dict)
    recent_benchmarks: list[ProviderBenchmarkRecord] = Field(default_factory=list)
    warnings: list[str]
    remediation: list[str]


class ProviderCapabilityListResponse(BaseModel):
    generated_at: datetime
    reefvision_version: str
    providers: list[ProviderCapabilityResponse]


class ProviderBenchmarkCreateRequest(BaseModel):
    provider_id: str = Field(min_length=1, max_length=100)
    model_id: str | None = Field(default=None, max_length=100)
    device_id: str = Field(min_length=1, max_length=200)
    task: str = Field(min_length=1, max_length=100)
    input_width: int = Field(ge=1, le=100_000)
    input_height: int = Field(ge=1, le=100_000)
    batch_size: int = Field(default=1, ge=1, le=100_000)
    sample_count: int = Field(ge=1, le=10_000_000)
    warmup_count: int = Field(default=0, ge=0, le=1_000_000)
    latencies_ms: list[float] = Field(min_length=1, max_length=10_000_000)
    elapsed_seconds: float = Field(gt=0)
    peak_ram_bytes: int | None = Field(default=None, ge=0)
    peak_vram_bytes: int | None = Field(default=None, ge=0)
    quality_metrics: dict[str, float] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ProviderBenchmarkComparisonResponse(BaseModel):
    records: list[ProviderBenchmarkRecord]
    fastest_record: ProviderBenchmarkRecord | None = None
    lowest_vram_record: ProviderBenchmarkRecord | None = None
    warnings: list[str]
