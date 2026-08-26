import { describe, expect, it } from "vitest";

import type { MetricVideoDepth3DResult } from "./videoScienceApi";
import {
  scientific3DGroupFramesCsv,
  scientific3DReportJson,
  scientific3DTrajectoriesCsv,
} from "./scientific3dReport";

const report: MetricVideoDepth3DResult = {
  schema_version: "video-metric-depth-3d-job-0001",
  stage: "complete",
  project_id: "project-1",
  video_id: "video-1",
  provider_id: "video_depth_anything",
  provider_version: "test",
  model_repo: "depth-anything/Metric-Video-Depth-Anything-Small",
  model_revision: "revision",
  model_sha256: "a".repeat(64),
  source_commit: "commit",
  device: "cuda",
  input_size_requested: 518,
  input_size_used: 392,
  max_res: 1280,
  depth_tier: "model_estimated_metric",
  physical_measurement_claim_allowed: false,
  underwater_validation_required: true,
  depth_stack_path: "projects/project-1/derived/depth.npz",
  depth_stack_sha256: "b".repeat(64),
  depth_stack_shape: [2, 60, 100],
  decoded_frame_count: 2,
  metric_depth_sample_count: 2,
  skipped_depth_observations: 0,
  source_track_ids: ["track-1"],
  analyzed_track_ids: ["track-1"],
  analytics: {
    schema_version: "video-depth-track-analytics-0001",
    video_id: "video-1",
    unit: "m",
    camera_intrinsics: {
      schema_version: "video-camera-intrinsics-0001",
      video_id: "video-1",
      fx_px: 100,
      fy_px: 100,
      cx_px: 50,
      cy_px: 30,
      method: "checkerboard",
      notes: null,
      video_revision: 2,
    },
    tracks: [
      {
        track_id: "track-1",
        track_number: 1,
        label_class_id: "fish",
        observed_frame_count: 2,
        first_frame: 0,
        last_frame: 1,
        duration_seconds: 0.1,
        path_length_3d: 0.2,
        displacement_3d: 0.2,
        mean_speed_3d_per_second: 2,
        maximum_speed_3d_per_second: 2,
        mean_depth: 2,
        minimum_depth: 2,
        maximum_depth: 2,
        skipped_gap_count: 0,
        points: [
          {
            frame: 0,
            timestamp_seconds: 0,
            center_x_px: 20,
            center_y_px: 15,
            x: -0.6,
            y: -0.3,
            z: 2,
            depth_confidence: 0.95,
          },
          {
            frame: 1,
            timestamp_seconds: 0.1,
            center_x_px: 30,
            center_y_px: 15,
            x: -0.4,
            y: -0.3,
            z: 2,
            depth_confidence: 0.96,
          },
        ],
      },
    ],
    warnings: [],
  },
  group_3d_frames: [
    {
      frame: 1,
      timestamp_seconds: 0.1,
      individual_count: 2,
      centroid_x: 0,
      centroid_y: 0,
      centroid_z: 2,
      mean_nearest_neighbor_distance: 0.4,
      mean_pairwise_distance: 0.4,
      bounding_box_volume: 0,
    },
  ],
  warnings: [],
  scientific_provenance: {
    depth_source: "Metric Video Depth Anything Small",
    depth_interpretation: "model_estimated_metric",
    track_depth_statistic: "central_bbox_median",
    track_depth_dispersion: "MAD-derived robust relative spread",
    physical_measurement_claim_allowed: false,
    reason: "Underwater validation required.",
  },
};

describe("Scientific 3D report serialization", () => {
  it("preserves per-frame XYZ and scientific validity provenance", () => {
    const csv = scientific3DTrajectoriesCsv(report);
    expect(csv).toContain("x_m,y_m,z_m,depth_confidence");
    expect(csv).toContain("model_estimated_metric,false");
    expect(csv.trimEnd().split("\n")).toHaveLength(3);
  });

  it("serializes group-level 3D spatial metrics", () => {
    const csv = scientific3DGroupFramesCsv(report);
    expect(csv).toContain("mean_nearest_neighbor_distance_m");
    expect(csv).toContain("bounding_box_volume_m3");
    expect(csv.trimEnd().split("\n")).toHaveLength(2);
  });

  it("serializes the complete immutable result payload", () => {
    const json = scientific3DReportJson(report);
    expect(json.endsWith("\n")).toBe(true);
    expect(JSON.parse(json)).toEqual(report);
  });
});
