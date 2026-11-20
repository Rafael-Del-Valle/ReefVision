"""Band calibration is a statement about an original source grid and its digital numbers."""

from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StringConstraints, model_validator

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SpectralModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PanelCalibration(SpectralModel):
    dark_dn: FiniteFloat = Field(ge=0, le=65535)
    white_dn: FiniteFloat = Field(gt=0, le=65535)
    white_reflectance: FiniteFloat = Field(gt=0, le=1)
    reference: Label

    @model_validator(mode="after")
    def different_levels(self) -> "PanelCalibration":
        if self.white_dn <= self.dark_dn:
            raise ValueError(
                "White reference must exceed the dark reference in source digital numbers"
            )
        return self


class BandInput(SpectralModel):
    name: Label
    wavelength_nm: FiniteFloat = Field(gt=0, le=3000)
    bandwidth_nm: FiniteFloat | None = Field(default=None, gt=0, le=1000)
    image_id: UUID
    original_sha256: Digest
    offset_x: int = Field(default=0, ge=-65535, le=65535, strict=True)
    offset_y: int = Field(default=0, ge=-65535, le=65535, strict=True)
    nodata: int | None = Field(default=None, ge=0, le=65535, strict=True)
    calibration: PanelCalibration | None = None


class GridAlignment(SpectralModel):
    grid: Label
    reviewer: Label
    evidence: Label
    maximum_residual_px: FiniteFloat = Field(ge=0)


class AcquisitionInput(SpectralModel):
    label: Label
    sensor: Label
    alignment: GridAlignment | None = None
    bands: list[BandInput] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def distinct_originals(self) -> "AcquisitionInput":
        if any(
            len(values) != len(self.bands)
            for values in (
                {b.image_id for b in self.bands},
                {b.original_sha256 for b in self.bands},
                {b.name.casefold() for b in self.bands},
            )
        ):
            raise ValueError("Choose distinct, named band originals")
        if self.bands[0].offset_x or self.bands[0].offset_y:
            raise ValueError("The first band defines the reference grid at offset (0, 0)")
        return self


class FrozenBand(BandInput):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    bits: Literal[8, 16]


class AcquisitionSnapshot(SpectralModel):
    method: Literal["original-monochrome-bands-v1"] = "original-monochrome-bands-v1"
    source_project_id: UUID
    label: Label
    sensor: Label
    alignment: GridAlignment | None
    bands: list[FrozenBand] = Field(min_length=2, max_length=8)


class IndexInput(SpectralModel):
    acquisition_sha256: Digest
    positive: int = Field(ge=0, le=7, strict=True)
    negative: int = Field(ge=0, le=7, strict=True)

    @model_validator(mode="after")
    def distinct_bands(self) -> "IndexInput":
        if self.positive == self.negative:
            raise ValueError("Choose two different spectral bands")
        return self


class PixelExclusions(SpectralModel):
    outside_grid: int = 0
    invalid_band_sample: int = 0
    zero_denominator: int = 0


class SpectralEstimate(SpectralModel):
    status: Literal["available", "withheld"]
    reasons: list[str]
    reference_pixels: int
    valid_pixels: int = 0
    excluded: PixelExclusions = Field(default_factory=PixelExclusions)
    minimum: FiniteFloat | None = None
    maximum: FiniteFloat | None = None
    mean: FiniteFloat | None = None
    mask_sha256: Digest | None = None
    float32_le_sha256: Digest | None = None


class IndexSnapshot(SpectralModel):
    method: Literal["reflectance-normalized-difference-v1"] = "reflectance-normalized-difference-v1"
    acquisition: AcquisitionSnapshot
    selection: IndexInput
    result: SpectralEstimate


Content = TypeVar("Content", AcquisitionSnapshot, IndexSnapshot)


class SpectralRecord(SpectralModel, Generic[Content]):
    id: UUID
    project_id: UUID
    content_sha256: Digest
    created_at: datetime
    snapshot: Content


class SpectralPage(SpectralModel, Generic[Content]):
    items: list[SpectralRecord[Content]]
    total: int
