"""Provider-neutral contracts for future raster-mask semantic segmentation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from reefvision.domain.errors import ValidationError

SEMANTIC_SEGMENTATION_TASK = "semantic_segment"
NNUNET_PROVIDER_ID = "nnunet"


@dataclass(frozen=True)
class SemanticClassDefinition:
    class_index: int
    pixel_value: int
    class_name: str


@dataclass(frozen=True)
class SemanticDatasetContract:
    """Immutable indexed-PNG dataset surface consumed by semantic trainers."""

    dataset_version_id: str
    dataset_manifest_sha256: str
    split_manifest_sha256: str
    export_root: Path
    images_root: Path
    masks_root: Path
    classes_file: Path
    classes: tuple[SemanticClassDefinition, ...]
    background_pixel_value: int = 0
    overlap_policy: str = ""

    def validate(self) -> None:
        if not self.dataset_version_id.strip():
            raise ValidationError(
                "Semantic datasets require a dataset version id"
            )
        for value, label in (
            (self.dataset_manifest_sha256, "dataset manifest"),
            (self.split_manifest_sha256, "split manifest"),
        ):
            is_sha256 = len(value) == 64 and all(
                character in "0123456789abcdef" for character in value
            )
            if not is_sha256:
                raise ValidationError(
                    "Semantic datasets require a lowercase SHA-256 "
                    f"{label}"
                )
        if self.background_pixel_value != 0:
            raise ValidationError(
                "ReefVision semantic-mask background must use pixel value 0"
            )
        if not self.export_root.is_dir():
            raise ValidationError("Semantic dataset export root is missing")
        if not self.images_root.is_dir() or not self.masks_root.is_dir():
            raise ValidationError(
                "Semantic datasets require images and masks directories"
            )
        if not self.classes_file.is_file():
            raise ValidationError(
                "Semantic dataset classes metadata is missing"
            )
        if not self.classes:
            raise ValidationError(
                "Semantic datasets require at least one foreground class"
            )
        class_indices = [item.class_index for item in self.classes]
        if len(class_indices) != len(set(class_indices)):
            raise ValidationError("Semantic class indices must be unique")
        pixel_values = [item.pixel_value for item in self.classes]
        if len(pixel_values) != len(set(pixel_values)):
            raise ValidationError(
                "Semantic class pixel values must be unique"
            )
        if any(value <= 0 or value > 255 for value in pixel_values):
            raise ValidationError(
                "Semantic class pixel values must be between 1 and 255"
            )


@dataclass(frozen=True)
class SemanticTrainingRequest:
    run_id: str
    project_id: str
    dataset: SemanticDatasetContract
    device: str = "auto"
    precision: str = "fp32"
    random_seed: int | None = None
    training_config: dict[str, Any] = field(default_factory=dict)
    resource_limits: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SemanticTrainingResult:
    checkpoint_path: Path
    metrics: dict[str, float]
    metrics_history: dict[str, list[float]]
    artifact_manifest: dict[str, Any]
    provider_version: str


class SemanticSegmentationProvider(Protocol):
    """Modular trainer/inference boundary for indexed semantic masks."""

    provider_id: str
    provider_version: str

    def preflight(
        self,
        request: SemanticTrainingRequest,
    ) -> tuple[list[str], list[str]]: ...

    def train(
        self,
        request: SemanticTrainingRequest,
    ) -> SemanticTrainingResult: ...

    def predict(
        self,
        checkpoint_path: Path,
        image_path: Path,
        *,
        device: str,
    ) -> Path: ...


class PlannedNnUNetProvider:
    """Capability-gated placeholder; execution is intentionally unavailable."""

    provider_id = NNUNET_PROVIDER_ID
    provider_version = "planned"

    def preflight(
        self,
        request: SemanticTrainingRequest,
    ) -> tuple[list[str], list[str]]:
        request.dataset.validate()
        return (
            [],
            [
                "nnU-Net orchestration is not installed in this ReefVision "
                "build. The indexed semantic PNG dataset contract is ready "
                "for a future provider pack."
            ],
        )

    def train(
        self,
        request: SemanticTrainingRequest,
    ) -> SemanticTrainingResult:
        request.dataset.validate()
        raise ValidationError(
            "nnU-Net semantic training is capability-gated and not "
            "implemented yet"
        )

    def predict(
        self,
        checkpoint_path: Path,
        image_path: Path,
        *,
        device: str,
    ) -> Path:
        del checkpoint_path, image_path, device
        raise ValidationError(
            "nnU-Net semantic inference is capability-gated and not "
            "implemented yet"
        )


def semantic_provider_for_name(
    provider_id: str,
) -> SemanticSegmentationProvider:
    normalized = provider_id.strip().casefold()
    if normalized == NNUNET_PROVIDER_ID:
        return PlannedNnUNetProvider()
    raise ValidationError(
        f"Unsupported semantic segmentation provider: {provider_id}"
    )
