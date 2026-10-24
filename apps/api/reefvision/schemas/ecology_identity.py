"""Strict project-owned ecological identity contracts; no verification claims."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from reefvision.domain.experimental_unit_policy import require_ecological_unit_type

Key = str


class EcologyIdentityFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["colony", "fragment", "individual"]
    parent_colony_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    experimental_unit_type: str | None = Field(default=None, max_length=100)
    experimental_unit_id: str | None = Field(default=None, min_length=1, max_length=150)
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("experimental_unit_type")
    @classmethod
    def reject_technical_replicates(cls, value: str | None) -> str | None:
        return require_ecological_unit_type(value)

    @model_validator(mode="after")
    def require_complete_unit(self) -> EcologyIdentityFields:
        if (self.experimental_unit_type is None) != (self.experimental_unit_id is None):
            raise ValueError("Experimental unit type and ID must be declared together")
        if self.parent_colony_key is not None and self.kind != "fragment":
            raise ValueError("Only fragments can reference a parent colony")
        return self


class EcologyIdentityCreate(EcologyIdentityFields):
    organism_key: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )


class EcologyIdentityRevisionCreate(EcologyIdentityFields):
    expected_revision: int = Field(ge=1)


class EcologyIdentityRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    organism_key: str
    revision: int
    kind: Literal["colony", "fragment", "individual"]
    parent_colony_key: str | None
    experimental_unit_type: str | None
    experimental_unit_id: str | None
    reason: str
    created_at: datetime


class EcologyIdentityRegistryResponse(BaseModel):
    schema_version: Literal["ecology-identity-registry-0001"] = "ecology-identity-registry-0001"
    project_id: str
    identities: list[EcologyIdentityRow]
    snapshot_sha256: str
    evidence_level: Literal["registered_unverified"] = "registered_unverified"
    review_gate: Literal["scientist_review_required"] = "scientist_review_required"
