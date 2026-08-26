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
        "Existing ReefVision baseline.",
    ),
    TaskCapability(
        "instance_segment",
        "Instance segmentation",
        ("image", "video"),
        ("polygon", "mask"),
        ("ultralytics", "sam", "custom_pytorch"),
        True,
        True,
        "foundation",
        "Requires mask/polygon persistence and export.",
    ),
    TaskCapability(
        "semantic_segment",
        "Semantic segmentation",
        ("image",),
        ("semantic_mask",),
        ("nnunetv2", "custom_pytorch"),
        True,
        True,
        "ready",
        (
            "Dense-mask dataset versions, nnU-Net v2 training, packaged model "
            "registration, inference, and human-reviewed raster proposals are implemented."
        ),
    ),
    TaskCapability(
        "classify",
        "Image classification",
        ("image",),
        ("image_label",),
        ("ultralytics", "custom_pytorch"),
        True,
        True,
        "ready",
        (
            "Image-level labels, immutable classification datasets, training, "
            "inference, and researcher-reviewed predictions are implemented."
        ),
    ),
    TaskCapability(
        "track",
        "Multi-object tracking",
        ("video",),
        ("bbox_track", "mask_track"),
        ("ultralytics", "bytetrack", "botsort"),
        False,
        True,
        "ready",
        (
            "Detector-plus-tracker execution, editable tracks, interpolation, "
            "analytics, benchmarking, and provenance are implemented."
        ),
    ),
    TaskCapability(
        "video_annotate",
        "Video annotation",
        ("video",),
        ("bbox_track", "mask_track", "keyframe"),
        ("reefvision",),
        False,
        True,
        "ready",
        (
            "Managed videos, manual keyframes, linear interpolation, verified "
            "track persistence, and science analytics are implemented."
        ),
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
        "Relative depth is not metric without calibration.",
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
        "Uses skeleton centerlines and calibrated pixel scale.",
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
        "Supports projected 2D area and depth-aware approximation.",
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
        "Count divided by calibrated area.",
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
        "Ranks unreviewed samples; does not auto-accept labels.",
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
        "Runs nnUNetv2 as an isolated external provider.",
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
        "Disabled until trusted-code execution is explicitly enabled.",
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
        "Object storage foundation only; authentication and conflict resolution remain.",
    ),
)


def capability_payload() -> list[dict[str, object]]:
    return [asdict(item) for item in TASKS]


def get_task(task_id: str) -> TaskCapability:
    for task in TASKS:
        if task.task_id == task_id:
            return task
    raise KeyError(task_id)
