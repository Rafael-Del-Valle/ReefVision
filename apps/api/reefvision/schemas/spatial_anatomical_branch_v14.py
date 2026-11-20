"""Investigator-declared anatomical centerline and provisional reference evidence."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StringConstraints, model_validator

FiniteCoordinate = Annotated[StrictFloat, Field(allow_inf_nan=False)]
Length = Annotated[StrictFloat, Field(gt=0, allow_inf_nan=False)]
Tolerance = Annotated[StrictFloat, Field(ge=0, allow_inf_nan=False)]
EvidenceText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]
EvidenceId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]


class BranchReferenceProtocol(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_reference: EvidenceText
    independent_reference_id: EvidenceText
    independent_reference_observer_id: EvidenceId
    independent_reference_length_m: Length
    independent_reference_scale_evidence: EvidenceText
    repeatability_reference: EvidenceText
    repeated_lengths_m: list[Length] = Field(min_length=2, max_length=32)
    maximum_reference_error_m: Tolerance
    maximum_repeatability_range_m: Tolerance
    adjudicator_id: EvidenceId


class AnatomicalBranchDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ordered_points_source_units: list[
        tuple[FiniteCoordinate, FiniteCoordinate, FiniteCoordinate]
    ] = Field(min_length=2, max_length=128)
    base_landmark: EvidenceText
    tip_landmark: EvidenceText
    selection_method: EvidenceText
    operator_id: EvidenceId
    protocol: BranchReferenceProtocol | None = None

    @model_validator(mode="after")
    def validate_declaration(self) -> AnatomicalBranchDeclaration:
        points = self.ordered_points_source_units
        if len(set(points)) != len(points):
            raise ValueError("Centerline requires distinct ordered points from base to tip")
        if self.base_landmark.casefold() == self.tip_landmark.casefold():
            raise ValueError("Declare different base and tip landmarks")
        if self.protocol is not None and self.operator_id.casefold() in {
            self.protocol.independent_reference_observer_id.casefold(),
            self.protocol.adjudicator_id.casefold(),
        }:
            raise ValueError("Reference observer and adjudicator must differ from operator")
        return self
