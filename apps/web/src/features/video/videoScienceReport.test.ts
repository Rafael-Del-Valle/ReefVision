import { describe, expect, it } from "vitest";

import type { VideoTrackActivity } from "./videoActivityApi";
import type { SchoolingAnalytics, VideoSpatialCalibration } from "./videoScienceApi";
import {
  activityBoutsCsv,
  activityIntervalsCsv,
  activityReportJson,
  activitySummaryCsv,
  schoolingFramesCsv,
  schoolingReportJson,
  schoolingSummaryCsv,
} from "./videoScienceReport";

const calibration: VideoSpatialCalibration = {
  schema_version: "video-spatial-calibration-0001",
  video_id: "video-1",
  unit: "cm",
  reference_distance: 10,
  reference_pixels: 100,
  pixels_per_unit: 10,
  units_per_pixel: 0.1,
  method: 'ruler, "fixed"',
  reference_label: "10 cm ruler",
  notes: null,
  calibration_revision: 2,
  calibration_updated_at: "2026-08-12T22:00:00+00:00",
  video_revision: 4,
};

const schooling: SchoolingAnalytics = {
  schema_version: "video-schooling-analytics-0001",
  video_id: "video-1",
  track_ids: ["track-a", "track-b"],
  start_frame: 0,
  end_frame: 2,
  trajectory_policy: "configured_track_interpolation",
  frames_evaluated: 2,
  mean_group_size: 2,
  mean_pairwise_distance_pixels: 10,
  mean_nearest_neighbor_distance_pixels: 10,
  mean_distance_to_centroid_pixels: 5,
  mean_pairwise_distance: 1,
  mean_nearest_neighbor_distance: 1,
  mean_distance_to_centroid: 0.5,
  mean_speed_pixels_per_second: 100,
  mean_speed_per_second: 10,
  mean_polarization: 1,
  distance_unit: "cm",
  calibration,
  frames: [
    {
      frame: 1,
      timestamp_seconds: 0.1,
      active_track_count: 2,
      mean_pairwise_distance_pixels: 10,
      mean_nearest_neighbor_distance_pixels: 10,
      mean_distance_to_centroid_pixels: 5,
      mean_pairwise_distance: 1,
      mean_nearest_neighbor_distance: 1,
      mean_distance_to_centroid: 0.5,
      mean_speed_pixels_per_second: 100,
      mean_speed_per_second: 10,
      polarization: 1,
    },
  ],
};

const activity: VideoTrackActivity = {
  schema_version: "video-track-activity-0001",
  track_id: "track-a",
  video_id: "video-1",
  track_number: 1,
  label_class_id: "fish",
  trajectory_policy: "configured_track_interpolation",
  start_frame: 0,
  end_frame: 2,
  distance_unit: "cm",
  speed_threshold_per_second: 5,
  speed_threshold_pixels_per_second: 50,
  minimum_active_bout_seconds: 0.1,
  evaluated_seconds: 0.2,
  active_seconds: 0.1,
  rest_seconds: 0.1,
  active_fraction: 0.5,
  active_bout_count: 1,
  rest_bout_count: 1,
  mean_active_bout_seconds: 0.1,
  maximum_active_bout_seconds: 0.1,
  mean_rest_bout_seconds: 0.1,
  mean_active_speed_per_second: 10,
  maximum_speed_per_second: 10,
  calibration,
  intervals: [
    {
      start_frame: 0,
      end_frame: 1,
      start_time_seconds: 0,
      end_time_seconds: 0.1,
      duration_seconds: 0.1,
      distance_pixels: 0,
      distance: 0,
      speed_pixels_per_second: 0,
      speed_per_second: 0,
      active: false,
    },
    {
      start_frame: 1,
      end_frame: 2,
      start_time_seconds: 0.1,
      end_time_seconds: 0.2,
      duration_seconds: 0.1,
      distance_pixels: 10,
      distance: 1,
      speed_pixels_per_second: 100,
      speed_per_second: 10,
      active: true,
    },
  ],
  bouts: [
    {
      state: "rest",
      start_frame: 0,
      end_frame: 1,
      start_time_seconds: 0,
      end_time_seconds: 0.1,
      duration_seconds: 0.1,
      interval_count: 1,
    },
    {
      state: "active",
      start_frame: 1,
      end_frame: 2,
      start_time_seconds: 0.1,
      end_time_seconds: 0.2,
      duration_seconds: 0.1,
      interval_count: 1,
    },
  ],
};

describe("video science report serialization", () => {
  it("preserves schooling calibration provenance in summary and frame CSV", () => {
    const summary = schoolingSummaryCsv(schooling);
    expect(summary).toContain("calibration_revision,calibration_updated_at");
    expect(summary).toContain(",2,2026-08-12T22:00:00+00:00,");
    expect(summary).toContain('"ruler, ""fixed"""');

    const frames = schoolingFramesCsv(schooling);
    expect(frames).toContain("frame,timestamp_seconds,active_track_count");
    expect(frames).toContain(",1,0.1,2,");
    expect(frames.trimEnd().split("\n")).toHaveLength(2);
  });

  it("preserves activity thresholds and calibration provenance in CSV", () => {
    const summary = activitySummaryCsv(activity);
    expect(summary).toContain("speed_threshold_per_second");
    expect(summary).toContain("minimum_active_bout_seconds");
    expect(summary).toContain("calibration_revision");
    expect(summary).toContain(",5,50,0.1,cm,2,");

    const intervals = activityIntervalsCsv(activity);
    expect(intervals.trimEnd().split("\n")).toHaveLength(3);
    expect(intervals).toContain(",false,cm,5,2");
    expect(intervals).toContain(",true,cm,5,2");

    const bouts = activityBoutsCsv(activity);
    expect(bouts.trimEnd().split("\n")).toHaveLength(3);
    expect(bouts).toContain(",rest,0,1,");
    expect(bouts).toContain(",active,1,2,");
  });

  it("serializes exact JSON payloads with a trailing newline", () => {
    expect(JSON.parse(schoolingReportJson(schooling))).toEqual(schooling);
    expect(JSON.parse(activityReportJson(activity))).toEqual(activity);
    expect(schoolingReportJson(schooling).endsWith("\n")).toBe(true);
    expect(activityReportJson(activity).endsWith("\n")).toBe(true);
  });
});
