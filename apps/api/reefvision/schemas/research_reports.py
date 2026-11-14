"""Immutable publication figure and table contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from reefvision.schemas.ecology_pose_links import Digest

ReportSource = Literal["ecology", "event_summary", "comparison"]
Figure = Literal[
    "trajectory",
    "group_summary",
    "treatment_summary",
    "sample_coverage",
    "event_rate",
    "identity_scatter",
    "bland_altman",
]


class FigureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_kind: ReportSource
    source_id: UUID
    figure: Figure
    title: str = Field(min_length=1, max_length=120)
    style: Literal["grayscale", "accessible_color"] = "grayscale"


class FigurePoint(BaseModel):
    x: FiniteFloat
    y: FiniteFloat
    label: str
    denominator: int | None = None
    lower: FiniteFloat | None = None
    upper: FiniteFloat | None = None


class FigureSeries(BaseModel):
    label: str
    points: list[FigurePoint]


class FigureSnapshot(BaseModel):
    method: Literal["reefvision-publication-figure-v1"] = "reefvision-publication-figure-v1"
    software_version: str
    configuration: FigureRequest
    source_sha256: Digest
    source_method: str
    source_evidence: str
    x_label: str
    x_scale: Literal["numeric", "utc_day"] = "numeric"
    y_label: str
    geometry: Literal["points", "lines", "bars"]
    series: list[FigureSeries]
    guidelines: list[tuple[str, FiniteFloat]] = Field(default_factory=list)
    zero_identity: bool = False
    uncertainty: str | None = None
    exclusions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    provenance: dict[str, str] = Field(default_factory=dict)


class FigureRecord(BaseModel):
    id: UUID
    project_id: UUID
    created_at: datetime
    content_sha256: Digest
    local_source_id: UUID
    stale: bool
    snapshot: FigureSnapshot
