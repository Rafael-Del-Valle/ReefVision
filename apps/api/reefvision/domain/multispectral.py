"""Compute on original digital numbers using explicit integer grid translations."""

from hashlib import sha256

import numpy as np
from numpy.typing import NDArray

from reefvision.domain.errors import ValidationError
from reefvision.schemas.multispectral import (
    AcquisitionSnapshot,
    FrozenBand,
    IndexInput,
    PixelExclusions,
    SpectralEstimate,
)

Planes = dict[int, NDArray[np.uint16]]


def aligned_band(
    band: FrozenBand, source: NDArray[np.uint16], shape: tuple[int, int]
) -> tuple[NDArray[np.float64], NDArray[np.bool_]]:
    height, width = shape
    values = np.full(shape, np.nan)
    footprint = np.zeros(shape, dtype=bool)
    x0, y0 = max(0, band.offset_x), max(0, band.offset_y)
    x1, y1 = min(width, band.offset_x + band.width), min(height, band.offset_y + band.height)
    if x1 <= x0 or y1 <= y0:
        return values, footprint
    area = np.s_[y0:y1, x0:x1]
    raw = source[y0 - band.offset_y : y1 - band.offset_y, x0 - band.offset_x : x1 - band.offset_x]
    footprint[area] = True
    valid = raw != band.nodata if band.nodata is not None else np.ones(raw.shape, dtype=bool)
    calibration = band.calibration
    if calibration:
        valid &= (raw >= calibration.dark_dn) & (raw <= calibration.white_dn)
        converted = (
            (raw.astype(np.float64) - calibration.dark_dn)
            * calibration.white_reflectance
            / (calibration.white_dn - calibration.dark_dn)
        )
    else:
        converted = raw.astype(np.float64) / ((1 << band.bits) - 1)
    values[area] = np.where(valid, converted, np.nan)
    return values, footprint


def composite(
    snapshot: AcquisitionSnapshot, channels: tuple[int, int, int], planes: Planes
) -> NDArray[np.uint8]:
    if not snapshot.alignment:
        raise ValidationError(
            "Record a reviewed common pixel grid before composing different bands"
        )
    shape = (snapshot.bands[0].height, snapshot.bands[0].width)
    pixels = np.empty((*shape, 4), dtype=np.uint8)
    valid = np.ones(shape, dtype=bool)
    for channel, index in enumerate(channels):
        values, _ = aligned_band(snapshot.bands[index], planes[index], shape)
        valid &= np.isfinite(values)
        pixels[:, :, channel] = np.rint(np.nan_to_num(values) * 255).clip(0, 255).astype(np.uint8)
    pixels[:, :, 3] = valid.astype(np.uint8) * 255
    return pixels


def normalized_difference(
    snapshot: AcquisitionSnapshot, selection: IndexInput, planes: Planes
) -> tuple[SpectralEstimate, NDArray[np.float32] | None]:
    shape = (snapshot.bands[0].height, snapshot.bands[0].width)
    count = shape[0] * shape[1]
    reasons = []
    if not snapshot.alignment:
        reasons.append("The common pixel grid has no reviewed alignment.")
    indices = (selection.positive, selection.negative)
    for i in indices:
        if snapshot.bands[i].calibration is None:
            reasons.append(f"Band {snapshot.bands[i].name} has no reflectance calibration.")
    if reasons:
        return SpectralEstimate(status="withheld", reasons=reasons, reference_pixels=count), None
    positive, pos_footprint = aligned_band(snapshot.bands[indices[0]], planes[indices[0]], shape)
    negative, neg_footprint = aligned_band(snapshot.bands[indices[1]], planes[indices[1]], shape)
    overlap = pos_footprint & neg_footprint
    measured = np.isfinite(positive) & np.isfinite(negative)
    denominator = positive + negative
    valid = measured & (denominator > 0)
    excluded = PixelExclusions(
        outside_grid=int((~overlap).sum()),
        invalid_band_sample=int((overlap & ~measured).sum()),
        zero_denominator=int((measured & ~valid).sum()),
    )
    if not valid.any():
        return SpectralEstimate(
            status="withheld",
            reasons=["No overlapping, calibrated sample has a nonzero denominator."],
            reference_pixels=count,
            excluded=excluded,
        ), None
    values = np.full(shape, np.nan, dtype="<f4")
    np.divide(positive - negative, denominator, out=values, where=valid)
    kept = values[valid]
    return SpectralEstimate(
        status="available",
        reasons=[],
        reference_pixels=count,
        valid_pixels=int(kept.size),
        excluded=excluded,
        minimum=float(kept.min()),
        maximum=float(kept.max()),
        mean=float(kept.mean(dtype=np.float64)),
        mask_sha256=sha256(valid.astype(np.uint8).tobytes()).hexdigest(),
        float32_le_sha256=sha256(values.tobytes()).hexdigest(),
    ), values
