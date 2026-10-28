"""Public contracts for safe computed scientific metrics."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from reefvision.domain.scientific_units import UNITS

MetricDimension = Literal[
    "dimensionless",
    "length",
    "area",
    "time",
    "speed",
    "temperature",
    "practical_salinity",
    "mass_salinity",
    "count",
    "count_density",
    "count_rate",
    "angle",
    "pixel_length",
    "pixel_area",
]


class ComputedMetricModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class ComputedMetricInputSpec(ComputedMetricModel):
    symbol: str = Field(min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_]*$")
    dimension: MetricDimension


class ComputedMetricDefinitionCreate(ComputedMetricModel):
    name: str = Field(min_length=1, max_length=200)
    expression: str = Field(min_length=1, max_length=1000)
    inputs: list[ComputedMetricInputSpec] = Field(min_length=1, max_length=50)
    output_unit: str

    @field_validator("output_unit")
    @classmethod
    def supported_output_unit(cls, value: str) -> str:
        if value not in UNITS:
            raise ValueError("Output unit must be explicitly supported")
        return value

    @model_validator(mode="after")
    def unique_symbols(self) -> ComputedMetricDefinitionCreate:
        symbols = [item.symbol for item in self.inputs]
        if len(symbols) != len(set(symbols)):
            raise ValueError("Metric input symbols must be unique")
        return self


class ComputedMetricDefinitionResponse(ComputedMetricDefinitionCreate):
    id: UUID
    project_id: UUID
    formula_version: str
    definition_sha256: str
    created_at: datetime


class ComputedMetricDefinitionPage(ComputedMetricModel):
    items: list[ComputedMetricDefinitionResponse]
    total: int


class ComputedMetricCalculateRequest(ComputedMetricModel):
    inputs: dict[str, UUID] = Field(min_length=1, max_length=50)


class ComputedMetricResultResponse(ComputedMetricModel):
    schema_version: Literal["1.1.0"] = "1.1.0"
    id: UUID
    project_id: UUID
    definition_id: UUID
    definition_name: str
    expression: str
    formula_version: str
    definition_sha256: str
    value: float
    unit: str
    normalized_value: float
    normalized_unit: str
    uncertainty: float | None
    normalized_uncertainty: float | None
    dimension: dict[str, int]
    observed_at: datetime
    subject: dict[str, JsonValue]
    input_record_ids: dict[str, UUID]
    input_snapshot: dict[str, dict[str, JsonValue]]
    provenance: dict[str, JsonValue]
    content_sha256: str
    workflow_run_id: UUID | None = None
    workflow_node_run_id: UUID | None = None
    created_at: datetime


class ComputedMetricResultPage(ComputedMetricModel):
    items: list[ComputedMetricResultResponse]
    total: int
