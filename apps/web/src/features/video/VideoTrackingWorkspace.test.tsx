import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";
import { VideoTrackingWorkspace } from "./VideoTrackingWorkspace";
import * as api from "./videoApi";

vi.mock("./videoApi", async () => {
  const actual =
    await vi.importActual<typeof import("./videoApi")>("./videoApi");
  return {
    ...actual,
    getVideos: vi.fn(),
    getVideoTracks: vi.fn(),
    getVideoTrackInterpolation: vi.fn(),
    getVideoTrackAnalytics: vi.fn(),
    getTrackingModels: vi.fn(),
  };
});

const project: Project = {
  id: "project-1",
  name: "Fish tracking project",
  slug: "fish-tracking-project",
  description: null,
  storage_root: "projects/project-1",
  default_annotation_type: "bbox",
  created_at: "2026-07-18T00:00:00Z",
  updated_at: "2026-07-18T00:00:00Z",
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
      created_at: "2026-07-18T00:00:00Z",
      updated_at: "2026-07-18T00:00:00Z",
    },
  ],
};

function renderWorkspace() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <VideoTrackingWorkspace project={project} />
    </QueryClientProvider>,
  );
}

describe("VideoTrackingWorkspace", () => {
  beforeEach(() => {
    vi.mocked(api.getVideos).mockResolvedValue([
      {
        id: "video-1",
        project_id: "project-1",
        original_filename: "fish.mp4",
        managed_path: "projects/project-1/videos/originals/video-1.mp4",
        sha256: "a".repeat(64),
        media_type: "video/mp4",
        width_px: 1920,
        height_px: 1080,
        frame_count: 300,
        fps: 30,
        duration_seconds: 10,
        metadata_json: { extraction_every_n_frames: 10 },
        frame_directory_path: "projects/project-1/videos/frames/video-1",
        extraction_job_id: "job-1",
        status: "frames_ready",
        revision: 2,
      },
    ]);
    vi.mocked(api.getVideoTracks).mockResolvedValue([]);
    vi.mocked(api.getVideoTrackInterpolation).mockResolvedValue({
      track_id: "track-1",
      video_id: "video-1",
      interpolation: "linear",
      frames: [],
    });
    vi.mocked(api.getVideoTrackAnalytics).mockResolvedValue({
      track_id: "track-1",
      video_id: "video-1",
      track_number: 1,
      label_class_id: "class-1",
      first_frame: 0,
      last_frame: 0,
      observed_frame_count: 1,
      duration_seconds: 0,
      path_length_pixels: 0,
      mean_speed_pixels_per_second: 0,
      maximum_speed_pixels_per_second: 0,
      displacement_pixels: 0,
      mean_bbox_area_pixels: 100,
      occupancy_grid: {},
    });
    vi.mocked(api.getTrackingModels).mockResolvedValue([]);
  });

  it("shows managed video, frame, track, and automated tracking sections", async () => {
    renderWorkspace();

    expect(await screen.findByText("Managed videos")).toBeInTheDocument();
    expect(screen.getByText("Source-coordinate overlay")).toBeInTheDocument();
    expect(screen.getByText("Identities and keyframes")).toBeInTheDocument();
    expect(screen.getByText("Detector + ByteTrack")).toBeInTheDocument();
    expect(await screen.findByText(/fish\.mp4/)).toBeInTheDocument();
    expect(await screen.findByText(/300 frames/)).toBeInTheDocument();
  });
});
