import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PoseActiveLearningPanel } from "./PoseActiveLearningPanel";
import * as api from "./poseActiveLearningApi";

vi.mock("./poseActiveLearningApi", async () => {
  const actual = await vi.importActual<
    typeof import("./poseActiveLearningApi")
  >("./poseActiveLearningApi");
  return {
    ...actual,
    createPoseActiveLearningRound: vi.fn(),
    createPoseTrainingDataset: vi.fn(),
    getPoseActiveLearningRounds: vi.fn(),
    getPoseActiveLearningCandidates: vi.fn(),
    reviewPoseActiveLearningCandidate: vi.fn(),
  };
});

const round: api.PoseActiveLearningRound = {
  id: "pose-round-1",
  project_id: "project-1",
  video_id: "video-1",
  name: "Tentacle uncertainty review",
  status: "open",
  selection_unit: "clip",
  requested_size: 5,
  selected_count: 1,
  clip_radius_frames: 3,
  minimum_frame_spacing: 5,
  model_ids_json: [],
  scoring_config_json: {},
  selection_manifest_json: {},
  selection_sha256: "a".repeat(64),
  created_by: "local_user",
  created_at: "2026-10-03T00:00:00Z",
  completed_at: null,
};

const trainingDataset: api.PoseTrainingDataset = {
  id: "pose-dataset-1",
  project_id: "project-1",
  source_round_id: "pose-round-1",
  name: "Verified pose dataset",
  status: "complete",
  schema_version: "pose-training-dataset-0001",
  pose_schema_id: "jellyfish",
  pose_schema_revision: 3,
  pose_schema_content_hash: "c".repeat(64),
  source_selection_sha256: "a".repeat(64),
  source_retraining_manifest_sha256: "d".repeat(64),
  manifest_json: {},
  manifest_sha256: "e".repeat(64),
  item_count: 1,
  created_by: "local_user",
  created_at: "2026-10-03T00:00:00Z",
};

const candidate: api.PoseActiveLearningCandidate = {
  id: "candidate-1",
  round_id: round.id,
  video_track_id: "track-1",
  focus_frame: 42,
  frame_start: 39,
  frame_end: 45,
  acquisition_score: 0.82,
  score_components_json: {
    low_landmark_confidence: 0.7,
    visibility_uncertainty: 0.3,
    association_uncertainty: 0.6,
    repeated_landmark_ambiguity: 0.8,
    identity_break_signal: 1,
    motion_anomaly: 0.2,
    model_disagreement: 0.55,
  },
  reason_codes_json: [
    "low_landmark_confidence",
    "repeated_landmark_ambiguity",
    "identity_break_or_nearby_break",
  ],
  pose_schema_id: "jellyfish",
  pose_schema_revision: 3,
  source_track_revision: 7,
  source_model_ids_json: [],
  source_job_ids_json: [],
  provenance_json: {},
  provenance_sha256: "b".repeat(64),
  review_status: "pending",
  review_started_track_revision: null,
  verified_track_revision: null,
  verified_pose_sha256: null,
  correction_id: null,
  reviewed_by: null,
  reviewed_at: null,
  created_at: "2026-10-03T00:00:00Z",
  review_target: {
    workspace: "pose_annotation_editor",
    video_id: "video-1",
    video_track_id: "track-1",
    focus_frame: 42,
    frame_start: 39,
    frame_end: 45,
    pose_schema_id: "jellyfish",
    pose_schema_revision: 3,
  },
};

function renderPanel(onOpenCandidate = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={client}>
      <PoseActiveLearningPanel
        projectId="project-1"
        videoId="video-1"
        onOpenCandidate={onOpenCandidate}
      />
    </QueryClientProvider>,
  );

  return onOpenCandidate;
}

describe("PoseActiveLearningPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.createPoseActiveLearningRound).mockResolvedValue(round);
    vi.mocked(api.createPoseTrainingDataset).mockResolvedValue(trainingDataset);
    vi.mocked(api.getPoseActiveLearningRounds).mockResolvedValue([round]);
    vi.mocked(api.getPoseActiveLearningCandidates).mockResolvedValue([
      candidate,
    ]);
    vi.mocked(api.reviewPoseActiveLearningCandidate).mockResolvedValue({
      ...candidate,
      review_status: "in_review",
      review_started_track_revision: 7,
    });
  });

  it("shows explainable pose uncertainty and opens the Pose Annotation Editor handoff", async () => {
    const onOpenCandidate = renderPanel();

    const candidateCard = await screen.findByTestId(
      "pose-al-candidate-candidate-1",
    );

    expect(candidateCard).toHaveTextContent(/Frame\s+42/);
    expect(candidateCard).toHaveTextContent(/uncertainty\s+82\.0%/);

    expect(candidateCard).toHaveTextContent(/repeated[- ]landmark ambiguity/i);

    expect(candidateCard).toHaveTextContent(/identity-break signal\s+100\.0%/i);
    expect(candidateCard).toHaveTextContent(/Model disagreement:\s+55\.0%/i);
    expect(candidateCard).toHaveTextContent(
      /Heatmap entropy:\s+not exposed by this provider/i,
    );
    expect(candidateCard).toHaveTextContent(
      /PAF ambiguity:\s+not exposed by this provider/i,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "Review in Pose Annotation Editor",
      }),
    );

    await waitFor(() =>
      expect(api.reviewPoseActiveLearningCandidate).toHaveBeenCalledWith(
        "candidate-1",
        {
          action: "start_review",
          reviewed_by: "local_user",
        },
      ),
    );

    await waitFor(() =>
      expect(onOpenCandidate).toHaveBeenCalledWith(
        expect.objectContaining({
          id: "candidate-1",
          review_status: "in_review",
        }),
      ),
    );
  });

  it("creates a diversity-balanced acquisition round", async () => {
    renderPanel();

    await screen.findByTestId("pose-al-candidate-candidate-1");

    fireEvent.change(
      screen.getByLabelText("Pose Active Learning acquisition balance"),
      {
        target: {
          value: "uncertainty_diverse",
        },
      },
    );

    const diversityInput = screen.getByLabelText(
      "Pose Active Learning diversity weight",
    );

    expect(diversityInput).toBeInTheDocument();

    fireEvent.change(diversityInput, {
      target: {
        value: "0.35",
      },
    });

    fireEvent.click(
      screen.getByRole("button", {
        name: "Create pose acquisition round",
      }),
    );

    await waitFor(() =>
      expect(api.createPoseActiveLearningRound).toHaveBeenCalledWith(
        "project-1",
        expect.objectContaining({
          selection_mode: "uncertainty_diverse",
          diversity_weight: 0.35,
        }),
      ),
    );
  });

  it("freezes a completed reviewed round into immutable training truth", async () => {
    const completedRound: api.PoseActiveLearningRound = {
      ...round,
      status: "complete",
      completed_at: "2026-10-03T01:00:00Z",
    };

    vi.mocked(api.getPoseActiveLearningRounds).mockResolvedValue([
      completedRound,
    ]);

    vi.mocked(api.getPoseActiveLearningCandidates).mockResolvedValue([
      {
        ...candidate,
        review_status: "verified",
        verified_track_revision: 8,
        verified_pose_sha256: "f".repeat(64),
        correction_id: "correction-1",
        reviewed_by: "scientist",
        reviewed_at: "2026-10-03T01:00:00Z",
      },
    ]);

    renderPanel();

    const freezeButton = await screen.findByRole("button", {
      name: "Freeze verified training dataset",
    });

    expect(freezeButton).toBeEnabled();

    fireEvent.click(freezeButton);

    await waitFor(() =>
      expect(api.createPoseTrainingDataset).toHaveBeenCalledWith(
        "pose-round-1",
        {
          created_by: "local_user",
        },
      ),
    );

    const frozen = await screen.findByTestId("pose-training-dataset");

    expect(frozen).toHaveTextContent(/Immutable pose dataset/i);
    expect(frozen).toHaveTextContent(/1 verified pose/i);
    expect(
      screen.getByRole("link", {
        name: /Download immutable ReefVision pose dataset/i,
      }),
    ).toBeInTheDocument();
  });
});
