"""Provider contracts shared by training, inference, depth, and tracking engines."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


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
