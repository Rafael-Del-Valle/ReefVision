"""Interactive annotation-assist API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, FiniteFloat, field_validator

from reefvision.schemas.annotations import AnnotationResponse, MaskAnnotationResponse


class AssistSessionCreateRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=36)
    device: str = Field(default="auto", min_length=1, max_length=20)
    source_prediction_id: str | None = Field(
        default=None, min_length=1, max_length=36
    )


class AssistPoint(BaseModel):
    x: FiniteFloat
    y: FiniteFloat


class BrushStrokeRequest(BaseModel):
    points: list[AssistPoint] = Field(min_length=1)


class AssistBrushRequest(BaseModel):
    mode: Literal["add", "subtract"]
    brush_radius: FiniteFloat = Field(gt=0, le=4096)
    strokes: list[BrushStrokeRequest] = Field(min_length=1)


class AssistBoxRequest(BaseModel):
    x_min: FiniteFloat
    y_min: FiniteFloat
    x_max: FiniteFloat
    y_max: FiniteFloat

    @field_validator("x_max")
    @classmethod
    def validate_box_area(cls, value: float, info: object) -> float:
        data = getattr(info, "data", {})
        x_min = data.get("x_min")
        y_min = data.get("y_min")
        y_max = data.get("y_max")
        if (
            x_min is not None
            and y_min is not None
            and y_max is not None
            and not _box_has_positive_area(
                float(x_min),
                float(y_min),
                float(value),
                float(y_max),
            )
        ):
            raise ValueError("Bounding boxes must have positive width and height")
        return value


class AssistAcceptRequest(BaseModel):
    label_class_id: str = Field(min_length=1, max_length=36)


class AssistCandidateBox(BaseModel):
    x_min: float
    y_min: float
    x_max: float
    y_max: float


class AssistSessionResponse(BaseModel):
    session_id: str
    project_id: str
    image_id: str
    model_id: str
    model_display_name: str
    provider_name: str
    provider_version: str
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    add_stroke_count: int
    subtract_stroke_count: int
    brush_radius: float | None
    source_prediction_id: str | None
    prompt_type: str | None
    candidate_box: AssistCandidateBox | None
    candidate_mask_png_base64: str | None


class AssistAcceptResponse(BaseModel):
    session_id: str
    annotation: AnnotationResponse
    mask_annotation: MaskAnnotationResponse | None = None


def _box_has_positive_area(
    x_min: float,
    y_min: float,
    x_max: float,
    y_max: float,
) -> bool:
    return x_max > x_min and y_max > y_min
