"""In-tree pose records used by the native text interchange codecs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from reefvision.domain.errors import ValidationError


@dataclass(frozen=True)
class Skeleton:
    nodes: list[str]
    name: str = ""
    edges: list[list[int]] = field(default_factory=list)

    @property
    def node_names(self) -> list[str]:
        return self.nodes

    @property
    def edge_inds(self) -> list[list[int]]:
        return self.edges


@dataclass(frozen=True)
class Track:
    name: str


@dataclass(frozen=True)
class Category:
    name: str


@dataclass(frozen=True)
class Video:
    filename: str
    shape: tuple[int, int, int, int]

    def __getitem__(self, frame_index: int) -> NDArray[np.uint8]:
        import cv2

        capture = cv2.VideoCapture(self.filename)
        try:
            if not capture.isOpened() or not capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index):
                raise ValidationError(f"Could not open source video frame {frame_index}")
            ok, pixels = capture.read()
            if not ok or pixels is None:
                raise ValidationError(f"Could not decode source video frame {frame_index}")
            return np.asarray(cv2.cvtColor(pixels, cv2.COLOR_BGR2RGB), dtype=np.uint8)
        finally:
            capture.release()


@dataclass(frozen=True)
class Instance:
    points: NDArray[Any]
    skeleton: Skeleton
    track: Track | None
    category: Category
    score: float

    @classmethod
    def from_arrays(
        cls,
        xy: NDArray[Any],
        *,
        skeleton: Skeleton,
        visible: NDArray[Any],
        scores: NDArray[Any] | None,
        score: float,
        track: Track | None,
        category: Category,
    ) -> Instance:
        fields: list[tuple[str, str] | tuple[str, str, tuple[int, ...]]] = [
            ("xy", "f8", (2,)),
            ("visible", "?"),
        ]
        if scores is not None:
            fields.append(("score", "f8"))
        points = np.zeros(len(skeleton.node_names), dtype=np.dtype(fields))
        points["xy"], points["visible"] = xy, visible
        if scores is not None:
            points["score"] = scores
        return cls(points, skeleton, track, category, score)


@dataclass(frozen=True)
class LabeledFrame:
    video: Video
    frame_idx: int
    instances: list[Instance]


@dataclass(frozen=True)
class Labels:
    labeled_frames: list[LabeledFrame]
    videos: list[Video]
    skeletons: list[Skeleton]
    provenance: dict[str, Any]
