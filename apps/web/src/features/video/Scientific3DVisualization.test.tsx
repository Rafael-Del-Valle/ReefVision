import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Scientific3DVisualization } from "./Scientific3DVisualization";
import type { MetricVideoDepth3DResult } from "./videoScienceApi";

const result: MetricVideoDepth3DResult = {
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
  depth_stack_shape: [3, 60, 100],
  decoded_frame_count: 3,
  metric_depth_sample_count: 5,
  skipped_depth_observations: 0,
  source_track_ids: ["track-1", "track-2"],
  analyzed_track_ids: ["track-1", "track-2"],
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
        observed_frame_count: 3,
        first_frame: 0,
        last_frame: 2,
        duration_seconds: 0.2,
        path_length_3d: 0.4,
        displacement_3d: 0.4,
        mean_speed_3d_per_second: 2,
        maximum_speed_3d_per_second: 2,
        mean_depth: 2.1,
        minimum_depth: 2,
        maximum_depth: 2.2,
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
            center_y_px: 16,
            x: -0.4,
            y: -0.28,
            z: 2.1,
            depth_confidence: 0.96,
          },
          {
            frame: 2,
            timestamp_seconds: 0.2,
            center_x_px: 40,
            center_y_px: 18,
            x: -0.2,
            y: -0.24,
            z: 2.2,
            depth_confidence: 0.94,
          },
        ],
      },
      {
        track_id: "track-2",
        track_number: 2,
        label_class_id: "fish",
        observed_frame_count: 2,
        first_frame: 0,
        last_frame: 1,
        duration_seconds: 0.1,
        path_length_3d: 0.1,
        displacement_3d: 0.1,
        mean_speed_3d_per_second: 1,
        maximum_speed_3d_per_second: 1,
        mean_depth: 1.5,
        minimum_depth: 1.45,
        maximum_depth: 1.55,
        skipped_gap_count: 0,
        points: [
          {
            frame: 0,
            timestamp_seconds: 0,
            center_x_px: 60,
            center_y_px: 30,
            x: 0.15,
            y: 0,
            z: 1.45,
            depth_confidence: 0.9,
          },
          {
            frame: 1,
            timestamp_seconds: 0.1,
            center_x_px: 63,
            center_y_px: 31,
            x: 0.2,
            y: 0.02,
            z: 1.55,
            depth_confidence: 0.91,
          },
        ],
      },
    ],
    warnings: [],
  },
  group_3d_frames: [
    {
      frame: 0,
      timestamp_seconds: 0,
      individual_count: 2,
      centroid_x: -0.225,
      centroid_y: -0.15,
      centroid_z: 1.725,
      mean_nearest_neighbor_distance: 0.82,
      mean_pairwise_distance: 0.82,
      bounding_box_volume: 0.05,
    },
    {
      frame: 1,
      timestamp_seconds: 0.1,
      individual_count: 2,
      centroid_x: -0.1,
      centroid_y: -0.13,
      centroid_z: 1.825,
      mean_nearest_neighbor_distance: 0.7,
      mean_pairwise_distance: 0.7,
      bounding_box_volume: 0.04,
    },
  ],
  warnings: [],
  scientific_provenance: {},
};

describe("Scientific3DVisualization", () => {
  it("renders depth, trajectory projections, and group metrics", () => {
    render(
      <Scientific3DVisualization
        result={result}
        classNames={new Map([["fish", "Fish"]])}
      />,
    );

    expect(
      screen.getByText("Depth and X/Y/Z trajectories"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "Track depth heat strip" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "Estimated depth over time" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "Top-view X Y trajectory" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "Side-view X Z trajectory" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "Front-view Y Z trajectory" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", {
        name: "3D nearest-neighbor distance over time",
      }),
    ).toBeInTheDocument();
  });

  it("switches tracks without changing the scientific validity tier", () => {
    render(
      <Scientific3DVisualization
        result={result}
        classNames={new Map([["fish", "Fish"]])}
      />,
    );

    fireEvent.change(screen.getByLabelText("Track"), {
      target: { value: "track-2" },
    });

    expect(screen.getByText("1.5000 m")).toBeInTheDocument();
    expect(screen.getByText("model estimated metric")).toBeInTheDocument();
    expect(
      screen.getByText(/requires independent underwater validation/i),
    ).toBeInTheDocument();
  });
});
