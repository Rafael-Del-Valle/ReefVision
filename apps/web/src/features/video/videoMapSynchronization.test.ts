import { describe, expect, it } from "vitest";

import type { GeoReferencedObservationSummary } from "./videoGeoreferencedObservationsApi";

import {
  activeObservationForFrame,
  frameIndexForVideoTime,
  videoTimeMatchesPendingSeek,
} from "./videoMapSynchronization";

function observation(
  id: string,
  frameIndex: number,
  trackId: string | null = "track-1",
): GeoReferencedObservationSummary {
  return {
    id,
    project_id: "project-1",
    video_asset_id: "video-1",
    track_id: trackId,
    detection_id: null,
    frame_index: frameIndex,
    frame_width_px: 1920,
    frame_height_px: 1080,
    frame_time_s: frameIndex / 30,
    bbox: {
      x_min: 10,
      y_min: 20,
      x_max: 100,
      y_max: 120,
    },
    representative_pixel: {
      x: 55,
      y: 70,
      method: "bbox_center",
    },
    location: {
      latitude_deg: 32.75 + frameIndex * 0.000001,
      longitude_deg: -79.93 + frameIndex * 0.000001,
      crs: "EPSG:4326",
    },
    uncertainty_available: false,
    method_version: "opencv-dji-enu-flat-wgs84-v1",
    created_at: "2026-09-23T12:00:00Z",
  };
}

describe("video/map synchronization", () => {
  it("converts video time to a clamped frame index", () => {
    expect(frameIndexForVideoTime(1.4, 30, 300)).toBe(42);

    expect(frameIndexForVideoTime(-1, 30, 300)).toBe(0);

    expect(frameIndexForVideoTime(100, 30, 300)).toBe(299);
  });

  it("rejects stale playback updates while a map seek is pending", () => {
    const pending = {
      sequence: 2,
      frameIndex: 42,
      frameTimeSeconds: 1.4,
    };

    expect(videoTimeMatchesPendingSeek(pending, 0.2, 30)).toBe(false);

    expect(videoTimeMatchesPendingSeek(pending, 1.4, 30)).toBe(true);

    expect(videoTimeMatchesPendingSeek(null, 0.2, 30)).toBe(true);
  });

  it("selects the nearest persisted observation without changing identity", () => {
    const first = observation("observation-10", 10, "track-A");

    const second = observation("observation-20", 20, "track-B");

    expect(activeObservationForFrame([first, second], 18)?.id).toBe(
      "observation-20",
    );

    expect(activeObservationForFrame([first, second], 15)?.id).toBe(
      "observation-10",
    );
  });

  it("supports an active untracked observation", () => {
    const untracked = observation("untracked", 5, null);

    expect(activeObservationForFrame([untracked], 5)?.track_id).toBeNull();
  });
});
