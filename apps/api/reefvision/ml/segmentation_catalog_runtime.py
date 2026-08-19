"""Keep provider-catalog segmentation capabilities aligned with the implemented runtime."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from reefvision.ml import provider_hub

_APPLIED = False


def apply_segmentation_catalog_runtime_patch() -> None:
    global _APPLIED
    if _APPLIED:
        return
    original = provider_hub._list_model_providers_uncached

    def list_with_unified_segmentation(
        settings: Any = None,
        *,
        refresh: bool = False,
    ) -> list[Any]:
        descriptors = original(settings, refresh=refresh)
        output: list[Any] = []
        for descriptor in descriptors:
            if descriptor.provider_id != "segment_anything":
                output.append(descriptor)
                continue
            output.append(
                replace(
                    descriptor,
                    display_name="Segment Anything / Smart Mask",
                    supported_model_families=(
                        "Original Segment Anything checkpoints",
                        "Ultralytics SAM checkpoints",
                        "Ultralytics SAM 2 checkpoints",
                        "MobileSAM checkpoints",
                        "FastSAM checkpoints",
                    ),
                    supported_tasks=("assist_segmentation",),
                    supported_input_types=(
                        "image",
                        "box_prompt",
                        "brush_prompt",
                        "point_prompt",
                    ),
                    supported_output_types=(
                        "pending_mask_proposal",
                        "managed_raster_mask",
                        "bounding_box",
                    ),
                    known_limitations=(
                        "Prompt-assisted masks remain proposals until explicit human review.",
                        "Automatic checkpoint downloads remain disabled; local checkpoints must "
                        "be selected explicitly.",
                        "SAM 2 video propagation uses the dedicated video/sidecar path rather "
                        "than the image Segmenter node.",
                    ),
                    capabilities=replace(
                        descriptor.capabilities,
                        image_instance_segmentation=True,
                        click_prompting=True,
                        box_prompting=True,
                        brush_prompting=True,
                        cpu_inference=True,
                        cuda_inference=True,
                        packaged_desktop_operation=True,
                    ),
                )
            )
        return output

    provider_hub._list_model_providers_uncached = list_with_unified_segmentation
    _APPLIED = True


apply_segmentation_catalog_runtime_patch()
