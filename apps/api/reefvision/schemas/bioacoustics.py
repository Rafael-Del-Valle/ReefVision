"""Sample-exact bioacoustic evidence and clock contracts."""

from datetime import UTC, datetime
from typing import Annotated, Any, Generic, Literal, Self, TypeVar
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

MAX_AUDIO_BYTES = 256 * 1024**2
MAX_AUDIO_PROPOSALS = 500
MAX_AUDIO_ANCHORS = 50
AudioSHA = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Sample = Annotated[int, Field(ge=0, strict=True)]
AudioNote = Annotated[str, Field(min_length=1, max_length=2000)]
AudioDecision = Literal["accepted", "dismissed", "uncertain"]
AudioStatus = Literal["proposed", "accepted", "dismissed", "uncertain"]
T = TypeVar("T")


class AudioSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, from_attributes=True)


class AudioPage(AudioSchema, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class AudioAssetRead(AudioSchema):
    id: UUID
    project_id: UUID
    original_asset_id: UUID
    original_project_id: UUID
    original_filename: str
    sha256: AudioSHA
    size_bytes: int = Field(gt=0, le=MAX_AUDIO_BYTES)
    sample_rate_hz: int = Field(ge=8_000, le=96_000)
    sample_count: int = Field(gt=0)
    channel_count: Literal[1, 2]
    bits_per_sample: Literal[8, 16, 24, 32]
    created_at: datetime


class WaveformPeak(AudioSchema):
    start_sample: Sample
    end_sample: Sample
    minimum: float = Field(ge=-1, le=1, allow_inf_nan=False)
    maximum: float = Field(ge=-1, le=1, allow_inf_nan=False)


class AudioWaveform(AudioSchema):
    asset_id: UUID
    source_sha256: AudioSHA
    channel: Sample
    sample_rate_hz: int
    sample_count: int
    peaks: list[WaveformPeak]


class AudioProposalCreate(AudioSchema):
    start_sample: Sample
    end_sample: Sample
    channel: Sample
    label: str = Field(min_length=1, max_length=200)
    notes: AudioNote | None = None
    source_sha256: AudioSHA

    @model_validator(mode="after")
    def nonempty_interval(self) -> Self:
        if self.end_sample <= self.start_sample:
            raise ValueError("Choose a nonempty half-open source sample interval")
        return self


class AudioReviewCreate(AudioSchema):
    expected_revision: Sample
    decision: AudioDecision
    reason: AudioNote


class AudioReviewRead(AudioSchema):
    id: UUID
    project_id: UUID
    proposal_id: UUID
    reviewer: str
    decision: AudioDecision
    reason: AudioNote
    revision: int = Field(ge=1)
    reviewed_at: datetime


class AudioProposalRead(AudioProposalCreate):
    id: UUID
    project_id: UUID
    asset_id: UUID
    author: str
    created_at: datetime
    proposal_sha256: AudioSHA
    status: AudioStatus
    review_revision: Sample
    latest_review: AudioReviewRead | None


class _Anchor(AudioSchema):
    sample: Sample
    source_sha256: AudioSHA
    uncertainty_us: int = Field(ge=0, le=86_400_000_000, strict=True)
    evidence: AudioNote


class UTCAnchor(_Anchor):
    kind: Literal["utc"]
    utc: AwareDatetime

    @field_validator("utc", mode="before")
    @classmethod
    def require_declared_offset(cls, value: object) -> object:
        if not isinstance(value, (str, datetime)):
            raise ValueError("Enter a timestamp with an explicit UTC offset")
        if isinstance(value, str) and not (
            "T" in value and (value.endswith("Z") or "+" in value[10:] or "-" in value[10:])
        ):
            raise ValueError("Enter a timestamp with an explicit UTC offset")
        return value

    @field_validator("utc")
    @classmethod
    def normalize_utc(cls, value: datetime) -> datetime:
        try:
            return value.astimezone(UTC)
        except OverflowError as exc:
            raise ValueError("The anchor is outside the supported UTC range") from exc


class VideoAnchor(_Anchor):
    kind: Literal["video"]
    video_id: UUID
    video_sha256: AudioSHA
    video_time_us: int = Field(ge=0, le=31_536_000_000_000, strict=True)


AudioAnchorCreate = Annotated[UTCAnchor | VideoAnchor, Field(discriminator="kind")]
_anchor_annotation: Any = AudioAnchorCreate
AUDIO_ANCHOR = TypeAdapter[AudioAnchorCreate](_anchor_annotation)


class _AnchorIdentity(AudioSchema):
    id: UUID
    project_id: UUID
    asset_id: UUID
    anchor_sha256: AudioSHA
    author: str
    created_at: datetime


class UTCAnchorRead(UTCAnchor, _AnchorIdentity):
    pass


class VideoAnchorRead(VideoAnchor, _AnchorIdentity):
    pass


AudioAnchorRead = Annotated[UTCAnchorRead | VideoAnchorRead, Field(discriminator="kind")]
_anchor_read_annotation: Any = AudioAnchorRead
AUDIO_ANCHOR_READ = TypeAdapter[AudioAnchorRead](_anchor_read_annotation)


class AudioAlignment(AudioSchema):
    status: Literal["withheld", "utc", "video"]
    reason: str | None = None
    start_utc: AwareDatetime | None = None
    end_utc: AwareDatetime | None = None
    start_video_us: Sample | None = None
    end_video_us: Sample | None = None
    uncertainty_us: Sample | None = None


class AudioReportEntry(AudioSchema):
    proposal: AudioProposalRead
    alignment: AudioAlignment


class AudioReportCreate(AudioSchema):
    anchor_id: UUID | None = None


class AudioReportSnapshot(AudioSchema):
    schema_version: Literal["reefvision-bioacoustic-report-1"] = "reefvision-bioacoustic-report-1"
    method: Literal["sample-clock-offset-v1"] = "sample-clock-offset-v1"
    source: AudioAssetRead
    anchor: AudioAnchorRead | None
    clock_conflicts: list[UUID]
    entries: list[AudioReportEntry] = Field(max_length=MAX_AUDIO_PROPOSALS)


class AudioReportRead(AudioSchema):
    id: UUID
    project_id: UUID
    asset_id: UUID
    snapshot: AudioReportSnapshot
    report_sha256: AudioSHA
    created_at: datetime
