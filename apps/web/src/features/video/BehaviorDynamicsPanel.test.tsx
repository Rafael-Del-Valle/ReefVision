import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BehaviorDynamicsPanel } from "./BehaviorDynamicsPanel";
import * as api from "./behaviorDynamicsApi";

vi.mock("./behaviorDynamicsApi", async () => {
  const actual =
    await vi.importActual<typeof import("./behaviorDynamicsApi")>(
      "./behaviorDynamicsApi",
    );
  return {
    ...actual,
    getBehaviorEthograms: vi.fn(),
    getBehaviorBouts: vi.fn(),
    getBehaviorDynamics: vi.fn(),
    getBehaviorModels: vi.fn(),
    getBehaviorPredictions: vi.fn(),
    createBehaviorEthogram: vi.fn(),
    createBehaviorBout: vi.fn(),
    trainBehaviorModel: vi.fn(),
    runBehaviorPredictions: vi.fn(),
    reviewBehaviorPrediction: vi.fn(),
  };
});

const ethogram: api.BehaviorEthogram = {
  id: "ethogram-1",
  ethogram_series_id: "ethogram-series-1",
  project_id: "project-1",
  revision: 1,
  supersedes_revision_id: null,
  name: "Locomotion",
  description: null,
  definition_sha256: "a".repeat(64),
  created_by: "local_user",
  created_at: "2026-10-03T00:00:00Z",
  states: [
    {
      id: "rest-state",
      ethogram_revision_id: "ethogram-1",
      code: "rest",
      label: "Rest",
      channel: "locomotion",
      description: null,
      sort_order: 0,
    },
    {
      id: "swim-state",
      ethogram_revision_id: "ethogram-1",
      code: "swim",
      label: "Swimming",
      channel: "locomotion",
      description: null,
      sort_order: 1,
    },
  ],
};

const model: api.BehaviorModel = {
  id: "behavior-model-1",
  project_id: "project-1",
  ethogram_revision_id: "ethogram-1",
  channel: "locomotion",
  display_name: "Transparent locomotion model",
  algorithm: "standardized_nearest_centroid",
  algorithm_version: "0001",
  feature_set_version: "reefvision-behavior-features-0001",
  feature_preset: "track_only",
  feature_names: ["track.mean_speed_pixels_per_second"],
  feature_request: {},
  scaler: {},
  centroids: {},
  class_counts: { "rest-state": 2, "swim-state": 2 },
  training_track_ids: ["track-training"],
  training_bout_ids: ["bout-1", "bout-2", "bout-3", "bout-4"],
  training_sample_count: 4,
  training_manifest_sha256: "b".repeat(64),
  created_by: "local_user",
  created_at: "2026-10-03T00:00:00Z",
};

const prediction: api.BehaviorPrediction = {
  id: "prediction-1",
  video_track_id: "track-1",
  model_id: "behavior-model-1",
  ethogram_revision_id: "ethogram-1",
  behavior_state_id: "swim-state",
  behavior_code: "swim",
  behavior_label: "Swimming",
  channel: "locomotion",
  start_frame: 30,
  end_frame: 59,
  prediction_score: 0.82,
  score_semantics: "normalized_inverse_distance_not_calibrated",
  scores: {},
  feature_vector: {},
  feature_parameters_sha256: "c".repeat(64),
  source_track_revision: 1,
  stale_against_track: false,
  review_status: "pending",
  accepted_bout_series_id: null,
  reviewed_at: null,
  reviewed_by: null,
  created_at: "2026-10-03T00:00:00Z",
};

function renderPanel(onFrameChange = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return {
    onFrameChange,
    ...render(
      <QueryClientProvider client={queryClient}>
        <BehaviorDynamicsPanel
          projectId="project-1"
          trackId="track-1"
          frameIndex={12}
          onFrameChange={onFrameChange}
        />
      </QueryClientProvider>,
    ),
  };
}

describe("BehaviorDynamicsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getBehaviorEthograms).mockResolvedValue([ethogram]);
    vi.mocked(api.getBehaviorBouts).mockResolvedValue([]);
    vi.mocked(api.getBehaviorDynamics).mockResolvedValue({
      schema_version: "behavior-dynamics-0001",
      track_id: "track-1",
      video_id: "video-1",
      track_number: 1,
      ethogram_revision_id: "ethogram-1",
      ethogram_definition_sha256: ethogram.definition_sha256,
      start_frame: 0,
      end_frame: 99,
      fps: 30,
      transition_policy: "adjacent-labeled-bouts-only",
      interval_policy: "inclusive-frame-intervals",
      annotation_policy: "verified_only",
      excluded_unreviewed_bout_count: 0,
      provenance_status: "current",
      provenance_warning: null,
      stale_bout_count: 0,
      channels: [
        {
          channel: "locomotion",
          evaluated_frames: 100,
          evaluated_seconds: 100 / 30,
          labeled_frames: 60,
          labeled_seconds: 2,
          unlabeled_frames: 40,
          unlabeled_seconds: 40 / 30,
          coverage_fraction: 0.6,
          states: [
            {
              behavior_state_id: "rest-state",
              behavior_code: "rest",
              behavior_label: "Rest",
              channel: "locomotion",
              bout_count: 2,
              dwell_frames: 30,
              dwell_seconds: 1,
              fraction_of_evaluated_time: 0.3,
              fraction_of_labeled_time: 0.5,
              mean_bout_seconds: 0.5,
              maximum_bout_seconds: 0.6,
            },
          ],
          transitions: [
            {
              channel: "locomotion",
              from_behavior_state_id: "rest-state",
              from_behavior_code: "rest",
              to_behavior_state_id: "swim-state",
              to_behavior_code: "swim",
              count: 1,
              probability_from_state: 0.5,
            },
          ],
        },
      ],
    });
    vi.mocked(api.getBehaviorModels).mockResolvedValue([model]);
    vi.mocked(api.getBehaviorPredictions).mockResolvedValue([prediction]);
    vi.mocked(api.reviewBehaviorPrediction).mockResolvedValue({
      ...prediction,
      review_status: "edited_and_accepted",
      accepted_bout_series_id: "accepted-bout-series",
    });
  });

  it("shows scientific dynamics, provenance, model semantics, and exports", async () => {
    renderPanel();

    await screen.findByText(/Definition a{12}/);
    expect(screen.getByText(/60.0% labeled/)).toBeInTheDocument();
    expect(screen.getByText(/rest → swim: 1 · 50.0%/)).toBeInTheDocument();
    expect(
      screen.getByText(/normalized inverse distance, not calibrated/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/standardized_nearest_centroid 0001/),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("link", { name: "Export behavior JSON" }),
    ).toHaveAttribute("href", expect.stringContaining("format=json"));
    expect(
      screen.getByRole("link", { name: "Export canonical bouts CSV" }),
    ).toHaveAttribute("href", expect.stringContaining("format=bouts_csv"));
  });

  it("passes explicit scientist corrections to edit-and-accept", async () => {
    renderPanel();

    await screen.findByText(/Swimming · frames 30–59/);
    fireEvent.change(
      screen.getByLabelText("Corrected behavior state prediction-1"),
      { target: { value: "rest-state" } },
    );
    fireEvent.change(
      screen.getByLabelText("Corrected behavior start prediction-1"),
      { target: { value: "31" } },
    );
    fireEvent.change(
      screen.getByLabelText("Corrected behavior end prediction-1"),
      { target: { value: "58" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Edit & accept" }));

    await waitFor(() =>
      expect(api.reviewBehaviorPrediction).toHaveBeenCalledWith(
        "prediction-1",
        {
          action: "edit_and_accept",
          behavior_state_id: "rest-state",
          start_frame: 31,
          end_frame: 58,
        },
      ),
    );
  });

  it("creates verified manual bouts at the current frame", async () => {
    vi.mocked(api.createBehaviorBout).mockResolvedValue({
      id: "bout-new",
      bout_series_id: "bout-series-new",
      revision: 1,
      supersedes_bout_id: null,
      video_track_id: "track-1",
      ethogram_revision_id: "ethogram-1",
      behavior_state_id: "rest-state",
      behavior_code: "rest",
      behavior_label: "Rest",
      channel: "locomotion",
      start_frame: 12,
      end_frame: 12,
      start_time_seconds: 0.4,
      end_time_seconds: 13 / 30,
      duration_seconds: 1 / 30,
      source: "manual",
      confidence: null,
      review_status: "verified",
      source_track_revision: 1,
      stale_against_track: false,
      source_behavior_classifier_id: null,
      source_behavior_prediction_id: null,
      revision_reason: "manual_annotation",
      note: null,
      created_by: "local_user",
      created_at: "2026-10-03T00:00:00Z",
    });
    renderPanel();

    await screen.findByText(/Definition a{12}/);
    fireEvent.click(
      screen.getByRole("button", { name: "Add verified manual bout" }),
    );

    await waitFor(() =>
      expect(api.createBehaviorBout).toHaveBeenCalledWith("track-1", {
        ethogram_revision_id: "ethogram-1",
        behavior_state_id: "rest-state",
        start_frame: 12,
        end_frame: 12,
        source: "manual",
      }),
    );
  });
});
