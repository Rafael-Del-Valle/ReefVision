"""Reject technical observation units as ecological independent replicates.

This is a conservative input safeguard, not study-design authentication.
"""

from __future__ import annotations

import re
import unicodedata

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
        # Repeated temporal observations and derived measurements are not
        # independent biological experimental units, even across visits.
        "observation",
        "observations",
        "measurement",
        "measurements",
        "timepoint",
        "timepoints",
        "timestamp",
        "timestamps",
        "visit",
        "visits",
        "date",
        "dates",
        "session",
        "sessions",
    }
)


# Exporters and UI clients also use compact or camel-case technical labels.
# Do not mistake these derived observations for biological experimental units.
_COMPACT_TECHNICAL_REPLICATES = frozenset(
    {
        "videoframe",
        "posekeypoint",
        "trackingtracklet",
        "segmentationmask",
        "segmentationpolygon",
        "modelprediction",
        "boundingbox",
        "imagepatch",
        "imagecrop",
        "cameraview",
        "detectionbox",
        "samplingdate",
        "samplingtime",
        "observationevent",
    }
)


def require_ecological_unit_type(value: str | None) -> str | None:
    """Validate declared units without asserting their biological independence.

    Reject common image-processing, temporal and technical replicate types, including compound
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
    if any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in cleaned):
        raise ValueError("Experimental unit type cannot contain control or invisible characters")
    # Classify Unicode compatibility forms (e.g. fullwidth 'image') without
    # rewriting the source declaration retained in scientific provenance.
    normalized = unicodedata.normalize("NFKC", cleaned)
    # Split lower-to-upper boundaries before case folding (e.g. VideoFrame).
    # Explicit compact tokens also reject all-lowercase exports (videoframe).
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", normalized)
    tokens = set(re.findall(r"[a-z0-9]+", words.casefold()))
    if tokens & (_TECHNICAL_REPLICATES | _COMPACT_TECHNICAL_REPLICATES):
        raise ValueError(
            "Image, frame, camera and annotation records are technical replicates, "
            "not independent ecological experimental units"
        )
    return cleaned


def require_ecological_unit_id(value: str | None) -> str | None:
    """Preserve physical-unit identity without silently changing its label.

    A padded ID such as "tank-1 " must not count as an independent unit
    alongside "tank-1". Reject ambiguity rather than stripping provenance.
    This validates syntax, not the existence or independence of a unit.
    """
    if value is None:
        return None
    if not value.strip():
        raise ValueError("Experimental unit ID cannot be blank")
    if value != value.strip():
        raise ValueError("Experimental unit ID cannot have surrounding whitespace")
    if any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in value):
        raise ValueError("Experimental unit ID cannot contain control or invisible characters")
    # Compatibility and canonical Unicode aliases can otherwise split one physical
    # unit into multiple apparent replicates (e.g. fullwidth IDs or decomposed é).
    # Reject rather than silently rewriting the original evidence identifier.
    if unicodedata.normalize("NFKC", value) != value:
        raise ValueError("Experimental unit ID must use Unicode NFKC form")
    return value
