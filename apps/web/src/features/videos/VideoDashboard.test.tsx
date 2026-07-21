import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";
import {
  addVideoTrackObservation,
  analyzeVideo,
  calibrateVideo,
  cancelJob,
  correctVideoTrackIdentity,
  createVideoDataExport,
  createVideoRenderExport,
  createVideoZone,
  createVideoTracking,
  evaluateVideoTracking,
  getJob,
  getModels,
  getVideoTrackingEvaluations,
  getVideoTracks,
  getVideoZones,
  getVideos,
  mergeVideoTracks,
  reassignVideoTrackObservations,
  splitVideoTrack,
  updateVideoTrackObservation,
  updateVideoZone,
  type JobRecord,
  type VideoAnalytics,
  type VideoTrack,
  type VideoTrackingEvaluation,
  type VideoZone,
} from "../phase456/api";
import { VideoDashboard } from "./VideoDashboard";

vi.mock("../phase456/api", async () => {
  const actual =
    await vi.importActual<typeof import("../phase456/api")>("../phase456/api");
  return {
    ...actual,
    addVideoTrackObservation: vi.fn(),
    analyzeVideo: vi.fn(),
    archiveVideoTrack: vi.fn(),
    calibrateVideo: vi.fn(),
    cancelJob: vi.fn(),
    correctVideoTrackIdentity: vi.fn(),
    createVideoDataExport: vi.fn(),
    createVideoRenderExport: vi.fn(),
    createVideoTrack: vi.fn(),
    createVideoTracking: vi.fn(),
    createVideoZone: vi.fn(),
    deleteVideoTrackObservation: vi.fn(),
    deleteVideoZone: vi.fn(),
    evaluateVideoTracking: vi.fn(),
    getJob: vi.fn(),
    getModels: vi.fn(),
    getVideoTrackingEvaluations: vi.fn(),
    getVideoTracks: vi.fn(),
    getVideoZones: vi.fn(),
    getVideos: vi.fn(),
    mergeVideoTracks: vi.fn(),
    reassignVideoTrackObservations: vi.fn(),
    restoreVideoTrackObservation: vi.fn(),
    splitVideoTrack: vi.fn(),
    updateVideoTrack: vi.fn(),
    updateVideoTrackObservation: vi.fn(),
    updateVideoZone: vi.fn(),
    uploadVideo: vi.fn(),
  };
});

const project: Project = {
  id: "project-1",
  name: "Fish study",
  slug: "fish-study",
  description: null,
  storage_root: "projects/fish-study",
  default_annotation_type: "bounding_box",
  created_at: "2026-07-20T00:00:00Z",
  updated_at: "2026-07-20T00:00:00Z",
  archived_at: null,
  label_classes: [
    {
      id: "class-fish",
      project_id: "project-1",
      class_index: 0,
      display_order: 0,
      name: "Fish",
      scientific_name: null,
      state_name: null,
      description: null,
      display_color: "#22ddaa",
      is_active: true,
      archived_at: null,
      created_at: "2026-07-20T00:00:00Z",
      updated_at: "2026-07-20T00:00:00Z",
    },
  ],
};

const videos = [
  {
    id: "video-1",
    project_id: project.id,
    original_filename: "reef-a.mp4",
    media_type: "video/mp4",
    width_px: 100,
    height_px: 80,
    frame_count: 20,
    fps: 10,
    duration_seconds: 2,
    metadata_json: {},
    created_at: "2026-07-20T00:00:00Z",
    updated_at: "2026-07-20T00:00:00Z",
    revision: 1,
  },
  {
    id: "video-2",
    project_id: project.id,
    original_filename: "reef-b.mp4",
    media_type: "video/mp4",
    width_px: 120,
    height_px: 90,
    frame_count: 12,
    fps: 6,
    duration_seconds: 2,
    metadata_json: {},
    created_at: "2026-07-20T00:00:00Z",
    updated_at: "2026-07-20T00:00:00Z",
    revision: 1,
  },
];

function keyframe(id: string, frame: number, x: number, manualEdit = false) {
  return {
    id,
    frame_index: frame,
    timestamp_seconds: frame / 10,
    x_min: x,
    y_min: 10,
    x_max: x + 10,
    y_max: 20,
    centroid_x: x + 5,
    centroid_y: 15,
    confidence: 0.9,
    source: manualEdit ? "human" : "bytetrack",
    manual_edit: manualEdit,
    automated_provenance: manualEdit ? { tracker: "bytetrack" } : null,
    deleted_at: null,
    revision: manualEdit ? 2 : 1,
  };
}

const trackOne: VideoTrack = {
  id: "track-1",
  video_id: "video-1",
  label_class_id: "class-fish",
  origin_job_id: "job-track",
  track_number: 1,
  name: "Fish one",
  geometry_kind: "bounding_box",
  keyframes: [keyframe("obs-1", 0, 10), keyframe("obs-2", 5, 20, true)],
  interpolation: "linear",
  status: "generated",
  source_type: "generated",
  is_ground_truth: false,
  metadata_json: { tracker: "bytetrack" },
  created_by: "video_tracking_worker",
  updated_by: "local_user",
  created_at: "2026-07-20T00:00:00Z",
  updated_at: "2026-07-20T00:00:00Z",
  deleted_at: null,
  revision: 2,
};

const trackTwo: VideoTrack = {
  ...trackOne,
  id: "track-2",
  origin_job_id: "job-bot",
  track_number: 2,
  name: "Fish two",
  keyframes: [keyframe("obs-3", 0, 50), keyframe("obs-4", 5, 40)],
  revision: 1,
};

const zone: VideoZone = {
  id: "zone-1",
  video_id: "video-1",
  name: "Left",
  x_min: 0,
  y_min: 0,
  x_max: 40,
  y_max: 80,
  revision: 1,
  created_at: "2026-07-20T00:00:00Z",
  updated_at: "2026-07-20T00:00:00Z",
};

const completedJob: JobRecord = {
  id: "job-new",
  job_type: "video_track",
  status: "succeeded",
  progress_current: 20,
  progress_total: 20,
  request_json: {},
  result_json: { track_ids: [trackOne.id] },
  error_message: null,
};

const analyticsResult: VideoAnalytics = {
  analysis_id: "analysis-1",
  video_id: "video-1",
  fps: 10,
  coordinate_unit: "pixels",
  timing_source: "observation_timestamps",
  distance_per_pixel: null,
  physical_unit: null,
  tracks: [
    {
      track_id: trackOne.id,
      tracker_id: 1,
      label_class_id: "class-fish",
      duration_seconds: 0.5,
      distance_pixels: 5,
      net_displacement_pixels: 5,
      total_path_length_pixels: 5,
      path_tortuosity: 1,
      mean_speed_pixels_per_second: 10,
      maximum_speed_pixels_per_second: 10,
      mean_acceleration_pixels_per_second_squared: 0,
      maximum_acceleration_pixels_per_second_squared: 0,
      mean_turning_angle_degrees: 0,
      cumulative_turning_angle_degrees: 0,
      mean_angular_velocity_degrees_per_second: 0,
      mean_distance_to_wall_pixels: 15,
      active_time_seconds: 0.5,
      inactive_time_seconds: 0,
      distance_physical: null,
      mean_speed_physical_per_second: null,
      mean_distance_to_wall_physical: null,
      physical_unit: null,
      zone_time_seconds: { Left: 0.5 },
      trajectory: [
        {
          observation_id: "obs-1",
          frame_index: 0,
          timestamp_seconds: 0,
          center_x_pixels: 15,
          center_y_pixels: 15,
          center_x_physical: null,
          center_y_physical: null,
          interpolated: false,
          manual_edit: false,
        },
      ],
    },
  ],
  school_by_frame: [],
  heatmap_bins_x: 20,
  heatmap_bins_y: 20,
  heatmap: [
    { column: 1, row: 1, observation_count: 1, occupancy_seconds: 0.1 },
  ],
  zone_events: [
    {
      track_id: "track-1",
      zone_name: "Left",
      event_type: "entry",
      frame_index: 0,
      timestamp_seconds: 0,
    },
  ],
  configuration: {},
  source_track_revisions: [{ track_id: "track-1", revision: 2 }],
  analysis_sha256: "a".repeat(64),
  warnings: ["Physical metrics unavailable without calibration."],
};

const evaluationResult: VideoTrackingEvaluation = {
  evaluation_id: "evaluation-1",
  video_id: "video-1",
  ground_truth_available: true,
  minimum_iou: 0.5,
  ranked_by_hota: [
    {
      candidate_name: "ByteTrack confidence 0.25",
      parameters: {},
      localization_iou: 0.9,
      detection_precision: 1,
      detection_recall: 0.8,
      identity_switch_count: 1,
      fragmentation_count: 2,
      false_positive_track_count: 0,
      false_negative_track_count: 0,
      mostly_tracked_count: 1,
      mostly_lost_count: 0,
      mean_track_continuity: 0.75,
      mota: 0.7,
      motp: 0.9,
      idf1: 0.8,
      hota: 0.75,
      per_frame: [],
      per_track: [],
    },
  ],
  best_candidate_name: "ByteTrack confidence 0.25",
  configuration: {},
  source_track_revisions: [],
  evaluation_sha256: "b".repeat(64),
  warnings: ["Synthetic fixtures are software acceptance only."],
};

function operationResult(operation: string) {
  return {
    operation,
    operation_id: `${operation}-1`,
    tracks: [trackOne, trackTwo],
    deleted_track_ids: [],
    warnings: [],
    replayed: false,
  };
}

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <VideoDashboard project={project} />
    </QueryClientProvider>,
  );
}

describe("VideoDashboard", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    vi.mocked(getVideos).mockResolvedValue(videos);
    vi.mocked(getModels).mockResolvedValue([
      {
        id: "detector-1",
        purpose: "detector",
        task: "detect",
        display_name: "Local fish detector",
        provider_name: "ultralytics",
        metadata_json: {},
      },
    ]);
    vi.mocked(getVideoTracks).mockImplementation(async (videoId) =>
      videoId === "video-1" ? [trackOne, trackTwo] : [],
    );
    vi.mocked(getVideoZones).mockImplementation(async (videoId) =>
      videoId === "video-1" ? [zone] : [],
    );
    vi.mocked(getVideoTrackingEvaluations).mockResolvedValue([]);
    vi.mocked(getJob).mockResolvedValue(completedJob);
    vi.mocked(createVideoTracking).mockResolvedValue({
      ...completedJob,
      status: "queued",
      progress_current: 0,
    });
    vi.mocked(cancelJob).mockResolvedValue({
      ...completedJob,
      status: "cancel_requested",
    });
    vi.mocked(calibrateVideo).mockResolvedValue({
      ...videos[0],
      metadata_json: {
        calibration: { distance_per_pixel: 0.1, unit: "cm" },
      },
      revision: 2,
    });
    vi.mocked(updateVideoTrackObservation).mockResolvedValue(
      operationResult("observation_updated"),
    );
    vi.mocked(addVideoTrackObservation).mockResolvedValue(
      operationResult("observation_added"),
    );
    vi.mocked(splitVideoTrack).mockResolvedValue(
      operationResult("track_split"),
    );
    vi.mocked(mergeVideoTracks).mockResolvedValue(
      operationResult("tracks_merged"),
    );
    vi.mocked(correctVideoTrackIdentity).mockResolvedValue(
      operationResult("identity_switch_corrected"),
    );
    vi.mocked(reassignVideoTrackObservations).mockResolvedValue(
      operationResult("observations_reassigned"),
    );
    vi.mocked(updateVideoZone).mockResolvedValue({ ...zone, revision: 2 });
    vi.mocked(createVideoZone).mockResolvedValue({
      ...zone,
      id: "zone-2",
      name: "Nursery",
    });
    vi.mocked(analyzeVideo).mockResolvedValue(analyticsResult);
    vi.mocked(evaluateVideoTracking).mockResolvedValue(evaluationResult);
    vi.mocked(createVideoDataExport).mockResolvedValue({
      artifact_id: "artifact-1",
      video_id: "video-1",
      archive_path: "projects/fish-study/video-exports/data.zip",
      manifest_path: "projects/fish-study/video-exports/data/manifest.json",
      archive_sha256: "c".repeat(64),
      archive_size_bytes: 2048,
      manifest_sha256: "d".repeat(64),
      formats: ["csv", "json", "mot", "npz"],
    });
    vi.mocked(createVideoRenderExport).mockResolvedValue({
      job: {
        ...completedJob,
        id: "render-job",
        job_type: "video_render_export",
      },
    });
  });

  it("selects videos, renders source-coordinate overlays, and clears stale results", async () => {
    const user = userEvent.setup();
    renderDashboard();

    await waitFor(() =>
      expect(screen.getByLabelText("Managed video")).toHaveValue("video-1"),
    );
    await screen.findByRole("heading", { name: "2 active tracks" });
    expect(screen.getByText(/100×80 · 10.000 fps/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Select track 1 on frame 0/i }),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Calculate behavior metrics" }),
    );
    expect(await screen.findByText(/Path 5.00 px/)).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Managed video"), "video-2");
    await waitFor(() =>
      expect(getVideoTracks).toHaveBeenCalledWith("video-2", expect.anything()),
    );
    await screen.findByRole("heading", { name: "0 active tracks" });
    expect(screen.queryByText(/Path 5.00 px/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Select track 1 on frame 0/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/120×90 · 6.000 fps/)).toBeInTheDocument();
  });

  it("submits BoT-SORT options once, disables pending submission, and refreshes tracks", async () => {
    const user = userEvent.setup();
    let resolveTracking: ((job: JobRecord) => void) | undefined;
    vi.mocked(createVideoTracking).mockReturnValue(
      new Promise((resolve) => {
        resolveTracking = resolve;
      }),
    );
    renderDashboard();
    await waitFor(() =>
      expect(screen.getByLabelText("Managed video")).toHaveValue("video-1"),
    );
    await user.selectOptions(screen.getByLabelText("Tracker"), "botsort");
    await user.selectOptions(screen.getByLabelText("Tracking device"), "cpu");
    const submit = screen.getByRole("button", { name: "Run fish tracking" });
    await user.click(submit);
    expect(screen.getByRole("button", { name: "Queuing…" })).toBeDisabled();
    expect(createVideoTracking).toHaveBeenCalledTimes(1);
    expect(createVideoTracking).toHaveBeenCalledWith(
      "video-1",
      expect.objectContaining({
        tracker: "botsort",
        device: "cpu",
        tracker_options: expect.objectContaining({
          gmc_method: "sparseOptFlow",
          track_buffer: 30,
        }),
      }),
    );

    resolveTracking?.({
      ...completedJob,
      status: "queued",
      progress_current: 0,
    });
    await screen.findByText("Tracking completed.");
    await waitFor(() => expect(getVideoTracks).toHaveBeenCalledTimes(2));
  });

  it("renders tracking failures and supports cancellation of a running job", async () => {
    const user = userEvent.setup();
    vi.mocked(createVideoTracking).mockRejectedValueOnce(
      new Error("Detector is incompatible with video tracking."),
    );
    renderDashboard();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Run fish tracking" }),
      ).toBeEnabled(),
    );
    await user.click(screen.getByRole("button", { name: "Run fish tracking" }));
    expect(
      await screen.findByText("Detector is incompatible with video tracking."),
    ).toBeInTheDocument();

    vi.mocked(createVideoTracking).mockResolvedValue({
      ...completedJob,
      status: "queued",
      progress_current: 0,
    });
    vi.mocked(getJob).mockResolvedValue({
      ...completedJob,
      status: "running",
      progress_current: 3,
    });
    await user.click(screen.getByRole("button", { name: "Run fish tracking" }));
    await user.click(await screen.findByRole("button", { name: "Cancel job" }));
    expect(cancelJob).toHaveBeenCalledWith("job-new");
  });

  it("edits observations and exposes split, merge, identity, and reassignment controls", async () => {
    const user = userEvent.setup();
    renderDashboard();
    const selectTrack = await screen.findByRole("button", {
      name: /Fish one automatic/i,
    });
    await user.click(selectTrack);
    const correctionCard = screen
      .getByRole("heading", { name: "2 active tracks" })
      .closest(".dashboard-card");
    expect(correctionCard).not.toBeNull();
    const correction = within(correctionCard as HTMLElement);
    await user.click(
      correction.getByRole("button", { name: /Frame 0 · bytetrack/i }),
    );
    await user.clear(correction.getByLabelText("X min"));
    await user.type(correction.getByLabelText("X min"), "12");
    await user.click(
      correction.getByRole("button", { name: "Save observation edit" }),
    );
    await waitFor(() =>
      expect(updateVideoTrackObservation).toHaveBeenCalledWith(
        "track-1",
        "obs-1",
        expect.objectContaining({ expected_revision: 2, x_min: 12 }),
      ),
    );
    await correction.findByRole("button", { name: "Add observation" });
    await user.clear(correction.getByLabelText("Frame number"));
    await user.type(correction.getByLabelText("Frame number"), "3");
    await user.click(
      correction.getByRole("button", { name: "Add observation" }),
    );
    expect(addVideoTrackObservation).toHaveBeenCalledWith(
      "track-1",
      expect.objectContaining({
        expected_revision: 2,
        observation: expect.objectContaining({ frame_index: 3 }),
      }),
    );

    await user.selectOptions(
      correction.getByLabelText("Other track"),
      "track-2",
    );
    await user.click(
      correction.getByRole("button", { name: "Split selected track" }),
    );
    expect(splitVideoTrack).toHaveBeenCalledWith(
      "track-1",
      expect.objectContaining({ split_frame: 1, expected_revision: 2 }),
    );
    await user.click(
      correction.getByRole("button", { name: "Merge into selected track" }),
    );
    expect(mergeVideoTracks).toHaveBeenCalledWith(
      expect.objectContaining({
        primary_track_id: "track-1",
        secondary_track_id: "track-2",
      }),
    );
    await user.click(
      correction.getByRole("button", { name: "Correct identity switch" }),
    );
    expect(correctVideoTrackIdentity).toHaveBeenCalled();

    await user.click(
      correction.getByRole("button", { name: /Frame 0 · bytetrack/i }),
    );
    await user.click(
      correction.getByRole("button", { name: "Reassign selected observation" }),
    );
    expect(reassignVideoTrackObservations).toHaveBeenCalledWith(
      expect.objectContaining({ observation_ids: ["obs-1"] }),
    );
  });

  it("saves calibration and zones, shows behavior and evaluation, and submits exports", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await waitFor(() =>
      expect(screen.getByLabelText("Managed video")).toHaveValue("video-1"),
    );
    await user.type(screen.getByLabelText("Distance per pixel"), "0.1");
    await user.click(screen.getByRole("button", { name: "Save calibration" }));
    expect(calibrateVideo).toHaveBeenCalledWith(
      "video-1",
      expect.objectContaining({ distance_per_pixel: 0.1, unit: "cm" }),
    );

    const zoneCard = screen
      .getByRole("heading", { name: "Calibrated trajectories and occupancy" })
      .closest(".dashboard-card");
    expect(zoneCard).not.toBeNull();
    const zoneControls = within(zoneCard as HTMLElement);
    await user.click(zoneControls.getByRole("button", { name: "Edit zone" }));
    await user.clear(zoneControls.getByLabelText("Zone name"));
    await user.type(zoneControls.getByLabelText("Zone name"), "Nursery");
    await user.click(zoneControls.getByRole("button", { name: "Update zone" }));
    expect(updateVideoZone).toHaveBeenCalledWith(
      "zone-1",
      expect.objectContaining({ name: "Nursery", expected_revision: 1 }),
    );
    await zoneControls.findByRole("button", { name: "Create zone" });
    await user.type(zoneControls.getByLabelText("Zone name"), "Nursery");
    await user.click(zoneControls.getByRole("button", { name: "Create zone" }));
    expect(createVideoZone).toHaveBeenCalledWith(
      "video-1",
      expect.objectContaining({ name: "Nursery" }),
    );

    await user.click(
      zoneControls.getByRole("button", { name: "Calculate behavior metrics" }),
    );
    expect(await screen.findByText(/Path 5.00 px/)).toBeInTheDocument();
    expect(screen.getByLabelText("Heatmap occupancy")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Compare tracker results" }),
    );
    expect(
      await screen.findByText("ByteTrack confidence 0.25"),
    ).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", {
        name: "Create CSV / JSON / MOT / NumPy bundle",
      }),
    );
    expect(
      await screen.findByRole("link", { name: "Open checksummed bundle" }),
    ).toHaveAttribute(
      "href",
      expect.stringContaining("/artifacts/artifact-1/content"),
    );
    expect(createVideoDataExport).toHaveBeenCalledWith(
      "video-1",
      expect.objectContaining({ formats: ["csv", "json", "mot", "npz"] }),
    );

    await user.selectOptions(
      screen.getByLabelText("Rendered view"),
      "trajectory",
    );
    await user.click(
      screen.getByRole("button", { name: "Queue rendered video" }),
    );
    expect(createVideoRenderExport).toHaveBeenCalledWith(
      "video-1",
      expect.objectContaining({ export_kind: "trajectory" }),
    );
  });

  it("shows an empty state and keeps actions disabled without managed videos", async () => {
    vi.mocked(getVideos).mockResolvedValue([]);
    renderDashboard();
    expect(
      await screen.findByText("Import a managed video to begin Phase 6."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Run fish tracking" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Calculate behavior metrics" }),
    ).toBeDisabled();
  });
});
