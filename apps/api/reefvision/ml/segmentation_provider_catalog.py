"""Task-aware provider metadata overlays for instance segmentation."""

from __future__ import annotations

from dataclasses import replace

from reefvision.ml.provider_hub import (
    ModelProviderDescriptor,
    ProviderCapabilityMatrix,
)


def segmentation_capability_matrix(
    provider_id: str,
    capabilities: ProviderCapabilityMatrix,
) -> ProviderCapabilityMatrix:
    if provider_id != "ultralytics":
        return capabilities
    return replace(
        capabilities,
        image_detection=True,
        image_instance_segmentation=True,
        training=True,
        validation=True,
        export=True,
        cpu_inference=True,
        cuda_inference=True,
        fp16=True,
        packaged_desktop_operation=True,
    )


def segmentation_provider_descriptor(
    descriptor: ModelProviderDescriptor,
) -> ModelProviderDescriptor:
    if descriptor.provider_id != "ultralytics":
        return descriptor
    outputs = tuple(
        dict.fromkeys(
            [
                *descriptor.supported_output_types,
                "polygon_mask_proposals",
                "yolo_segmentation_datasets",
            ]
        )
    )
    return replace(
        descriptor,
        supported_tasks=tuple(
            dict.fromkeys(
                [*descriptor.supported_tasks, "detect", "segment"]
            )
        ),
        supported_output_types=outputs,
        known_limitations=(
            "Instance-segmentation training currently consumes polygon masks "
            "only; raster masks remain reserved for semantic providers.",
            "Tuning execution and tiled segmentation training remain disabled "
            "in this vertical slice.",
            "Automatic checkpoint downloads remain disabled; local or managed "
            "checkpoints must be selected explicitly.",
        ),
        capabilities=segmentation_capability_matrix(
            descriptor.provider_id,
            descriptor.capabilities,
        ),
    )
