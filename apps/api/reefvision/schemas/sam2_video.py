"""SAM 2 managed video-mask propagation schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from reefvision.schemas.jobs import JobResponse


class SAM2PromptPoint(BaseModel):
    x: float = Field(ge=0)
    y: float = Field(ge=0)


class SAM2PromptBox(BaseModel):
    x_min: float = Field(ge=0)
    y_min: float = Field(ge=0)
    x_max: float = Field(ge=0)
    y_max: float = Field(ge=0)

    @model_validator(mode="after")
    def positive_area(self) -> SAM2PromptBox:
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("Prompt boxes must have positive width and height")
        return self


class SAM2VideoPropagationRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=36)
    device: str = Field(default="auto", min_length=1, max_length=100)
    seed_frame_index: int = Field(default=0, ge=0)
    object_id: int = Field(default=1, ge=1)
    positive_points: list[SAM2PromptPoint] = Field(min_length=1, max_length=10_000)
    negative_points: list[SAM2PromptPoint] = Field(default_factory=list, max_length=10_000)
    prompt_box: SAM2PromptBox | None = None
    every_n_frames: int = Field(default=1, ge=1, le=10_000)
    maximum_frames: int | None = Field(default=None, ge=1, le=1_000_000)
    preview_every_n_frames: int = Field(default=30, ge=1, le=100_000)


class SAM2VideoPropagationResponse(BaseModel):
    job: JobResponse
