import { describe, expect, it } from "vitest";

import type { GeographicMovementSegment } from "./videoGeographicMovementAnalyticsApi";

import {
  activeGeographicSegmentForFrame,
  geographicSegmentSeekTarget,
} from "./videoGeographicMovementSynchronization";

function segment(start: number, end: number): GeographicMovementSegment {
  return {
    track_id: "track-1",
    video_asset_id: "video-1",
    start_observation_id: `observation-${start}`,
    end_observation_id: `observation-${end}`,
    start_frame_index: start,
    end_frame_index: end,
    start_frame_time_s: start / 10,
    end_frame_time_s: end / 10,
    elapsed_time_s: (end - start) / 10,
    start_location: {
      latitude_deg: 32.75,
      longitude_deg: -79.93,
      crs: "EPSG:4326",
    },
    end_location: {
      latitude_deg: 32.76,
      longitude_deg: -79.94,
      crs: "EPSG:4326",
    },
    distance_m: 10,
    speed_m_s: 5,
    initial_bearing_deg: 315,
    cumulative_distance_m: 10,
    speed_valid: true,
    invalid_reason: null,
  };
}

describe("geographic movement synchronization", () => {
  const first = segment(10, 20);
  const second = segment(20, 30);

  it("returns no active segment without a usable frame", () => {
    expect(activeGeographicSegmentForFrame([], 15)).toBeNull();
    expect(activeGeographicSegmentForFrame([first], null)).toBeNull();
    expect(activeGeographicSegmentForFrame([first], -1)).toBeNull();
    expect(activeGeographicSegmentForFrame([first], NaN)).toBeNull();
  });

  it("uses persisted segment frame boundaries", () => {
    expect(activeGeographicSegmentForFrame([first], 10)).toBe(first);
    expect(activeGeographicSegmentForFrame([first], 15)).toBe(first);
    expect(activeGeographicSegmentForFrame([first], 20)).toBe(first);
    expect(activeGeographicSegmentForFrame([first], 21)).toBeNull();
  });

  it("chooses the preceding segment at a shared endpoint", () => {
    expect(activeGeographicSegmentForFrame([first, second], 20)).toBe(first);

    expect(activeGeographicSegmentForFrame([first, second], 21)).toBe(second);
  });

  it("does not interpolate across observation gaps", () => {
    expect(
      activeGeographicSegmentForFrame([segment(10, 20), segment(30, 40)], 25),
    ).toBeNull();
  });

  it("uses persisted endpoint timing for segment navigation", () => {
    expect(geographicSegmentSeekTarget(first)).toEqual({
      frameIndex: 20,
      frameTimeSeconds: 2,
    });
  });

  it("rejects invalid seek endpoints", () => {
    expect(
      geographicSegmentSeekTarget({
        ...first,
        end_frame_time_s: NaN,
      }),
    ).toBeNull();

    expect(
      geographicSegmentSeekTarget({
        ...first,
        end_frame_index: -1,
      }),
    ).toBeNull();
  });

  it("accepts a valid zero-second endpoint", () => {
    expect(
      geographicSegmentSeekTarget({
        ...first,
        end_frame_index: 0,
        end_frame_time_s: 0,
      }),
    ).toEqual({
      frameIndex: 0,
      frameTimeSeconds: 0,
    });
  });
});
