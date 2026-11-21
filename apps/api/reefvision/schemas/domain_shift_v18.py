"""Researcher-declared acquisition domains on one frozen paired evaluation."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from reefvision.schemas.image_adjustments_v18 import ImageAdjustmentPin, Sha256

GroupKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Mode = Literal["original", "adjusted"]


class DomainRoster(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    groups: list[GroupKey] = Field(min_length=1, max_length=500)


class DomainRecipeChoice(ImageAdjustmentPin):
    image_id: UUID


class DomainShiftDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    comparison_id: UUID
    comparison_sha256: Sha256
    reference: DomainRoster
    target: DomainRoster
    independent_unit: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
    ]
    preprocessing: Mode
    adjustments: list[DomainRecipeChoice] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def distinct_evidence(self) -> "DomainShiftDraft":
        keys = [value.casefold() for value in self.reference.groups + self.target.groups]
        if self.reference.label.casefold() == self.target.label.casefold() or len(keys) != len(
            set(keys)
        ):
            raise ValueError("The two domains need different names and disjoint acquisition groups")
        if bool(self.adjustments) != (self.preprocessing == "adjusted"):
            raise ValueError(
                "Adjusted analysis requires explicit recipe pins for the included stills"
            )
        if len(self.adjustments) != len({row.image_id for row in self.adjustments}):
            raise ValueError("Each source image must have at most one adjustment")
        return self
