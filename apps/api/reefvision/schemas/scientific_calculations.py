"""Typed, version-pinned requests for reproducible scientific calculations."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from reefvision.schemas.scientific_data import ScientificModel


class ScientificCalculationRequest(ScientificModel):
    formula_id: Literal["count_records", "rectangular_area", "density"]
    formula_version: Literal["1.0.0"]
    input_record_ids: list[UUID] = Field(min_length=1, max_length=10000)
