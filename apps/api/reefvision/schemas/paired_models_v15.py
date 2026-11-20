"""Reviewed selections and per-independent-unit model comparison evidence."""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from reefvision.schemas.model_runtime import Digest

ComparisonTask = Literal["detector", "mask", "pose", "tracking", "event"]


class ComparisonChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    sha256: Digest


class ComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: ComparisonTask
    left: ComparisonChoice
    right: ComparisonChoice
    sources: Annotated[list[ComparisonChoice], Field(min_length=1, max_length=2)]

    @model_validator(mode="after")
    def paired_inputs(self) -> "ComparisonRequest":
        if self.left.id == self.right.id:
            raise ValueError("Select two distinct reviewed models")
        count = 1 if self.task in {"detector", "mask"} else 2
        if len(self.sources) != count or len({s.id for s in self.sources}) != count:
            raise ValueError("Select one frozen dataset or one scored video report per model")
        return self


class PairedMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    left: FiniteFloat | None
    right: FiniteFloat | None


class PairedObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_kind: Literal["image", "video"]
    media_id: UUID
    frame: int | None = Field(default=None, ge=0)
    seconds: FiniteFloat | None = Field(default=None, ge=0)
    metrics: list[PairedMetric]
    exclusion: str | None = None


class PairedGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_id: str = Field(min_length=1)
    observations: list[PairedObservation] = Field(min_length=1)


class ComparisonEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_id: UUID
    reference_sha256: Digest
    source_sha256: list[Digest] = Field(min_length=2)
    inference_job_ids: list[UUID] = Field(default_factory=list)
    groups: list[PairedGroup] = Field(min_length=1)
    method: str
    limitations: list[str]
    evaluation_status: Literal["held_out", "exploratory"] = "held_out"
    lineage: list[dict[str, Any]] = Field(default_factory=list)


class ComparisonSource(ComparisonChoice):
    label: str
    model_ids: list[UUID] = Field(default_factory=list)
    reference_id: UUID
    reference_sha256: Digest
