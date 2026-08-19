"""Single source of truth for ReefVision tasks and their implementation state."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

TaskState = Literal["ready", "foundation", "blocked", "planned"]


@dataclass(frozen=True, slots=True)
class TaskCapability:
    task_id: str
    display_name: str
    media: tuple[str, ...]
    annotation_kinds: tuple[str, ...]
    providers: tuple[str, ...]
    supports_training: bool
    supports_inference: bool
    state: TaskState
    notes: str


TASKS: tuple[TaskCapability, ...] = (
    TaskCapability(
        "detect",
        "Object detection",
        ("image", "video"),
        ("bbox",),
        ("ultralytics", "custom_pytorch"),
        True,
        True,
        "ready",
        "Existing ReefVision detection baseline with training, inference, review, and evaluation.",
    ),
    TaskCapability(
        "instance_segment",
        "Instance segmentation",
        ("image", "video"),
        ("polygon", "mask"),
        ("ultralytics", "sam", "sam2", "sam3", "fastsam", "custom_pytorch"),
        True,
        True,
        "foundation",
        "Editable masks, assisted segmentation, training, inference, and evaluation exist; full 1.0 requires all provider and end-to-end gates to pass.",
    ),
    TaskCapability(
        "semantic_segment",
        "Semantic segmentation",
        ("image",),
        ("semantic_mask",),
        ("nnunetv2", "reefvision_unet", "custom_pytorch"),
        True,
        True,
        "foundation",
        "Dense-mask dataset, native U-Net, and nnU-Net foundations exist and remain mandatory for 1.0 validation.",
    ),
    TaskCapability(
        "classify",
        "Image and region classification",
        ("image",),
        ("image_label", "region_label"),
        ("ultralytics", "transformers", "custom_pytorch"),
        True,
        True,
        "foundation",
        "Classification datasets, assignments, training, inference, evaluation, and review are part of the 1.0 release scope.",
    ),
    TaskCapability(
        "track",
        "Multi-object tracking",
        ("video",),
        ("bbox_track", "mask_track"),
        ("ultralytics", "bytetrack", "botsort", "sam2"),
        False,
        True,
        "foundation",
        "Managed video tracking, persisted identities, manual corrections, and tracking evaluation are required for 1.0.",
    ),
    TaskCapability(
        "video_annotate",
        "Video annotation",
        ("video",),
        ("bbox_track", "mask_track", "keyframe"),
        ("reefvision", "sam2"),
        False,
        True,
        "foundation",
        "Frame timeline, interpolation, persistent tracks, assisted propagation, and review remain required for 1.0.",
    ),
    TaskCapability(
        "behavior_analysis",
        "Fish behavior analysis",
        ("video",),
        ("bbox_track", "mask_track", "zone", "trajectory"),
        ("reefvision_measurements",),
        False,
        True,
        "foundation",
        "Trajectory, speed, acceleration, turning, occupancy, zone, heatmap, wall-distance, and schooling metrics are required for 1.0.",
    ),
    TaskCapability(
        "depth",
        "Monocular depth estimation",
        ("image", "video"),
        ("depth_map",),
        ("depth_anything_v2",),
        False,
        True,
        "foundation",
        "Relative and imported metric depth maps are supported; absolute physical interpretation still requires calibration.",
    ),
    TaskCapability(
        "rgbd",
        "RGB-D fusion and depth-aware analysis",
        ("image", "video"),
        ("depth_map", "mask", "bbox_track"),
        ("reefvision_rgbd", "custom_pytorch"),
        True,
        True,
        "foundation",
        "Depth-aware association, four-channel model foundations, and depth-aware measurement must be wired end-to-end for 1.0.",
    ),
    TaskCapability(
        "tle",
        "Total linear extent",
        ("image",),
        ("mask", "centerline"),
        ("reefvision_measurements",),
        False,
        True,
        "foundation",
        "Uses skeleton centerlines, gap bridging, spur pruning, and calibrated pixel scale.",
    ),
    TaskCapability(
        "surface_area",
        "Coral surface area",
        ("image",),
        ("mask", "depth_map"),
        ("reefvision_measurements",),
        False,
        True,
        "foundation",
        "Supports projected 2D area plus depth-aware and geometry-based approximations with explicit calibration assumptions.",
    ),
    TaskCapability(
        "polyp_density",
        "Polyp density",
        ("image",),
        ("points", "bbox", "mask"),
        ("reefvision_measurements",),
        False,
        True,
        "foundation",
        "Count divided by calibrated area with provenance for the selected count and area sources.",
    ),
    TaskCapability(
        "prompt_assist",
        "Prompt Assist",
        ("image", "video"),
        ("point_prompt", "box_prompt", "brush_prompt", "mask"),
        ("sam", "sam2", "sam3", "fastsam", "reefvision"),
        False,
        True,
        "foundation",
        "Positive/negative points, boxes, brush refinement, provider selection, and review-before-accept behavior are required for 1.0.",
    ),
    TaskCapability(
        "active_learning",
        "Automated active learning",
        ("image", "video"),
        ("review_score",),
        ("reefvision",),
        False,
        True,
        "foundation",
        "Supports uncertainty, margin, entropy, embedding diversity, clustering, density, Pareto ranking, and ensemble disagreement; cycle orchestration and UI closure remain release gates.",
    ),
    TaskCapability(
        "workflow_fusion",
        "Fusion workflow graph",
        ("image", "video", "dataset"),
        ("workflow_graph",),
        ("reefvision",),
        False,
        True,
        "foundation",
        "Persisted typed graphs, execution stages, artifact lineage, caching, retries, and scientific workflow templates are mandatory for 1.0.",
    ),
    TaskCapability(
        "interchange",
        "Project and dataset interoperability",
        ("image", "video", "dataset", "project"),
        ("manifest", "annotation", "mask", "track", "measurement"),
        ("reefvision", "coco", "yolo", "csv", "json", "npy"),
        False,
        True,
        "foundation",
        "Round-trip-safe scientific import/export with split, class, source-ID, checksum, and provenance preservation is required for 1.0.",
    ),
    TaskCapability(
        "nnunet_train",
        "nnU-Net training",
        ("image",),
        ("semantic_mask",),
        ("nnunetv2",),
        True,
        True,
        "foundation",
        "Runs nnUNetv2 as an isolated external provider and remains a required segmentation path for 1.0.",
    ),
    TaskCapability(
        "custom_pytorch",
        "Custom PyTorch architecture",
        ("image", "video"),
        ("provider_defined",),
        ("custom_pytorch",),
        True,
        True,
        "blocked",
        "Disabled until trusted-code execution is explicitly enabled; safe model loading remains the default.",
    ),
    TaskCapability(
        "cloud_sync",
        "Cloud collaboration and hosted datasets",
        ("dataset",),
        ("manifest",),
        ("s3_compatible",),
        False,
        False,
        "foundation",
        "Object-storage foundations exist; authentication and conflict resolution remain incomplete.",
    ),
)


def capability_payload() -> list[dict[str, object]]:
    return [asdict(item) for item in TASKS]


def get_task(task_id: str) -> TaskCapability:
    for task in TASKS:
        if task.task_id == task_id:
            return task
    raise KeyError(task_id)
