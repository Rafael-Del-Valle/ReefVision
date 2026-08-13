import { describe, expect, it } from "vitest";

import type { VideoOccupancyAnalytics } from "./videoOccupancyApi";
import {
  occupancyCellsCsv,
  occupancyReportJson,
  occupancyTracksCsv,
} from "./videoOccupancyReport";

const report: VideoOccupancyAnalytics = {
  schema_version: "video-occupancy-0001",
  video_id: "video-1",
  track_ids: ["track-a", "track-b"],
  start_frame: 0,
  end_frame: 2,
  grid_rows: 2,
  grid_columns: 2,
  video_width_pixels: 100,
  video_height_pixels: 100,
  trajectory_policy: "configured_track_interpolation",
  frames_with_tracks: 3,
  track_frame_observations: 6,
  total_track_seconds: 0.6,
  cells: [
    {
      row: 0,
      column: 0,
      x_min_pixels: 0,
      y_min_pixels: 0,
      x_max_pixels: 50,
      y_max_pixels: 50,
      observation_count: 3,
      observation_fraction: 0.5,
      occupied_frame_count: 3,
      occupied_frame_fraction: 1,
      unique_track_count: 1,
      dwell_seconds: 0.3,
    },
  ],
  per_track: [
    {
      track_id: "track-a",
      track_number: 1,
      label_class_id: "fish",
      observation_count: 3,
      dwell_seconds: 0.3,
      occupied_cell_count: 1,
      most_occupied_row: 0,
      most_occupied_column: 0,
      most_occupied_fraction: 1,
    },
  ],
};

describe("occupancy report serialization", () => {
  it("serializes cell-level fish-frame occupancy provenance", () => {
    const csv = occupancyCellsCsv(report);
    expect(csv).toContain("observation_fraction");
    expect(csv).toContain("occupied_frame_fraction");
    expect(csv).toContain("configured_track_interpolation");
    expect(csv.trimEnd().split("\n")).toHaveLength(2);
  });

  it("serializes per-track dominant cell summaries", () => {
    const csv = occupancyTracksCsv(report);
    expect(csv).toContain("most_occupied_fraction");
    expect(csv).toContain(",track-a,1,fish,3,0.3,1,0,0,1,");
  });

  it("serializes the exact JSON payload with a trailing newline", () => {
    const json = occupancyReportJson(report);
    expect(json.endsWith("\n")).toBe(true);
    expect(JSON.parse(json)).toEqual(report);
  });
});
