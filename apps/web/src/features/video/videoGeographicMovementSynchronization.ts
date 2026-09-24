import type { GeographicMovementSegment } from "./videoGeographicMovementAnalyticsApi";

export interface GeographicSegmentSeekTarget {
  frameIndex: number;
  frameTimeSeconds: number;
}

/**
 * Find the persisted segment containing the playback frame.
 *
 * At a shared endpoint, the preceding segment is active.
 * Gaps are not interpolated.
 */
export function activeGeographicSegmentForFrame(
  segments: readonly GeographicMovementSegment[],
  frameIndex: number | null,
): GeographicMovementSegment | null {
  if (frameIndex === null || !Number.isFinite(frameIndex) || frameIndex < 0) {
    return null;
  }

  return (
    segments.find(
      (segment) =>
        segment.start_frame_index <= frameIndex &&
        frameIndex <= segment.end_frame_index,
    ) ?? null
  );
}

/**
 * Use the endpoint's persisted frame and timestamp.
 * Never derive geographic movement timing from video FPS here.
 */
export function geographicSegmentSeekTarget(
  segment: GeographicMovementSegment,
): GeographicSegmentSeekTarget | null {
  if (
    !Number.isInteger(segment.end_frame_index) ||
    segment.end_frame_index < 0 ||
    !Number.isFinite(segment.end_frame_time_s) ||
    segment.end_frame_time_s < 0
  ) {
    return null;
  }

  return {
    frameIndex: segment.end_frame_index,
    frameTimeSeconds: segment.end_frame_time_s,
  };
}
