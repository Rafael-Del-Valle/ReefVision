"""Printed scale-label OCR proposal schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from reefvision.schemas.image_calibration import CalibrationRoi


class ScaleLabelOcrRequest(BaseModel):
    roi: CalibrationRoi | None = None
    allow_model_download: bool = False


class ScaleLabelOcrCandidate(BaseModel):
    image_id: str
    raw_text: str
    parsed_value: float | None = Field(default=None, gt=0)
    parsed_unit: str | None = None
    normalized_unit: str | None = None
    roi: CalibrationRoi
    confidence: float = Field(ge=0, le=1)
    confidence_kind: str = "ocr_and_parse_heuristic"
    model_id: str
    model_revision: str
    warnings: list[str] = Field(default_factory=list)
    requires_researcher_confirmation: bool = True
