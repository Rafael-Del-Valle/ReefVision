"""Typed, source-linked projected geometry candidates; never verified growth data."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class EcologyMeasurementCandidate(BaseModel):
    organism_key: str
    identity_revision: int = Field(ge=1)
    parent_colony_key: str | None
    experimental_unit_type: str | None
    experimental_unit_id: str | None
    image_id: str
    image_sha256: str
    annotation_evidence_id: str
    calibration_evidence_id: str
    annotation_kind: Literal["box", "mask"]
    annotation_id: str
    annotation_revision: int = Field(ge=1)
    annotation_sha256: str
    calibration_sha256: str
    metric: Literal["box_width", "box_height", "mask_projected_area"]
    value: float = Field(gt=0, allow_inf_nan=False)
    unit: str
    capture_timestamp_utc: datetime | None
    capture_time_status: Literal["timezone_aware", "missing", "timezone_missing"]
    evidence_level: Literal["linked_unverified"] = "linked_unverified"
    review_gate: Literal["scientist_review_required"] = "scientist_review_required"


class EcologyMeasurementExclusion(BaseModel):
    calibration_evidence_id: str
    reason: Literal["perspective_transform_requires_review", "unsupported_geometry"]


class EcologyMeasurementCandidatesResponse(BaseModel):
    schema_version: Literal["ecology-measurement-candidates-0001"] = (
        "ecology-measurement-candidates-0001"
    )
    project_id: str
    source_registry_history_sha256: str | None
    source_calibration_evidence_sha256: str | None
    candidates: list[EcologyMeasurementCandidate] = Field(default_factory=list)
    candidate_count: int = 0
    exclusions: list[EcologyMeasurementExclusion] = Field(default_factory=list)
    input_sha256: str
    evidence_level: Literal["linked_unverified"] = "linked_unverified"
    review_gate: Literal["scientist_review_required"] = "scientist_review_required"
