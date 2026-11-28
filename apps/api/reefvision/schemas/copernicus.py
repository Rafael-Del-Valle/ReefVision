"""Small, explicit, reproducible modeled-ocean subsets."""

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from reefvision.schemas.scientific_data import ScientificModel, utc_timestamp


def default_variables() -> list[Literal["uo", "vo", "thetao", "so"]]:
    return ["uo", "vo", "thetao", "so"]


class CopernicusRequest(ScientificModel):
    dataset_id: str = Field(pattern=r"^cmems_mod_[A-Za-z0-9_.-]+$", max_length=200)
    dataset_version: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    variables: list[Literal["uo", "vo", "thetao", "so"]] = Field(
        default_factory=default_variables, min_length=1, max_length=4
    )
    minimum_longitude: float = Field(ge=-180, le=180)
    maximum_longitude: float = Field(ge=-180, le=180)
    minimum_latitude: float = Field(ge=-90, le=90)
    maximum_latitude: float = Field(ge=-90, le=90)
    minimum_depth: float = Field(default=0, ge=0, le=11000)
    maximum_depth: float = Field(default=10, ge=0, le=11000)
    start_datetime: datetime
    end_datetime: datetime
    offline: bool = False
    refresh: bool = False

    _utc = field_validator("start_datetime", "end_datetime")(utc_timestamp)

    @model_validator(mode="after")
    def bounded(self) -> "CopernicusRequest":
        if not 0 <= self.maximum_longitude - self.minimum_longitude <= 5:
            raise ValueError(
                "Longitude extent must be ordered and at most 5 degrees; split dateline requests"
            )
        if not 0 <= self.maximum_latitude - self.minimum_latitude <= 5:
            raise ValueError("Latitude extent must be ordered and at most 5 degrees")
        if self.maximum_depth < self.minimum_depth:
            raise ValueError("Depth bounds must be ordered, positive down from sea surface")
        if not 0 <= (self.end_datetime - self.start_datetime).total_seconds() <= 604800:
            raise ValueError("Time range must be ordered and at most 7 days")
        if len(set(self.variables)) != len(self.variables):
            raise ValueError("Variables must be unique")
        if self.offline and self.refresh:
            raise ValueError("Offline reuse cannot request a live refresh")
        return self
