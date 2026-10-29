"""Typed and provenance-aware scientific heatmap responses."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

HeatmapKind = Literal[
    "reviewed_boxes",
    "verified_masks",
    "pending_predictions",
]


class HeatmapLayer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: HeatmapKind
    counting_method: Literal["bounding_rectangle_centroid"]
    object_count: int = Field(ge=0)
    max_cell_count: int = Field(ge=0)
    counts: list[list[int]]
    normalized: list[list[float]]


class ScientificHeatmapResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1.0"] = "1.1.0"
    algorithm: Literal["reefvision-centroid-grid-1"]
    project_id: UUID
    image_id: UUID
    image_sha256: str
    annotation_revision: int = Field(ge=0)
    annotation_status: str
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    columns: int = Field(ge=2, le=64)
    rows: int = Field(ge=2, le=64)
    label_class_id: UUID | None
    layers: list[HeatmapLayer]
    source_sha256: str
    content_sha256: str
    methodological_notes: list[str]
