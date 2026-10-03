import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PoseVisualizationPanel } from "./PoseVisualizationPanel";
import * as poseVisualizationApi from "./poseVisualizationApi";

vi.mock("./poseVisualizationApi", async () => {
  const actual = await vi.importActual<typeof import("./poseVisualizationApi")>(
    "./poseVisualizationApi",
  );
  return {
    ...actual,
    getPoseVisualization: vi.fn(),
  };
});

const response: poseVisualizationApi.PoseVisualizationResponse = {
  schema_version: "pose-visualization-0001",
  parent_video_track_id: "track-1",
  source_track_revision: 4,
  video_id: "video-1",
  coordinate_space: "source_pixels",
  video_width_pixels: 200,
  video_height_pixels: 100,
  fps: 10,
  start_frame: 0,
  end_frame: 2,
  grid_rows: 1,
  grid_columns: 2,
  sampling_policy: "persisted_canonical_pose_keyframes",
  predicted_coordinate_policy: "exclude_occluded_predictions",
  identity_policy: "latest_resolved_temporal_association",
  identity_status: "current",
  identity_warning: null,
  sampled_frame_count: 3,
  spatial_sample_count: 5,
  observed_sample_count: 5,
  predicted_sample_count: 0,
  resolved_identity_sample_count: 5,
  unresolved_identity_sample_count: 0,
  excluded_missing_coordinate_count: 1,
  excluded_filter_count: 0,
  activity_segment_count: 3,
  cells: [
    {
      row: 0,
      column: 0,
      x_min_pixels: 0,
      y_min_pixels: 0,
      x_max_pixels: 100,
      y_max_pixels: 100,
      sample_count: 3,
      observed_sample_count: 3,
      predicted_sample_count: 0,
      confidence_sample_count: 3,
      mean_landmark_confidence: 0.9,
      sample_fraction: 0.6,
      occupied_sampled_frame_count: 3,
      occupied_sampled_frame_fraction: 1,
      unique_landmark_track_count: 1,
      movement_segment_count: 2,
      movement_distance_pixels: 20,
      movement_duration_seconds: 0.2,
      mean_speed_pixels_per_second: 100,
      maximum_speed_pixels_per_second: 110,
    },
    {
      row: 0,
      column: 1,
      x_min_pixels: 100,
      y_min_pixels: 0,
      x_max_pixels: 200,
      y_max_pixels: 100,
      sample_count: 2,
      observed_sample_count: 2,
      predicted_sample_count: 0,
      confidence_sample_count: 2,
      mean_landmark_confidence: 0.5,
      sample_fraction: 0.4,
      occupied_sampled_frame_count: 2,
      occupied_sampled_frame_fraction: 2 / 3,
      unique_landmark_track_count: 1,
      movement_segment_count: 1,
      movement_distance_pixels: 5,
      movement_duration_seconds: 0.1,
      mean_speed_pixels_per_second: 50,
      maximum_speed_pixels_per_second: 50,
    },
  ],
  provider_capabilities: {
    provider_name: "sleap_nn",
    keypoint_scores_persisted: true,
    native_confidence_maps_persisted: false,
    part_affinity_fields_persisted: false,
    raw_tensor_export_available: false,
    reason:
      "The current SLEAP-NN adapter persists canonical keypoint scores, but ReefVision does not retain native confidence-map or part-affinity-field tensors from inference.",
  },
  trajectories: [
    {
      landmark_track_id: "landmark-track-123456",
      semantic_label: "tentacle",
      lifecycle_state: "confirmed",
      path_length_pixels: 25,
      evaluated_seconds: 0.3,
      movement_segment_count: 3,
      points: [
        {
          frame_index: 0,
          time_s: 0,
          semantic_label: "tentacle",
          occurrence_index: 0,
          x_px: 20,
          y_px: 50,
          landmark_confidence: 0.95,
          visibility_state: "visible",
          observation_source: "model",
          coordinate_kind: "observed",
          landmark_track_id: "landmark-track-123456",
          association_state: "confirmed",
          verification_state: "unreviewed",
        },
        {
          frame_index: 1,
          time_s: 0.1,
          semantic_label: "tentacle",
          occurrence_index: 0,
          x_px: 30,
          y_px: 50,
          landmark_confidence: 0.93,
          visibility_state: "visible",
          observation_source: "model",
          coordinate_kind: "observed",
          landmark_track_id: "landmark-track-123456",
          association_state: "confirmed",
          verification_state: "unreviewed",
        },
      ],
    },
  ],
  paf: {
    available: false,
    provider_name: "sleap_nn",
    representation: "part_affinity_fields",
    persistence_state: "not_persisted",
    reason:
      "The current SLEAP-NN adapter persists canonical keypoints but does not persist raw part-affinity-field tensors.",
  },
};

function renderPanel(frameIndex = 1) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <PoseVisualizationPanel trackId="track-1" frameIndex={frameIndex} />
    </QueryClientProvider>,
  );
}

describe("PoseVisualizationPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(poseVisualizationApi.getPoseVisualization).mockResolvedValue(
      response,
    );
  });

  it("generates canonical confidence heatmaps with explicit filters and provenance", async () => {
    renderPanel();

    expect(
      screen.queryByTestId("pose-visualization-canvas"),
    ).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Pose visualization grid rows"), {
      target: { value: "12" },
    });
    fireEvent.change(screen.getByLabelText("Pose visualization grid columns"), {
      target: { value: "16" },
    });
    fireEvent.change(
      screen.getByLabelText("Pose visualization minimum confidence"),
      { target: { value: "0.4" } },
    );
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Include occlusion-predicted coordinates",
      }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Generate pose visualization" }),
    );

    await waitFor(() =>
      expect(poseVisualizationApi.getPoseVisualization).toHaveBeenCalledWith(
        "track-1",
        {
          grid_rows: 12,
          grid_columns: 16,
          include_predicted: true,
          include_uncertain: true,
          minimum_landmark_confidence: 0.4,
        },
      ),
    );

    expect(
      await screen.findByText("Mean landmark confidence (0–1)"),
    ).toBeInTheDocument();
    expect(screen.getAllByTestId("pose-heatmap-cell")).toHaveLength(2);
    expect(
      screen.getByText(/Coordinate space: source pixels/),
    ).toHaveTextContent("track revision 4");
    expect(
      screen.getByText("ReefVision does not synthesize PAFs from keypoints."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/canonical keypoint scores:/),
    ).toHaveTextContent("persisted");
    expect(
      screen.getByText(/native confidence maps:/),
    ).toHaveTextContent("not persisted");

    expect(
      screen.getByRole("link", { name: "Export visualization JSON" }),
    ).toHaveAttribute(
      "href",
      expect.stringContaining("format=json"),
    );
    expect(
      screen.getByRole("link", { name: "Export heatmap cells CSV" }),
    ).toHaveAttribute(
      "href",
      expect.stringContaining("grid_rows=12"),
    );
    expect(
      screen.getByRole("link", { name: "Export trajectories CSV" }),
    ).toHaveAttribute(
      "href",
      expect.stringContaining("format=trajectories_csv"),
    );
  });

  it("keeps occupancy, activity, and trajectory semantics distinct", async () => {
    renderPanel(1);
    fireEvent.click(
      screen.getByRole("button", { name: "Generate pose visualization" }),
    );
    await screen.findByText("Mean landmark confidence (0–1)");

    fireEvent.change(screen.getByLabelText("Pose visualization mode"), {
      target: { value: "occupancy" },
    });
    expect(
      screen.getByText("Occupied sampled-frame fraction (0–100%)"),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Pose visualization mode"), {
      target: { value: "activity" },
    });
    expect(
      screen.getByText("Mean landmark speed (0–100.00 px/s)"),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Pose visualization mode"), {
      target: { value: "trajectory" },
    });
    expect(
      screen.getByText("Persistent landmark trajectories (source pixels)"),
    ).toBeInTheDocument();
    expect(screen.getAllByTestId("pose-trajectory")).toHaveLength(1);
    expect(screen.getAllByTestId("pose-current-frame-point")).toHaveLength(1);
    expect(screen.queryByTestId("pose-heatmap-cell")).not.toBeInTheDocument();
  });

  it("surfaces stale temporal identity state instead of drawing trajectories", async () => {
    vi.mocked(poseVisualizationApi.getPoseVisualization).mockResolvedValue({
      ...response,
      identity_status: "stale",
      identity_warning:
        "Temporal identities predate the current video-track revision; rebuild them before interpreting trajectories or activity.",
      resolved_identity_sample_count: 0,
      unresolved_identity_sample_count: 5,
      activity_segment_count: 0,
      trajectories: [],
    });

    renderPanel();
    fireEvent.click(
      screen.getByRole("button", { name: "Generate pose visualization" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "rebuild them before interpreting trajectories",
    );
  });
});
