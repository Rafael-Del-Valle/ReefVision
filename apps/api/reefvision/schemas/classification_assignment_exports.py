"""Joined scientific exports for reviewed classification assignments."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ScientificClassificationExportRow(BaseModel):
    assignment_id: str
    assignment_revision: int
    assignment_status: str
    target_kind: str
    target_key: str
    image_id: str
    image_filename: str
    image_group_key: str | None = None
    capture_timestamp: datetime | None = None
    image_metadata: dict[str, Any] = Field(default_factory=dict)
    annotation_id: str | None = None
    mask_annotation_id: str | None = None
    fragment_key: str | None = None
    bounding_box: list[float] | None = None
    label_set_id: str
    label_set_key: str
    label_set_name: str
    cardinality: str
    label_class_id: str
    label_class_name: str
    source_type: str
    source_model_id: str | None = None
    source_model_name: str | None = None
    source_prediction_id: str | None = None
    confidence: float | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)
    reviewed_at: datetime | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    measurement_join_status: str
    measurement_mask_id: str | None = None
    measurement_candidate_mask_ids: list[str] = Field(default_factory=list)
    measurements: dict[str, Any] = Field(default_factory=dict)


class ScientificClassificationExportResponse(BaseModel):
    project_id: str
    row_count: int = Field(ge=0)
    matched_measurement_count: int = Field(ge=0)
    unmatched_measurement_count: int = Field(ge=0)
    ambiguous_measurement_count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
    rows: list[ScientificClassificationExportRow]
