"""Ensure Fusion segmentation uses the final runtime-patched assist provider factory."""

from __future__ import annotations

from typing import Any

from reefvision.jobs import workflow_segmentation_runtime
from reefvision.ml.sam2_sidecar import SAM2SidecarAssistProvider


def _dynamic_assist_provider(provider_name: str) -> Any:
    normalized = provider_name.strip().casefold().replace("-", "_")
    if normalized == "sam2_sidecar":
        return SAM2SidecarAssistProvider()
    if normalized in {"segment_anything", "sam", "original_sam"}:
        # catalog_expansion owns the checkpoint-aware Smart Mask adapter for original SAM,
        # Ultralytics SAM/SAM2, MobileSAM.pt, and FastSAM. apply_fastsam_runtime_patch()
        # augments this same class before workflow execution.
        from reefvision.ml.catalog_expansion import UnifiedSegmentAnythingAssistProvider

        return UnifiedSegmentAnythingAssistProvider()

    # Import the module at execution time. apply_sam_runtime_patch() replaces this factory
    # during create_app(), adding separately packaged MobileSAM, SAM2, and EfficientViT-SAM.
    from reefvision.ml import provider_hub

    return provider_hub.assist_provider_for_name(provider_name)


def install_segmentation_provider_runtime() -> None:
    if workflow_segmentation_runtime._assist_provider is not _dynamic_assist_provider:
        workflow_segmentation_runtime._assist_provider = _dynamic_assist_provider


install_segmentation_provider_runtime()
