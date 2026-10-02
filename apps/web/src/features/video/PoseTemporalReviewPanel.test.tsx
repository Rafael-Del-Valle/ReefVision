import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PoseTemporalReviewPanel } from "./PoseTemporalReviewPanel";
import * as poseApi from "./poseTemporalApi";

vi.mock("./poseTemporalApi", async () => {
  const actual =
    await vi.importActual<typeof import("./poseTemporalApi")>(
      "./poseTemporalApi",
    );
  return {
    ...actual,
    getTemporalPoseSummary: vi.fn(),
    buildTemporalPoseAssociations: vi.fn(),
    correctTemporalPoseAssociation: vi.fn(),
    createTemporalPoseIdentityBreak: vi.fn(),
    temporalPoseExportUrl: vi.fn(
      (trackId: string, format: string) =>
        "/pose-export/" + trackId + "." + format,
    ),
  };
});

const track = {
  id: "landmark-track-1",
  parent_video_track_id: "track-1",
  pose_schema_id: "schema-1",
  pose_schema_revision: 1,
  semantic_label: "tentacle",
  lifecycle_state: "confirmed",
  first_frame: 10,
  last_frame: 11,
  origin: "tracker",
  source_model_id: "model-1",
  source_job_id: "job-1",
  association_algorithm: "reefvision-temporal-pose",
  association_algorithm_version: "0001",
  association_parameters_json: {},
  association_parameters_hash: "a".repeat(64),
  created_at: "2026-10-02T00:00:00Z",
  terminated_at: null,
};

const observation = {
  id: "observation-1",
  observation_series_id: "series-1",
  revision: 1,
  supersedes_observation_id: null,
  parent_video_track_id: "track-1",
  frame_index: 10,
  time_s: 1,
  pose_schema_id: "schema-1",
  pose_schema_revision: 1,
  semantic_label: "tentacle",
  occurrence_index: 0,
  observed_x_px: 40,
  observed_y_px: 50,
  predicted_x_px: null,
  predicted_y_px: null,
  landmark_confidence: 0.93,
  visibility_state: "visible" as const,
  observation_source: "model",
  source_model_id: "model-1",
  source_job_id: "job-1",
  created_at: "2026-10-02T00:00:00Z",
};

const unresolvedDecision = {
  id: "decision-1",
  observation_id: observation.id,
  decision_revision: 1,
  supersedes_decision_id: null,
  selected_landmark_track_id: null,
  previous_observation_id: null,
  association_state: "unresolved" as const,
  association_confidence: null,
  verification_state: "unreviewed",
  association_source: "tracker",
  candidate_margin: 0.01,
  total_cost: 0.1,
  cost_breakdown_json: { motion: 0.1 },
  algorithm: "reefvision-temporal-pose",
  algorithm_version: "0001",
  parameters_hash: "a".repeat(64),
  created_at: "2026-10-02T00:00:00Z",
};

function renderPanel(frameIndex = 10, onFrameChange = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <PoseTemporalReviewPanel
        trackId="track-1"
        frameIndex={frameIndex}
        onFrameChange={onFrameChange}
      />
    </QueryClientProvider>,
  );
  return { onFrameChange };
}

describe("PoseTemporalReviewPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(poseApi.correctTemporalPoseAssociation).mockResolvedValue({
      ...unresolvedDecision,
      decision_revision: 2,
      selected_landmark_track_id: track.id,
      association_state: "confirmed",
      association_source: "human",
      verification_state: "human_corrected",
    });
    vi.mocked(poseApi.createTemporalPoseIdentityBreak).mockResolvedValue({
      id: "break-1",
      parent_video_track_id: "track-1",
      predecessor_landmark_track_id: track.id,
      successor_landmark_track_id: null,
      break_after_frame: 10,
      successor_start_frame: null,
      reason: "ambiguous_crossing",
      decision_confidence: null,
      source: "human",
      human_verified: true,
      correction_id: "correction-1",
      created_at: "2026-10-02T00:00:00Z",
    });
  });

  it("builds temporal identities when canonical records do not exist", async () => {
    vi.mocked(poseApi.getTemporalPoseSummary).mockResolvedValue({
      schema_version: "pose-temporal-summary-0001",
      parent_video_track_id: "track-1",
      landmark_tracks: [],
      observations: [],
      association_decisions: [],
      identity_breaks: [],
      corrections: [],
    });
    vi.mocked(poseApi.buildTemporalPoseAssociations).mockResolvedValue({
      schema_version: "pose-temporal-build-0001",
      parent_video_track_id: "track-1",
      created_landmark_tracks: 2,
      created_observations: 12,
      created_association_decisions: 12,
      unresolved_associations: 1,
      identity_breaks: 0,
    });

    renderPanel();
    const build = await screen.findByRole("button", {
      name: "Build temporal identities",
    });
    fireEvent.click(build);

    await waitFor(() =>
      expect(poseApi.buildTemporalPoseAssociations).toHaveBeenCalledWith(
        "track-1",
        { replace_existing: false },
      ),
    );
    expect(
      await screen.findByText(
        "Built 2 landmark tracklets; 1 associations need review.",
      ),
    ).toBeInTheDocument();
  });

  it("reviews unresolved repeated landmarks and navigates pose frames", async () => {
    const nextObservation = {
      ...observation,
      id: "observation-2",
      observation_series_id: "series-2",
      frame_index: 11,
      time_s: 1.1,
      observed_x_px: 42,
    };
    vi.mocked(poseApi.getTemporalPoseSummary).mockResolvedValue({
      schema_version: "pose-temporal-summary-0001",
      parent_video_track_id: "track-1",
      landmark_tracks: [track],
      observations: [observation, nextObservation],
      association_decisions: [
        unresolvedDecision,
        {
          ...unresolvedDecision,
          id: "decision-2",
          observation_id: nextObservation.id,
          selected_landmark_track_id: track.id,
          association_state: "confirmed",
          association_confidence: 0.91,
        },
      ],
      identity_breaks: [],
      corrections: [],
    });

    const { onFrameChange } = renderPanel();

    expect(
      await screen.findByText("Unresolved associations"),
    ).toBeInTheDocument();
    expect(screen.getByText("unresolved · association confidence n/a · unreviewed"))
      .toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next pose frame" }));
    expect(onFrameChange).toHaveBeenCalledWith(11);

    const selector = screen.getByLabelText("Temporal identity for tentacle 1");
    fireEvent.change(selector, { target: { value: track.id } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm identity" }));

    await waitFor(() =>
      expect(poseApi.correctTemporalPoseAssociation).toHaveBeenCalledWith(
        observation.id,
        expect.objectContaining({
          selected_landmark_track_id: track.id,
          association_state: "confirmed",
        }),
      ),
    );

    expect(screen.getByRole("link", { name: "Export pose CSV" })).toHaveAttribute(
      "href",
      "/pose-export/track-1.csv",
    );
    expect(
      screen.getByRole("link", { name: "Export pose audit JSON" }),
    ).toHaveAttribute("href", "/pose-export/track-1.json");
  });
});
