"""Typed contracts for immutable verified-mask area and coverage metrics."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

MaskCoverageGroupingLevel = Literal["image", "image_group_key"]
MaskCoverageRoiContract = Literal[
    "full_image", "verified_mask_class_union", "source_image_polygons"
]
MaskCoverageFormulaVersion = Literal["reefvision.mask-coverage.v1", "reefvision.mask-coverage.v2"]
MaskCoverageCalibrationMethod = Literal["scalar_distance_per_pixel", "projective_reference_plane"]


class MaskCoverageModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class MaskCoverageRoiPolygon(MaskCoverageModel):
    image_id: UUID
    points: list[tuple[float, float]] = Field(min_length=3, max_length=256)


class ComputedMaskCoverageDefinitionCreate(MaskCoverageModel):
    name: str = Field(min_length=1, max_length=200)
    grouping_level: MaskCoverageGroupingLevel
    label_class_ids: list[UUID] = Field(default_factory=list, max_length=500)
    roi_label_class_id: UUID | None = None
    roi_polygons: list[MaskCoverageRoiPolygon] = Field(default_factory=list, max_length=500)
    use_reference_plane: bool = False

    @field_validator("label_class_ids")
    @classmethod
    def unique_labels(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Label class IDs must be unique")
        return value

    @model_validator(mode="after")
    def roi_is_not_a_target(self) -> ComputedMaskCoverageDefinitionCreate:
        if self.roi_label_class_id is not None and self.roi_label_class_id in self.label_class_ids:
            raise ValueError("ROI label class cannot also be a target label class")
        if self.roi_label_class_id is not None and self.roi_polygons:
            raise ValueError("Choose a verified ROI class or saved polygons")
        image_ids = {polygon.image_id for polygon in self.roi_polygons}
        if len(image_ids) != len(self.roi_polygons):
            raise ValueError("Supply one ROI polygon per image")
        return self


class ComputedMaskCoverageDefinitionResponse(ComputedMaskCoverageDefinitionCreate):
    id: UUID
    project_id: UUID
    definition_kind: Literal["mask_coverage"] = "mask_coverage"
    expression: str
    operation: Literal["verified_mask_union_coverage"]
    output_unit: Literal["percent"]
    formula_version: MaskCoverageFormulaVersion
    schema_version: Literal["1.1.0"]
    required_review_state: Literal["reviewed"]
    independence_contract: Literal["one_unit_per_image", "one_unit_per_image_group_key"]
    roi_contract: MaskCoverageRoiContract
    definition_sha256: str
    created_at: datetime


class ComputedMaskCoverageDefinitionPage(MaskCoverageModel):
    items: list[ComputedMaskCoverageDefinitionResponse]
    total: int


class ComputedMaskCoverageSelection(MaskCoverageModel):
    image_ids: list[UUID] = Field(min_length=1, max_length=500)

    @field_validator("image_ids")
    @classmethod
    def unique_images(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Image IDs must be unique")
        return value


class MaskCoverageClassArea(MaskCoverageModel):
    label_class_id: UUID | None
    label_name: str
    mask_count: int = Field(ge=0)
    summed_mask_area_pixels: int = Field(ge=0)
    union_area_pixels: int = Field(ge=0)
    physical_unit: str | None = None
    union_area_physical: float | None = Field(default=None, ge=0)


class MaskCoverageSummary(MaskCoverageModel):
    mask_count: int = Field(ge=0)
    density_object_count: int = Field(ge=0)
    summed_mask_area_pixels: int = Field(ge=0)
    union_area_pixels: int = Field(ge=0)
    overlap_area_pixels: int = Field(ge=0)
    image_denominator_pixels: int = Field(ge=1)
    image_coverage_percent: float = Field(ge=0, le=100)
    roi_denominator_pixels: int | None = Field(default=None, ge=1)
    target_union_in_roi_pixels: int | None = Field(default=None, ge=0)
    roi_coverage_percent: float | None = Field(default=None, ge=0, le=100)
    area_by_class: list[MaskCoverageClassArea]
    physical_unit: str | None = None
    union_area_physical: float | None = Field(default=None, ge=0)
    sampling_area_physical: float | None = Field(default=None, gt=0)
    object_density_per_square_unit: float | None = Field(default=None, ge=0)
    calibration_method: MaskCoverageCalibrationMethod | None = None
    target_union_in_roi_physical: float | None = Field(default=None, ge=0)
    roi_coverage_physical_percent: float | None = Field(default=None, ge=0, le=100)
    physical_unavailable_reason: str | None = None


class MaskCoverageImageSummary(MaskCoverageSummary):
    image_id: UUID
    unit_key: str
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)


class MaskCoverageGroupSummary(MaskCoverageSummary):
    unit_key: str
    image_ids: list[UUID]


class ComputedMaskCoveragePreview(MaskCoverageSummary):
    schema_version: Literal["1.1.0"] = "1.1.0"
    definition_id: UUID
    definition_sha256: str
    grouping_level: MaskCoverageGroupingLevel
    required_review_state: Literal["reviewed"] = "reviewed"
    roi_contract: MaskCoverageRoiContract
    image_count: int = Field(ge=1)
    independent_unit_count: int = Field(ge=1)
    algorithm: Literal["reefvision.source-pixel-mask-union.v1"]
    coordinate_frame: Literal["source_image_pixels"]
    images: list[MaskCoverageImageSummary]
    groups: list[MaskCoverageGroupSummary]
    image_snapshot: list[dict[str, JsonValue]]
    mask_snapshot: list[dict[str, JsonValue]]
    evidence_sha256: str


class ComputedMaskCoverageResultResponse(ComputedMaskCoveragePreview):
    id: UUID
    project_id: UUID
    result_kind: Literal["mask_coverage"] = "mask_coverage"
    definition_name: str
    expression: str
    formula_version: MaskCoverageFormulaVersion
    output_unit: Literal["percent"]
    observed_at: datetime
    provenance: dict[str, JsonValue]
    content_sha256: str
    workflow_run_id: UUID | None = None
    workflow_node_run_id: UUID | None = None
    created_at: datetime


class ComputedMaskCoverageResultPage(MaskCoverageModel):
    items: list[ComputedMaskCoverageResultResponse]
    total: int


class ComputedMaskCoverageValidationResponse(MaskCoverageModel):
    result_id: UUID
    current: bool
    saved_evidence_sha256: str
    current_evidence_sha256: str
    reasons: list[str]
