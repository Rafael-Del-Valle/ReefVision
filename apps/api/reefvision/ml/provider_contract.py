"""Provider contracts shared by training, inference, depth, and tracking engines.

The original :class:`ProviderAdapter` contract remains available for the workflow
engine.  The lifecycle types below are the richer, model-scoped contract used by
the model catalog, provider acceptance, Prompt Assist, depth, and embedding
workflows.  Keeping the contract free of framework and database types makes it
possible to test lifecycle behavior without importing optional ML packages.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from threading import Event
from typing import Any, Protocol, runtime_checkable


class ProviderState(StrEnum):
    READY = "ready"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"
    LOADING = "loading"
    LOADED = "loaded"
    FAILED = "failed"
    UNLOADED = "unloaded"


class DeviceMode(StrEnum):
    AUTO = "auto"
    CPU = "cpu"
    CUDA = "cuda"


class CheckpointKind(StrEnum):
    FILE = "file"
    DIRECTORY = "directory"


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Fine-grained controls exposed to API and UI consumers."""

    discover: bool = True
    verify: bool = True
    diagnose: bool = True
    load: bool = True
    health_check: bool = True
    infer: bool = True
    cancel: bool = True
    unload: bool = True
    repair_metadata: bool = True
    reopen_after_restart: bool = True
    training: bool = False
    inference: bool = True
    video: bool = False
    batching: bool = False
    point_prompt: bool = False
    negative_point_prompt: bool = False
    box_prompt: bool = False
    mixed_point_box_prompt: bool = False
    text_prompt: bool = False
    brush_refinement: bool = False
    mask_output: bool = False
    box_output: bool = False
    depth_output: bool = False
    embedding_output: bool = False

    def as_dict(self) -> dict[str, bool]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProviderFileRecord:
    relative_path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ProviderModelDefinition:
    provider_id: str
    provider_version: str
    model_id: str
    architecture: str
    task: str
    capabilities: ProviderCapabilities
    checkpoint_path: Path
    checkpoint_kind: CheckpointKind
    checkpoint_sha256: str | None
    checkpoint_size_bytes: int | None
    checkpoint_format: str
    source: str
    revision: str | None = None
    license_metadata: dict[str, Any] = field(default_factory=dict)
    required_packages: tuple[str, ...] = ()
    optional_packages: tuple[str, ...] = ()
    supported_devices: tuple[DeviceMode, ...] = (DeviceMode.CPU, DeviceMode.CUDA)
    preferred_device: DeviceMode = DeviceMode.AUTO
    estimated_vram_bytes: int | None = None
    input_types: tuple[str, ...] = ("image",)
    output_types: tuple[str, ...] = ()
    prompt_types: tuple[str, ...] = ()
    file_manifest: tuple[ProviderFileRecord, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderVerification:
    status: str
    verified: bool
    checkpoint_exists: bool
    expected_sha256: str | None
    observed_sha256: str | None
    size_bytes: int | None
    expected_size_bytes: int | None = None
    files: tuple[ProviderFileRecord, ...] = ()
    duplicate_model_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderDiagnosis:
    ready: bool
    resolved_device: str | None
    runtime_versions: dict[str, str]
    missing_packages: tuple[str, ...] = ()
    incompatible_packages: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderHealthCheck:
    healthy: bool
    kind: str
    state: ProviderState
    checked_at: str
    resolved_device: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    failure_reason: str | None = None


@dataclass(slots=True)
class LifecycleInferenceRequest:
    request_id: str
    source_path: Path
    device: DeviceMode | str = DeviceMode.AUTO
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LifecycleInferenceResult:
    request_id: str
    provider_id: str
    model_id: str
    task: str
    resolved_device: str
    outputs: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class CancellationToken:
    """Thread-safe cooperative cancellation shared by every lifecycle adapter."""

    def __init__(self) -> None:
        self._event = Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise ProviderCancelledError("Provider request was cancelled")


class ProviderLifecycleError(RuntimeError):
    """Base structured runtime failure for provider lifecycle operations."""

    code = "provider_failure"


class ProviderUnavailableError(ProviderLifecycleError):
    code = "provider_unavailable"


class ProviderOutOfMemoryError(ProviderLifecycleError):
    code = "provider_out_of_memory"


class ProviderCancelledError(ProviderLifecycleError):
    code = "provider_cancelled"


@runtime_checkable
class LifecycleProvider(Protocol):
    provider_id: str

    def load(self, model: ProviderModelDefinition, device: str) -> None: ...

    def health_check(self) -> dict[str, Any]: ...

    def infer(
        self,
        model: ProviderModelDefinition,
        request: LifecycleInferenceRequest,
        cancellation: CancellationToken,
    ) -> LifecycleInferenceResult: ...

    def cancel(self, request_id: str) -> None: ...

    def unload(self) -> None: ...


@dataclass(slots=True)
class ProviderRequest:
    task: str
    project_id: str
    dataset_path: Path | None = None
    source_path: Path | None = None
    checkpoint_path: Path | None = None
    output_dir: Path | None = None
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProviderResult:
    artifacts: dict[str, str]
    metrics: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class ProviderAdapter(Protocol):
    provider_id: str
    supported_tasks: frozenset[str]

    def preflight(self, request: ProviderRequest) -> list[str]:
        """Return blockers. An empty list means execution may proceed."""
        ...

    def train(self, request: ProviderRequest) -> ProviderResult: ...

    def infer(self, request: ProviderRequest) -> ProviderResult: ...
