"""Independent scientific reference and validation contracts."""

from __future__ import annotations

from datetime import datetime
from itertools import pairwise
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Key = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9_.:-]+$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Split = Literal["development", "test"]
CycleState = Literal["complete", "partial"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ReferenceIndividual(Contract):
    id: Key
    species: str = Field(min_length=1, max_length=200)


class ReferenceLandmark(Contract):
    id: Key
    visibility: Literal["visible", "occluded", "absent", "uncertain", "out_of_frame"]
    x: float | None = None
    y: float | None = None

    @model_validator(mode="after")
    def coordinates(self) -> ReferenceLandmark:
        if (self.x is None) != (self.y is None) or (
            self.visibility == "visible" and self.x is None
        ):
            raise ValueError("Landmarks require a coordinate pair when visible")
        return self


class ReferencePose(Contract):
    individual_id: Key
    frame: int = Field(ge=0)
    bbox: tuple[float, float, float, float] | None = None
    landmarks: list[ReferenceLandmark] = Field(default_factory=list)
    state: Literal["scored", "occluded", "ambiguous", "missing"] = "scored"
    crossing: bool = False

    @model_validator(mode="after")
    def box(self) -> ReferencePose:
        if self.state == "scored" and self.bbox is None:
            raise ValueError("Scored poses require a source-pixel bounding box")
        if self.bbox is not None:
            x, y, width, height = self.bbox
            if min(x, y) < 0 or min(width, height) <= 0:
                raise ValueError("Invalid source-pixel bounding box")
        return self


class EventWindow(Contract):
    individual_id: Key
    label: Key
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self) -> EventWindow:
        if self.end_s <= self.start_s:
            raise ValueError("Window end must follow start")
        return self


class ReferenceEvent(EventWindow):
    id: Key
    state: CycleState = "complete"
    peak_s: float | None = None
    quality: Literal["scored", "ambiguous"] = "scored"

    @model_validator(mode="after")
    def peak_inside(self) -> ReferenceEvent:
        if self.peak_s is not None and not self.start_s <= self.peak_s <= self.end_s:
            raise ValueError("Event peak must be inside its boundaries")
        return self


class ReferenceMeasurement(Contract):
    individual_id: Key
    definition_id: Key
    frame: int = Field(ge=0)
    value: float | None
    unit: str = Field(min_length=1, max_length=40)
    state: Literal["scored", "ambiguous", "missing"] = "scored"

    @model_validator(mode="after")
    def observed_value(self) -> ReferenceMeasurement:
        if self.state == "scored" and self.value is None:
            raise ValueError("Scored measurements require a value")
        return self


class ReferenceAnnotation(Contract):
    rater_id: Key
    blinded: bool
    source: str = Field(default="Independent annotation import", min_length=1, max_length=500)
    original_sha256: Digest | None = None
    adjudicates: list[Key] = Field(default_factory=list)
    adjudication_note: str | None = Field(default=None, max_length=2000)
    poses: list[ReferencePose] = Field(default_factory=list)
    measurements: list[ReferenceMeasurement] = Field(default_factory=list)
    events: list[ReferenceEvent] = Field(default_factory=list)


class ReferenceCalibration(Contract):
    pixels_per_unit: float = Field(gt=0)
    unit: Literal["mm", "cm", "m", "um"]
    reference: str = Field(min_length=1, max_length=500)
    relative_uncertainty: float | None = Field(default=None, ge=0, lt=1)


class ReferenceRecording(Contract):
    video_id: UUID
    video_sha256: Digest
    schema_id: UUID
    schema_revision: int = Field(ge=1)
    schema_sha256: Digest
    group_id: Key
    split: Split
    conditions: str = Field(default="unspecified", min_length=1, max_length=200)
    calibration: ReferenceCalibration | None = None
    individuals: list[ReferenceIndividual] = Field(min_length=1)
    event_windows: list[EventWindow] = Field(default_factory=list)
    annotations: list[ReferenceAnnotation] = Field(min_length=2)

    @model_validator(mode="after")
    def independent_records(self) -> ReferenceRecording:
        raters = {item.rater_id for item in self.annotations if not item.adjudicates}
        all_ids = {item.rater_id for item in self.annotations}
        if len(raters) < 2 or len(all_ids) != len(self.annotations):
            raise ValueError("Each recording needs two distinct independent raters")
        individuals = {item.id for item in self.individuals}
        if len(individuals) != len(self.individuals):
            raise ValueError("Duplicate individual ID")
        windows: dict[tuple[str, str], list[EventWindow]] = {}
        for window in self.event_windows:
            if window.individual_id not in individuals:
                raise ValueError("Window references an unknown individual")
            windows.setdefault((window.individual_id, window.label), []).append(window)
        for intervals in windows.values():
            ordered = sorted(intervals, key=lambda item: item.start_s)
            if any(a.end_s > b.start_s for a, b in pairwise(ordered)):
                raise ValueError("Event scoring windows overlap")
        for annotation in self.annotations:
            parents = set(annotation.adjudicates)
            if parents and (
                len(parents) < 2 or not parents <= raters or not annotation.adjudication_note
            ):
                raise ValueError("Adjudication requires independent rater IDs and a note")
            poses = [(row.individual_id, row.frame) for row in annotation.poses]
            measures = [
                (row.individual_id, row.definition_id, row.frame, row.unit)
                for row in annotation.measurements
            ]
            if len(set(poses)) != len(poses) or len(set(measures)) != len(measures):
                raise ValueError("Duplicate pose or measurement observation")
            if len({row.id for row in annotation.events}) != len(annotation.events):
                raise ValueError("Duplicate reference event ID")
            referenced = {individual for individual, _ in poses}
            referenced.update(individual for individual, *_ in measures)
            referenced.update(event.individual_id for event in annotation.events)
            if not referenced <= individuals:
                raise ValueError("Annotation references an unknown individual")
            for event in annotation.events:
                if not any(
                    window.start_s <= event.start_s and event.end_s <= window.end_s
                    for window in windows.get((event.individual_id, event.label), [])
                ):
                    raise ValueError("Reference event is outside its declared scoring window")
        return self


class FreezeReferenceRequest(Contract):
    name: str = Field(min_length=1, max_length=200)
    data_kind: Literal["synthetic", "biological"]
    parent_id: UUID | None = None
    recordings: list[ReferenceRecording] = Field(min_length=1)

    @model_validator(mode="after")
    def split_integrity(self) -> FreezeReferenceRequest:
        groups: dict[str, Split] = {}
        for recording in self.recordings:
            if groups.setdefault(recording.group_id, recording.split) != recording.split:
                raise ValueError("A recording group cannot cross development and test splits")
        if len({item.video_id for item in self.recordings}) != len(self.recordings):
            raise ValueError("Duplicate source video")
        if len({item.video_sha256 for item in self.recordings}) != len(self.recordings):
            raise ValueError("Duplicate source video content")
        return self


class ReferenceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    parent_id: str | None
    revision: int
    name: str
    data_kind: str
    manifest_sha256: str
    created_at: datetime


class ReferenceDetail(ReferenceSummary):
    manifest: dict[str, Any]
