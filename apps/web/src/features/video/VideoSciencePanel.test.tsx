import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";
import { VideoSciencePanel } from "./VideoSciencePanel";
import * as videoApi from "./videoApi";
import * as scienceApi from "./videoScienceApi";

vi.mock("./videoApi", async () => {
  const actual =
    await vi.importActual<typeof import("./videoApi")>("./videoApi");
  return {
    ...actual,
    getVideos: vi.fn(),
    getVideoTracks: vi.fn(),
  };
});

vi.mock("./videoScienceApi", async () => {
  const actual =
    await vi.importActual<typeof import("./videoScienceApi")>(
      "./videoScienceApi",
    );
  return {
    ...actual,
    getVideoCalibration: vi.fn(),
    setVideoCalibration: vi.fn(),
    clearVideoCalibration: vi.fn(),
    getCalibratedTrackAnalytics: vi.fn(),
    getSchoolingAnalytics: vi.fn(),
    getVideoCameraIntrinsics: vi.fn(),
    setVideoCameraIntrinsics: vi.fn(),
    clearVideoCameraIntrinsics: vi.fn(),
    getDepthTrackAnalytics: vi.fn(),
  };
});

const project: Project = {
  id: "project-1",
  name: "3D fish science",
  slug: "3d-fish-science",
  description: null,
  storage_root: "projects/project-1",
  default_annotation_type: "bbox",
  created_at: "2026-08-18T00:00:00Z",
  updated_at: "2026-08-18T00:00:00Z",
  archived_at: null,
  label_classes: [
    {
      id: "class-1",
      project_id: "project-1",
      class_index: 0,
      display_order: 0,
      name: "Fish",
      scientific_name: null,
      state_name: null,
      description: null,
      display_color: "#00aaff",
      is_active: true,
      archived_at: null,
      created_at: "2026-08-18T00:00:00Z",
      updated_at: "2026-08-18T00:00:00Z",
    },
  ],
};

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <VideoSciencePanel project={project} />
    </QueryClientProvider>,
  );
}

describe("VideoSciencePanel", () => {
  beforeEach(() => {
    vi.mocked(videoApi.getVideos).mockResolvedValue([
      {
        id: "video-1",
        project_id: project.id,
        original_filename: "reef-fish.mp4",
        managed_path: "projects/project-1/videos/originals/video-1.mp4",
        sha256: "a".repeat(64),
        media_type: "video/mp4",
        width_px: 1920,
        height_px: 1080,
        frame_count: 300,
        fps: 30,
        duration_seconds: 10,
        metadata_json: {},
        frame_directory_path: null,
        extraction_job_id: null,
        status: "ready",
        revision: 1,
      },
    ]);
    vi.mocked(videoApi.getVideoTracks).mockResolvedValue([
      {
        id: "track-1",
        video_id: "video-1",
        label_class_id: "class-1",
        track_number: 1,
        geometry_kind: "bbox",
        keyframes_json: [],
        interpolation: "linear",
        status: "verified",
        source_model_id: null,
        source_job_id: null,
        metadata_json: {},
        revision: 1,
      },
    ]);
    vi.mocked(scienceApi.getVideoCalibration).mockResolvedValue(null);
    vi.mocked(scienceApi.getVideoCameraIntrinsics).mockResolvedValue({
      schema_version: "video-camera-intrinsics-0001",
      video_id: "video-1",
      fx_px: 100,
      fy_px: 100,
      cx_px: 5,
      cy_px: 5,
      method: "checkerboard",
      notes: "Validated camera",
      video_revision: 2,
    });
    vi.mocked(scienceApi.getDepthTrackAnalytics).mockResolvedValue({
      schema_version: "video-depth-track-analytics-0001",
      video_id: "video-1",
      unit: "m",
      camera_intrinsics: {
        schema_version: "video-camera-intrinsics-0001",
        video_id: "video-1",
        fx_px: 100,
        fy_px: 100,
        cx_px: 5,
        cy_px: 5,
        method: "checkerboard",
        notes: "Validated camera",
        video_revision: 2,
      },
      tracks: [
        {
          track_id: "track-1",
          track_number: 1,
          label_class_id: "class-1",
          observed_frame_count: 2,
          first_frame: 0,
          last_frame: 2,
          duration_seconds: 0.2,
          path_length_3d: 0.4,
          displacement_3d: 0.4,
          mean_speed_3d_per_second: 2,
          maximum_speed_3d_per_second: 2,
          mean_depth: 2,
          minimum_depth: 2,
          maximum_depth: 2,
          skipped_gap_count: 0,
          points: [],
        },
      ],
      warnings: [],
    });
  });

  it("shows calibrated 3D movement controls without treating relative depth as metric", async () => {
    renderPanel();

    expect(
      await screen.findByText("Calibration, schooling, and 3D movement"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Metric depth / 3D trajectories"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Relative Depth Anything values are not physical distances/,
      ),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/Saved intrinsics: fx 100\.00/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Calculate 3D trajectories" }),
    ).toBeEnabled();
  });

  it("parses track-number depth CSV and sends metric samples to 3D analytics", async () => {
    renderPanel();
    await screen.findByText(/Saved intrinsics: fx 100\.00/);

    const textarea = screen.getByLabelText("Metric depth samples (CSV)");
    fireEvent.change(textarea, {
      target: {
        value: "track,frame,depth,confidence\n1,0,2.0,0.99\n1,2,2.0,0.98",
      },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Calculate 3D trajectories" }),
    );

    await waitFor(() => {
      expect(scienceApi.getDepthTrackAnalytics).toHaveBeenCalledWith(
        "video-1",
        {
          unit: "m",
          samples: [
            { track_id: "track-1", frame: 0, depth: 2, confidence: 0.99 },
            { track_id: "track-1", frame: 2, depth: 2, confidence: 0.98 },
          ],
          maximum_frame_gap: null,
        },
      );
    });
    expect(screen.getByText("3D path")).toBeInTheDocument();
    expect(screen.getByText("3D displacement")).toBeInTheDocument();
    expect(await screen.findAllByText("0.4000 m")).toHaveLength(2);
    expect(screen.getAllByText("2.0000 m/s")).toHaveLength(2);
  });
});
