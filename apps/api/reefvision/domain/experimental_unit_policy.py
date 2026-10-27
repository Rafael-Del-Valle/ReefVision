"""Reject technical observation units as ecological independent replicates.

This is a conservative input safeguard, not study-design authentication.
"""

from __future__ import annotations

import re

_TECHNICAL_REPLICATES = frozenset(
    {
        "image",
        "images",
        "photo",
        "photos",
        "photograph",
        "photographs",
        "frame",
        "frames",
        "video",
        "videos",
        "tile",
        "tiles",
        "crop",
        "crops",
        "patch",
        "patches",
        "pixel",
        "pixels",
        "mask",
        "masks",
        "annotation",
        "annotations",
        "detection",
        "detections",
        "camera",
        "cameras",
        "sensor",
        "sensors",
        "roi",
        "rois",
        "box",
        "boxes",
        "bbox",
        "bboxes",
        "bounding",
        "segmentation",
        "segmentations",
        "prediction",
        "predictions",
        "inference",
        "inferences",
        "keyframe",
        "keyframes",
        "view",
        "views",
        "augmentation",
        "augmentations",
        "thumbnail",
        "thumbnails",
        "subimage",
        "subimages",
        "keypoint",
        "keypoints",
        "tracklet",
        "tracklets",
        "heatmap",
        "heatmaps",
        "polygon",
        "polygons",
        "screenshot",
        "screenshots",
        "subframe",
        "subframes",
    }
)


def require_ecological_unit_type(value: str | None) -> str | None:
    """Validate declared units without asserting their biological independence.

    Reject common image-processing/technical replicate types, including compound
    labels such as ``video_frame``, ``per-image``, ``bounding_box``, and
    ``model_prediction``. These are measurements or processing outputs, not
    independent biological units. Other declarations remain
    caller-supplied and require study-design review before scientific inference.
    """
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Experimental unit type cannot be blank")
    tokens = set(re.findall(r"[a-z0-9]+", cleaned.casefold()))
    if tokens & _TECHNICAL_REPLICATES:
        raise ValueError(
            "Image, frame, camera and annotation records are technical replicates, "
            "not independent ecological experimental units"
        )
    return cleaned
