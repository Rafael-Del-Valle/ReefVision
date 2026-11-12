import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PoseIdentityReviewPanel } from "./PoseIdentityReviewPanel";
import * as identityApi from "./poseIdentityTrackingApi";
import type { VideoTrackRecord } from "./videoApi";

vi.mock("./poseIdentityTrackingApi", () => ({
  listPoseIdentityRuns: vi.fn(),
  createPoseIdentityRun: vi.fn(),
  getPoseIdentityIdentities: vi.fn(),
  getPoseIdentityObservations: vi.fn(),
  getPoseIdentityDecisions: vi.fn(),
  getPoseIdentityReviewQueue: vi.fn(),
  getPoseIdentityCorrections: vi.fn(),
  createPoseIdentityCorrection: vi.fn(),
  cancelPoseIdentityJob: vi.fn(),
  poseIdentityExportUrl: vi.fn(
    (runId: string, format: string) => `/identity/${runId}.${format}`,
  ),
}));

const run = {
  id: "run-1",
  project_id: "project-1",
  video_id: "video-1",
  source_model_id: "model-1",
  source_job_id: "job-1",
  pose_schema_id: "schema-1",
  pose_schema_revision: 2,
  pose_schema_content_hash: "a".repeat(64),
  algorithm: "reefpose-geometric-motion-association",
  algorithm_version: "1.0.0",
  parameters_json: { low_confidence_threshold: 0.6 },
  parameters_sha256: "b".repeat(64),
  input_manifest_sha256: "c".repeat(64),
  source_coordinate_space: "source_pixels",
  source_width: 320,
  source_height: 180,
  status: "completed",
  progress_json: { stage: "completed", current: 2, total: 2 },
  error_json: null,
  revision: 1,
  created_at: "2026-11-12T12:00:00Z",
  updated_at: "2026-11-12T12:00:01Z",
  completed_at: "2026-11-12T12:00:01Z",
};

const identities = [
  {
    id: "identity-1",
    stable_identity_key: "animal-0001",
    display_name: "Animal 1",
    origin: "model",
    verification_state: "unreviewed",
    lifecycle_state: "active",
    first_frame: 0,
    last_frame: 5,
    mean_association_confidence: 0.83,
    revision: 1,
  },
  {
    id: "identity-2",
    stable_identity_key: "animal-0002",
    display_name: "Animal 2",
    origin: "scientist",
    verification_state: "scientist_confirmed",
    lifecycle_state: "active",
    first_frame: 0,
    last_frame: 5,
    mean_association_confidence: 0.91,
    revision: 2,
  },
];

const observations = [
  {
    id: "observation-1",
    observation_series_id: "series-1",
    revision: 1,
    supersedes_observation_id: null,
    animal_identity_id: "identity-1",
    source_video_track_id: "track-1",
    source_detection_key: "track-1:3",
    frame_index: 3,
    bbox_json: [10, 20, 30, 15],
    landmarks_json: [
      {
        landmark_id: "nose",
        x: 15,
        y: 25,
        confidence: 0.8,
        visibility: "visible",
      },
      {
        landmark_id: "tail",
        x: 35,
        y: 27,
        confidence: 0.7,
        visibility: "visible",
      },
      {
        landmark_id: "fin",
        x: 25,
        y: 32,
        confidence: 0.1,
        visibility: "absent",
      },
    ],
    detection_confidence: 0.9,
    association_confidence: 0.42,
    visibility_state: "visible",
    assignment_source: "model",
    verification_state: "unreviewed",
    coordinate_space: "source_pixels",
    is_current: true,
  },
];

const tracks: VideoTrackRecord[] = [
  {
    id: "track-1",
    video_id: "video-1",
    label_class_id: "class-1",
    track_number: 1,
    geometry_kind: "bbox",
    keyframes_json: [],
    interpolation: "hold",
    status: "verified",
    source_model_id: "model-1",
    source_job_id: "pose-job",
    metadata_json: {
      pose_landmark_schema: {
        schema_version: "pose-landmarks-0001",
        schema_id: "schema-1",
        schema_revision: 2,
        content_hash: "a".repeat(64),
        groups: [
          { name: "nose", count: 1 },
          { name: "tail", count: 1 },
          { name: "fin", count: 1 },
        ],
        expanded_labels: ["nose", "tail", "fin"],
        keypoint_count: 3,
        allows_repeated_labels: false,
        landmarks: [
          { id: "nose", name: "Nose" },
          { id: "tail", name: "Tail" },
          { id: "fin", name: "Fin" },
        ],
        edges: [
          { from_id: "nose", to_id: "tail" },
          { from_id: "nose", to_id: "fin" },
        ],
      },
    },
    revision: 1,
  },
];

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <PoseIdentityReviewPanel
        projectId="project-1"
        videoId="video-1"
        frameIndex={3}
        tracks={tracks}
        onFrameChange={vi.fn()}
      />
    </QueryClientProvider>,
  );
  return queryClient;
}

describe("PoseIdentityReviewPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(identityApi.listPoseIdentityRuns).mockResolvedValue([run]);
    vi.mocked(identityApi.createPoseIdentityRun).mockResolvedValue({
      id: "identity-job-1",
      status: "queued",
      progress_current: 0,
      progress_total: 1,
      result_json: { run_id: "run-1" },
      error_message: null,
    });
    vi.mocked(identityApi.cancelPoseIdentityJob).mockResolvedValue({
      id: "identity-job-1",
      status: "queued",
      progress_current: 0,
      progress_total: 1,
      result_json: { run_id: "run-1" },
      error_message: null,
    });
    vi.mocked(identityApi.getPoseIdentityIdentities).mockResolvedValue(
      identities,
    );
    vi.mocked(identityApi.getPoseIdentityObservations).mockResolvedValue(
      observations,
    );
    vi.mocked(identityApi.getPoseIdentityDecisions).mockResolvedValue([
      {
        id: "decision-1",
        observation_id: "observation-1",
        candidate_identity_id: "identity-1",
        candidate_rank: 1,
        selected: true,
        passed_gate: true,
        gate_reason: null,
        total_cost: 0.58,
        acceptance_threshold: 0.75,
        association_confidence: 0.42,
        score_components_json: {
          proximity_cost: 0.2,
          overlap_cost: 0.4,
          landmark_cost: 0.3,
          motion_cost: 0.8,
          confidence_cost: 0.1,
        },
        algorithm: "reefpose-geometric-motion-association",
        algorithm_version: "1.0.0",
        parameters_sha256: "b".repeat(64),
      },
    ]);
    vi.mocked(identityApi.getPoseIdentityReviewQueue).mockResolvedValue(
      observations,
    );
    vi.mocked(identityApi.getPoseIdentityCorrections).mockResolvedValue([]);
    vi.mocked(identityApi.createPoseIdentityCorrection).mockResolvedValue({
      id: "correction-1",
      association_run_id: "run-1",
      revision: 2,
      action: "reassign",
      target_type: "observation",
      target_id: "observation-1",
      frame_start: null,
      frame_end: null,
      before_json: {},
      after_json: {},
      before_sha256: "d".repeat(64),
      after_sha256: "e".repeat(64),
      reason: "Crossing correction",
      actor: "local_user",
      created_at: "2026-11-12T12:01:00Z",
    });
  });

  it("shows stable identities, provenance, current skeletons, and low-confidence scores", async () => {
    renderPanel();

    expect(
      await screen.findByRole("button", { name: "animal-0001" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "animal-0002" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Scientist confirmed")).toBeInTheDocument();
    expect(screen.getByText("Low-confidence review (1)")).toBeInTheDocument();
    expect(screen.getByText("motion 0.800")).toBeInTheDocument();
    expect(screen.getByText("schema-1 · revision 2")).toBeInTheDocument();
    expect(screen.getByText("source_pixels · 320 × 180")).toBeInTheDocument();
    const skeleton = screen.getByLabelText(
      "Animal animal-0001 skeleton at frame 3",
    );
    expect(skeleton).toBeInTheDocument();
    expect(skeleton.querySelectorAll("line")).toHaveLength(1);
    expect(skeleton.querySelectorAll("circle")).toHaveLength(2);
  });

  it("reassigns one observation and reloads append-only history", async () => {
    renderPanel();
    await screen.findByRole("button", { name: "animal-0001" });

    fireEvent.change(screen.getByLabelText("Correction action"), {
      target: { value: "reassign" },
    });
    fireEvent.change(screen.getByLabelText("Observation to correct"), {
      target: { value: "observation-1" },
    });
    fireEvent.change(screen.getByLabelText("Destination identity"), {
      target: { value: "identity-2" },
    });
    fireEvent.change(screen.getByLabelText("Correction reason"), {
      target: { value: "Crossing correction" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save identity correction" }),
    );

    await waitFor(() =>
      expect(identityApi.createPoseIdentityCorrection).toHaveBeenCalledWith(
        "run-1",
        {
          action: "reassign",
          target_type: "observation",
          target_id: "observation-1",
          destination_identity_id: "identity-2",
          frame_start: null,
          frame_end: null,
          reason: "Crossing correction",
          actor: "local_user",
        },
      ),
    );
    expect(
      await screen.findByText("Identity correction saved as revision 2."),
    ).toBeInTheDocument();
    expect(identityApi.getPoseIdentityCorrections).toHaveBeenCalledTimes(2);
  });

  it("requires compatible schema-bound pose tracks before association", async () => {
    renderPanel();
    await screen.findByRole("button", { name: "animal-0001" });
    const region = screen.getByRole("region", {
      name: "Animal identity tracking",
    });
    expect(
      within(region).getByRole("button", { name: "Associate individuals" }),
    ).toBeEnabled();
  });

  it("queues compatible association and exposes persisted-job cancellation", async () => {
    renderPanel();
    await screen.findByRole("button", { name: "animal-0001" });

    fireEvent.click(
      screen.getByRole("button", { name: "Associate individuals" }),
    );
    await waitFor(() =>
      expect(identityApi.createPoseIdentityRun).toHaveBeenCalledWith(
        "project-1",
        expect.objectContaining({
          video_id: "video-1",
          source_track_ids: ["track-1"],
          pose_schema_id: "schema-1",
          pose_schema_revision: 2,
          device: "auto",
        }),
      ),
    );
    expect(
      await screen.findByText(/Identity association queued/),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cancel association" }));
    await waitFor(() =>
      expect(identityApi.cancelPoseIdentityJob).toHaveBeenCalledWith(
        "identity-job-1",
      ),
    );
    expect(
      await screen.findByText("Identity association cancellation requested."),
    ).toBeInTheDocument();
  });

  it("reloads identity records when a queued run reaches completion", async () => {
    const queuedRun = { ...run, status: "queued", completed_at: null };
    vi.mocked(identityApi.listPoseIdentityRuns).mockResolvedValue([queuedRun]);
    vi.mocked(identityApi.getPoseIdentityIdentities)
      .mockResolvedValueOnce([])
      .mockResolvedValue(identities);
    const queryClient = renderPanel();

    await screen.findByRole("option", { name: /queued/ });
    await waitFor(() =>
      expect(identityApi.getPoseIdentityIdentities).toHaveBeenCalledTimes(1),
    );
    expect(
      screen.queryByRole("button", { name: "animal-0001" }),
    ).not.toBeInTheDocument();

    queryClient.setQueryData(["pose-identity-runs", "project-1"], [run]);
    expect(
      await screen.findByRole("button", { name: "animal-0001" }),
    ).toBeInTheDocument();
    expect(identityApi.getPoseIdentityIdentities).toHaveBeenCalledTimes(2);
    expect(
      screen.queryByRole("button", { name: "Cancel association" }),
    ).not.toBeInTheDocument();
  });

  it("cancels a persisted queued run after the workspace is reloaded", async () => {
    vi.mocked(identityApi.listPoseIdentityRuns).mockResolvedValue([
      { ...run, status: "queued", completed_at: null },
    ]);
    renderPanel();

    fireEvent.click(
      await screen.findByRole("button", { name: "Cancel association" }),
    );
    await waitFor(() =>
      expect(identityApi.cancelPoseIdentityJob).toHaveBeenCalledWith("job-1"),
    );
  });
});
