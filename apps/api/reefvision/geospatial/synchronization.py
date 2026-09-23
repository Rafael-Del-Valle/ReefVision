"""Binary-search telemetry lookup using relative video time."""

from bisect import bisect_left
from collections.abc import Iterable
from math import isfinite
from typing import Protocol

from reefvision.domain.errors import ValidationError
from reefvision.geospatial.models import TelemetryMatch, TelemetrySample


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
