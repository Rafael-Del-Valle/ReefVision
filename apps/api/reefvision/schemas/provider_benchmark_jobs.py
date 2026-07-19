"""Queued provider benchmark execution schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from reefvision.schemas.jobs import JobResponse


class ProviderBenchmarkRunRequest(BaseModel):
    provider_id: str = Field(min_length=1, max_length=100)
    project_id: str | None = Field(default=None, max_length=36)
    model_id: str | None = Field(default=None, max_length=200)
    image_ids: list[str] = Field(default_factory=list, max_length=10_000)
    task: str = Field(min_length=1, max_length=100)
    device_id: str = Field(default="auto", min_length=1, max_length=200)
    input_width: int = Field(default=640, ge=16, le=16_384)
    input_height: int = Field(default=640, ge=16, le=16_384)
    batch_size: int = Field(default=1, ge=1, le=1024)
    sample_count: int = Field(default=10, ge=1, le=10_000)
    warmup_count: int = Field(default=2, ge=0, le=1000)
    local_files_only: bool = True
    maximum_metric_depth: float | None = Field(default=None, gt=0)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_inputs(self) -> ProviderBenchmarkRunRequest:
        if self.provider_id != "mock" and not self.image_ids:
            raise ValueError("Non-mock provider benchmarks require at least one image_id")
        if (
            self.provider_id
            in {
                "ultralytics",
                "segment_anything",
                "efficientvit_sam",
                "mobile_sam",
                "sam2",
            }
            and not self.model_id
        ):
            raise ValueError("The selected provider benchmark requires model_id")
        return self


class ProviderBenchmarkRunResponse(BaseModel):
    job: JobResponse
