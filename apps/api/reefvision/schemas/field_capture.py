"""Portable, attributed offline field observations and reconciliation receipts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

FIELD_CAPTURE_FORMAT: Literal["reefvision-field-capture-1"] = "reefvision-field-capture-1"
MAX_FIELD_OBSERVATIONS = 500
FieldText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
FieldNote = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
WallTime = Annotated[
    str, StringConstraints(pattern=r"^\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d(?:\.\d{1,6})?)?$")
]
SourceFilename = Annotated[
    str, StringConstraints(min_length=1, max_length=255, pattern=r"^[^/\\\x00-\x1f]+$")
]
MediaKind = Literal["image", "video"]
FieldReviewDecision = Literal["retain_both", "prefer_existing", "prefer_incoming"]


class _FieldModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldCaptureClock(_FieldModel):
    state: Literal["known_offset", "unknown"]
    wall_time: WallTime | None = None
    utc_offset_minutes: int | None = Field(default=None, ge=-14 * 60, le=14 * 60)
    evidence: FieldNote

    @model_validator(mode="after")
    def validate_clock(self) -> FieldCaptureClock:
        if self.wall_time is not None:
            datetime.fromisoformat(self.wall_time)
        if self.state == "known_offset":
            if self.wall_time is None or self.utc_offset_minutes is None:
                raise ValueError("Known capture time requires the source wall time and UTC offset")
            try:
                self.utc_timestamp()
            except OverflowError as exc:
                raise ValueError("Capture time is outside the supported UTC range") from exc
        elif self.utc_offset_minutes is not None:
            raise ValueError("An unknown source clock cannot claim a UTC offset")
        return self

    def utc_timestamp(self) -> datetime | None:
        if self.wall_time is None or self.utc_offset_minutes is None:
            return None
        offset = timezone(timedelta(minutes=self.utc_offset_minutes))
        return datetime.fromisoformat(self.wall_time).replace(tzinfo=offset).astimezone(UTC)


class FieldCapturePosition(_FieldModel):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    evidence: FieldNote


class FieldCaptureMetadata(_FieldModel):
    observer: FieldText
    clock: FieldCaptureClock
    observation_key: FieldText | None = None
    site: FieldText | None = None
    subject: FieldText | None = None
    source_label: FieldText | None = None
    position: FieldCapturePosition | None = None
    notes: FieldNote | None = None


class FieldCaptureEntry(_FieldModel):
    source_observation_id: UUID
    filename: SourceFilename
    kind: MediaKind
    sha256: Sha256
    size_bytes: int = Field(gt=0)
    metadata: FieldCaptureMetadata


class FieldCaptureManifest(_FieldModel):
    schema_version: Literal["reefvision-field-capture-1"] = FIELD_CAPTURE_FORMAT
    origin_project_id: UUID
    origin_batch_id: UUID
    label: FieldText
    observations: list[FieldCaptureEntry] = Field(min_length=1, max_length=MAX_FIELD_OBSERVATIONS)

    @model_validator(mode="after")
    def validate_source_ids(self) -> FieldCaptureManifest:
        ids = {entry.source_observation_id for entry in self.observations}
        if len(ids) != len(self.observations):
            raise ValueError("A field batch cannot repeat the same source observation identity")
        return self


class FieldCaptureArchiveManifest(_FieldModel):
    manifest_sha256: Sha256
    manifest: FieldCaptureManifest


class FieldCaptureBatchCreate(_FieldModel):
    label: FieldText


class FieldCaptureObservationResponse(FieldCaptureEntry):
    id: UUID
    captured_at_utc: datetime | None


class FieldCaptureBatchSummary(_FieldModel):
    id: UUID
    project_id: UUID
    origin_project_id: UUID
    origin_batch_id: UUID
    label: str
    manifest_sha256: Sha256 | None
    created_at: datetime


class FieldCaptureBatchResponse(FieldCaptureBatchSummary):
    observations: list[FieldCaptureObservationResponse]


class FieldCaptureBatchPage(_FieldModel):
    items: list[FieldCaptureBatchSummary]
    total: int
    page: int
    page_size: int


class FieldCaptureImportResponse(_FieldModel):
    batch: FieldCaptureBatchResponse
    duplicate: bool


class FieldCaptureReconcileRequest(_FieldModel):
    manifest_sha256: Sha256


class FieldCaptureConflict(_FieldModel):
    against_observation_id: UUID
    against_batch_id: UUID
    against: FieldCaptureEntry
    reason: Literal[
        "source_identity_changed", "declared_observation_changed", "media_metadata_changed"
    ]


class FieldCaptureReconciliationItem(_FieldModel):
    observation_id: UUID
    source_observation_id: UUID
    kind: MediaKind
    sha256: Sha256
    asset_id: UUID
    outcome: Literal["imported", "duplicate_media", "conflict"]
    conflicts: list[FieldCaptureConflict]


class FieldCaptureReconciliation(_FieldModel):
    project_id: UUID
    batch_id: UUID
    manifest_sha256: Sha256
    rows: list[FieldCaptureReconciliationItem]
    report_sha256: Sha256


class FieldCaptureReviewCreate(_FieldModel):
    observation_id: UUID
    against_observation_id: UUID
    reviewer: FieldText
    decision: FieldReviewDecision
    notes: FieldNote


class FieldCaptureReviewResponse(FieldCaptureReviewCreate):
    id: UUID
    created_at: datetime
