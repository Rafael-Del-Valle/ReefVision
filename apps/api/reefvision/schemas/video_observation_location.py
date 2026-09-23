"""Typed native-image location selected for one video observation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, FiniteFloat

VideoObservationImageLocationMethod = Literal["explicit_point", "bbox_center"]


class VideoObservationImageLocation(BaseModel):
    """Selected native-image point plus the original observation bounding box."""

    schema_version: Literal["video-observation-image-location-0001"]
    bbox: tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat]
    pixel_x: FiniteFloat
    pixel_y: FiniteFloat
    method: VideoObservationImageLocationMethod
