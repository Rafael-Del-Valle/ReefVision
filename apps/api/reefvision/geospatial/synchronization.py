"""Binary-search telemetry lookup using relative video time."""

from bisect import bisect_left
from collections.abc import Iterable
from math import isfinite
from typing import Protocol

from reefvision.domain.errors import ValidationError
from reefvision.geospatial.models import TelemetryMatch, TelemetryProvenance, TelemetrySample


class TelemetrySource(Protocol):
    def sample_for_time(
        self, time_s: float, *, max_delta_s: float | None = None
    ) -> TelemetryMatch | None: ...

    def sample_for_frame(
        self, frame_index: int, fps: float, *, max_delta_s: float | None = None
    ) -> TelemetryMatch | None: ...


class IndexedTelemetrySource:
    def __init__(self, samples: Iterable[TelemetrySample]) -> None:
        self.samples = tuple(sorted(samples, key=lambda item: item.time_s))
        self._times = tuple(item.time_s for item in self.samples)

    def sample_for_time(
        self, time_s: float, *, max_delta_s: float | None = None
    ) -> TelemetryMatch | None:
        if not isfinite(time_s) or time_s < 0:
            raise ValidationError("Video time must be finite and nonnegative")
        if max_delta_s is not None and (not isfinite(max_delta_s) or max_delta_s < 0):
            raise ValidationError("Maximum telemetry delta must be finite and nonnegative")
        if not self.samples:
            return None
        index = bisect_left(self._times, time_s)
        candidates = self.samples[max(0, index - 1) : min(len(self.samples), index + 1)]
        sample = min(candidates, key=lambda item: (abs(item.time_s - time_s), item.time_s))
        # Duplicated timestamps consistently select the first source sample.
        sample = self.samples[bisect_left(self._times, sample.time_s)]
        delta = sample.time_s - time_s
        if max_delta_s is not None and abs(delta) > max_delta_s:
            return None
        return TelemetryMatch(sample=sample, requested_time_s=time_s, delta_s=delta)

    def sample_for_frame(
        self, frame_index: int, fps: float, *, max_delta_s: float | None = None
    ) -> TelemetryMatch | None:
        if isinstance(frame_index, bool) or not isinstance(frame_index, int) or frame_index < 0:
            raise ValidationError("Video frame index must be a nonnegative integer")
        if not isfinite(fps) or fps <= 0:
            raise ValidationError("Video FPS must be finite and positive")
        return self.sample_for_time(frame_index / fps, max_delta_s=max_delta_s)


def _pick(
    airdata_value: object | None,
    srt_value: object | None,
) -> tuple[object | None, str | None]:
    if airdata_value is not None:
        return airdata_value, "airdata"
    if srt_value is not None:
        return srt_value, "dji_srt"
    return None, None


class PreferredTelemetrySource:
    """Merge aligned AirData and SRT telemetry with AirData camera pose preferred.

    airdata_time_offset_s maps video-relative time to AirData flight-relative
    time: airdata_time = video_time + airdata_time_offset_s. A nonzero offset
    requires independent evidence and is never fitted from geographic residuals.
    """

    def __init__(
        self,
        *,
        airdata: TelemetrySource | None,
        srt: TelemetrySource | None,
        airdata_time_offset_s: float = 0.0,
        airdata_time_offset_evidence: str | None = None,
    ) -> None:
        if airdata is None and srt is None:
            raise ValidationError("At least one telemetry source is required")
        if not isfinite(airdata_time_offset_s):
            raise ValidationError("AirData time offset must be finite")
        evidence = (airdata_time_offset_evidence or "").strip()
        if airdata_time_offset_s and not evidence:
            raise ValidationError("A nonzero AirData time offset requires independent evidence")
        self.airdata = airdata
        self.srt = srt
        self.airdata_time_offset_s = airdata_time_offset_s
        self.airdata_time_offset_evidence = evidence or None

    def sample_for_time(
        self, time_s: float, *, max_delta_s: float | None = None
    ) -> TelemetryMatch | None:
        if not isfinite(time_s) or time_s < 0:
            raise ValidationError("Video time must be finite and nonnegative")
        if max_delta_s is not None and (not isfinite(max_delta_s) or max_delta_s < 0):
            raise ValidationError("Maximum telemetry delta must be finite and nonnegative")

        air_match = (
            self.airdata.sample_for_time(time_s + self.airdata_time_offset_s)
            if self.airdata is not None
            else None
        )
        srt_match = self.srt.sample_for_time(time_s) if self.srt is not None else None
        if air_match is None and srt_match is None:
            return None

        air = air_match.sample if air_match is not None else None
        srt = srt_match.sample if srt_match is not None else None

        if air is not None and air.latitude is not None and air.longitude is not None:
            latitude, longitude, position_source = air.latitude, air.longitude, "airdata"
        elif srt is not None and srt.latitude is not None and srt.longitude is not None:
            latitude, longitude, position_source = srt.latitude, srt.longitude, "dji_srt"
        else:
            latitude = longitude = None
            position_source = None

        relative_altitude, altitude_source = _pick(
            air.relative_altitude_m if air is not None else None,
            srt.relative_altitude_m if srt is not None else None,
        )
        gimbal_yaw, yaw_source = _pick(
            air.gimbal_yaw_deg if air is not None else None,
            srt.gimbal_yaw_deg if srt is not None else None,
        )
        gimbal_pitch, pitch_source = _pick(
            air.gimbal_pitch_deg if air is not None else None,
            srt.gimbal_pitch_deg if srt is not None else None,
        )
        gimbal_roll, roll_source = _pick(
            air.gimbal_roll_deg if air is not None else None,
            srt.gimbal_roll_deg if srt is not None else None,
        )

        def prefer(field: str) -> object | None:
            air_value = getattr(air, field) if air is not None else None
            srt_value = getattr(srt, field) if srt is not None else None
            return air_value if air_value is not None else srt_value

        assert air is not None or srt is not None
        merged = TelemetrySample.model_validate(
            {
                "sample_index": air.sample_index if air is not None else srt.sample_index,
                "time_s": time_s,
                "frame_number": srt.frame_number if srt is not None else None,
                "latitude": latitude,
                "longitude": longitude,
                "relative_altitude_m": relative_altitude,
                "absolute_altitude_m": prefer("absolute_altitude_m"),
                "gimbal_yaw_deg": gimbal_yaw,
                "gimbal_pitch_deg": gimbal_pitch,
                "gimbal_roll_deg": gimbal_roll,
                "aircraft_yaw_deg": prefer("aircraft_yaw_deg"),
                "aircraft_pitch_deg": prefer("aircraft_pitch_deg"),
                "aircraft_roll_deg": prefer("aircraft_roll_deg"),
                "horizontal_speed_mps": prefer("horizontal_speed_mps"),
                "vertical_speed_mps": prefer("vertical_speed_mps"),
                "iso": prefer("iso"),
                "shutter_speed_s": prefer("shutter_speed_s"),
                "focal_length_mm": prefer("focal_length_mm"),
                "focal_length_raw": prefer("focal_length_raw"),
                "digital_zoom_ratio": prefer("digital_zoom_ratio"),
            }
        )

        provenance = TelemetryProvenance(
            position_source=position_source,
            relative_altitude_source=altitude_source,
            gimbal_yaw_source=yaw_source,
            gimbal_pitch_source=pitch_source,
            gimbal_roll_source=roll_source,
            airdata_delta_s=air_match.delta_s if air_match is not None else None,
            srt_delta_s=srt_match.delta_s if srt_match is not None else None,
            airdata_time_offset_s=self.airdata_time_offset_s,
            airdata_time_offset_evidence=self.airdata_time_offset_evidence,
        )

        used_sources = {
            source
            for source in (
                position_source,
                altitude_source,
                yaw_source,
                pitch_source,
                roll_source,
            )
            if source is not None
        }
        deltas: list[float] = []
        if "airdata" in used_sources and air_match is not None:
            deltas.append(air_match.delta_s)
        if "dji_srt" in used_sources and srt_match is not None:
            deltas.append(srt_match.delta_s)
        if not deltas:
            if air_match is not None:
                deltas.append(air_match.delta_s)
            elif srt_match is not None:
                deltas.append(srt_match.delta_s)
        delta_s = max(deltas, key=abs)
        if max_delta_s is not None and abs(delta_s) > max_delta_s:
            return None
        return TelemetryMatch(
            sample=merged,
            requested_time_s=time_s,
            delta_s=delta_s,
            provenance=provenance,
        )

    def sample_for_frame(
        self, frame_index: int, fps: float, *, max_delta_s: float | None = None
    ) -> TelemetryMatch | None:
        if isinstance(frame_index, bool) or not isinstance(frame_index, int) or frame_index < 0:
            raise ValidationError("Video frame index must be a nonnegative integer")
        if not isfinite(fps) or fps <= 0:
            raise ValidationError("Video FPS must be finite and positive")
        return self.sample_for_time(frame_index / fps, max_delta_s=max_delta_s)
