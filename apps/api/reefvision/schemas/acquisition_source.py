"""Uploaded, generated and explicitly consented local acquisition evidence."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from reefvision.schemas.field_capture import FieldCaptureClock, FieldText, MediaKind, Sha256

AcquisitionKind = Literal["recorded", "simulated", "camera"]
AcquisitionState = Literal["ready", "paused", "disconnected", "exhausted"]


class AcquisitionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecordedSource(AcquisitionModel):
    kind: Literal["recorded"]
    batch_id: UUID
    manifest_sha256: Sha256


class SimulatedSource(AcquisitionModel):
    kind: Literal["simulated"]
    seed: int = Field(ge=0, le=2**32 - 1, strict=True)
    start_at_utc: AwareDatetime
    period_seconds: int = Field(ge=1, le=86400, strict=True)


class CameraSource(AcquisitionModel):
    kind: Literal["camera"]
    camera_index: int = Field(ge=0, le=15, strict=True)


SourceConfiguration = Annotated[
    RecordedSource | SimulatedSource | CameraSource, Field(discriminator="kind")
]


class AcquisitionSourceCreate(AcquisitionModel):
    label: FieldText
    configuration: SourceConfiguration


class AcquisitionSourceResponse(AcquisitionSourceCreate):
    id: UUID
    project_id: UUID
    source_sha256: Sha256
    cursor: int = Field(ge=0)
    state: AcquisitionState
    revision: int = Field(ge=1)
    last_error: str | None
    next_retry_at: datetime | None
    local_consent_until: datetime | None
    created_at: datetime
    updated_at: datetime


class AcquisitionSourcePage(AcquisitionModel):
    items: list[AcquisitionSourceResponse]
    total: int
    page: int
    page_size: int


class AcquisitionStateChange(AcquisitionModel):
    action: Literal["pause", "resume", "approve_camera", "revoke_camera"]
    revision: int = Field(ge=1, strict=True)


class AcquisitionSourcePin(AcquisitionModel):
    source_id: UUID
    source_sha256: Sha256


class AcquisitionReceiptPin(AcquisitionModel):
    capture_id: UUID
    content_sha256: Sha256


class AcquisitionCaptureRequest(AcquisitionModel):
    source_sha256: Sha256
    capture_key: UUID
    confirm_camera: bool = Field(default=False, strict=True)


class AcquisitionDispatch(AcquisitionModel):
    kind: Literal["manual", "schedule"]
    occurrence_id: UUID | None = None
    workflow_run_id: UUID | None = None
    node_id: str | None = None

    @model_validator(mode="after")
    def complete_dispatch(self) -> "AcquisitionDispatch":
        linkage = (self.occurrence_id, self.workflow_run_id, self.node_id)
        if self.kind == "manual" and any(value is not None for value in linkage):
            raise ValueError("Manual capture cannot claim a schedule occurrence")
        if self.kind == "schedule" and not all(linkage):
            raise ValueError("Scheduled capture requires a workflow run and node")
        return self


class AcquisitionMedia(AcquisitionModel):
    field_batch_id: UUID
    field_batch_sha256: Sha256
    field_observation_id: UUID
    original_observation_id: UUID
    filename: str
    kind: MediaKind
    sha256: Sha256
    size_bytes: int = Field(gt=0)


class AcquisitionTime(AcquisitionModel):
    origin: Literal["field_source", "synthetic_clock", "local_host_read"]
    clock: FieldCaptureClock
    captured_at_utc: AwareDatetime | None
    uncertainty_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    host_received_at_utc: AwareDatetime | None = None
    host_read_elapsed_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class SyntheticReading(AcquisitionModel):
    method: Literal["reefvision-synthetic-v1"] = "reefvision-synthetic-v1"
    value: int = Field(ge=0, le=100)
    unit: Literal["synthetic arbitrary units"] = "synthetic arbitrary units"


class AcquisitionReceiptData(AcquisitionModel):
    schema_version: Literal["reefvision-acquisition-capture-1"] = "reefvision-acquisition-capture-1"
    id: UUID
    project_id: UUID
    source_id: UUID
    source_kind: AcquisitionKind
    source_sha256: Sha256
    ordinal: int = Field(ge=0)
    dispatch: AcquisitionDispatch
    time: AcquisitionTime
    media: AcquisitionMedia
    synthetic_reading: SyntheticReading | None = None
    recorded_at_utc: AwareDatetime


class AcquisitionCaptureReceipt(AcquisitionModel):
    content_sha256: Sha256
    receipt: AcquisitionReceiptData


class AcquisitionCapturePage(AcquisitionModel):
    items: list[AcquisitionCaptureReceipt]
    total: int
    page: int
    page_size: int
