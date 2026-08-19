"""Ensure Fusion segmentation uses the final runtime-patched assist provider factory."""

from __future__ import annotations

from typing import Any

from reefvision.jobs import workflow_segmentation_runtime
from reefvision.ml.sam2_sidecar import SAM2SidecarAssistProvider


def _dynamic_assist_provider(provider_name: str) -> Any:
    normalized = provider_name.strip().casefold().replace("-", "_")
    if normalized == "sam2_sidecar":
        return SAM2SidecarAssistProvider()
    # Import the module at execution time. apply_sam_runtime_patch() replaces this factory
    # during create_app(), adding MobileSAM, SAM2, EfficientViT-SAM, and other optional packs.
    from reefvision.ml import provider_hub

    return provider_hub.assist_provider_for_name(provider_name)


workflow_segmentation_runtime._assist_provider = _dynamic_assist_provider
