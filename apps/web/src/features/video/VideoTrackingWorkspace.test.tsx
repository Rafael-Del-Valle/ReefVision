import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";
import { VideoTrackingWorkspace } from "./VideoTrackingWorkspace";
import * as api from "./videoApi";
import * as geographicApi from "./videoGeographicMovementAnalyticsApi";
import type { GeographicTrackAnalytics } from "./videoGeographicMovementAnalyticsApi";

vi.mock("./GeoreferencedMapPanel", () => ({
  GeoreferencedMapPanel: ({
    videoId,
    activeFrameIndex,
    onFrameSelect,
  }: {
    videoId: string;
    activeFrameIndex?: number | null;
    onFrameSelect?: (frameIndex: number, frameTimeSeconds: number) => void;
  }) => (
    <section data-testid="mock-georeferenced-map-panel">
      <h3>Geographic observations</h3>
      <span>{videoId}</span>
      <span data-testid="mock-active-map-frame">
        {activeFrameIndex ?? "none"}
      </span>
      <button type="button" onClick={() => onFrameSelect?.(42, 1.4)}>
        Select map observation
      </button>
    </section>
  ),
}));

vi.mock("./videoGeographicMovementAnalyticsApi", async () => {
  const actual = await vi.importActual<
    typeof import("./videoGeographicMovementAnalyticsApi")
  >("./videoGeographicMovementAnalyticsApi");

  return {
    ...actual,
    getVideoTrackGeographicAnalytics: vi.fn(),
  };
});

vi.mock("./videoApi", async () => {
  const actual =
    await vi.importActual<typeof import("./videoApi")>("./videoApi");
  return {
    ...actual,
    getVideos: vi.fn(),
    getVideoGeoreferencingReadiness: vi.fn(),
    getVideoTracks: vi.fn(),
    getVideoTrackInterpolation: vi.fn(),
    getVideoTrackAnalytics: vi.fn(),
    getTrackingModels: vi.fn(),
    getAnnotatedVideoExports: vi.fn(),
    importVideo: vi.fn(),
  };
});

const project: Project = {
  id: "project-1",
  name: "Fish tracking project",
  slug: "fish-tracking-project",
  description: null,
  storage_root: "projects/project-1",
  default_annotation_type: "bbox",
  georeference_height_offset_m: 0,
  georeference_height_evidence: null,
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
    vi.clearAllMocks();
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
        created_at: "2026-09-23T00:00:00Z",
        updated_at: "2026-09-23T00:00:00Z",
        telemetry: {
          found: false,
          available: false,
          source_type: null,
          source_path: null,
          path_kind: null,
          sample_count: 0,
          error: null,
        },
        airdata_telemetry: {
          found: false,
          available: false,
          source_type: null,
          source_path: null,
          path_kind: null,
          sample_count: 0,
          error: null,
        },
        airdata_alignment: { time_offset_s: 0, evidence: null },
      },
    ]);
    vi.mocked(api.getVideoGeoreferencingReadiness).mockResolvedValue({
      schema_version: "video-georeferencing-readiness-0001",
      video_id: "video-1",
      project_id: project.id,
      ready: true,
      state: "ready",
      issues: [],
      srt_available: true,
      airdata_available: true,
      airdata_alignment_valid: true,
      surface_reference_configured: true,
      calibration_available: true,
      calibration_valid: true,
      calibration_checksum_sha256: "a".repeat(64),
      sampled_frame_indices: [0, 75, 150, 224, 299],
      synchronized_frame_count: 5,
      sampled_frame_count: 5,
      maximum_sync_error_s: 0.05,
      zoom_compatible: true,
      max_allowed_sync_error_s: 0.1,
    });
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
    vi.mocked(api.importVideo).mockImplementation(async () => {
      const videos = await api.getVideos("project-1");
      return videos[0];
    });
    vi.mocked(api.getTrackingModels).mockResolvedValue([]);
    vi.mocked(api.getAnnotatedVideoExports).mockResolvedValue([]);
  });

  it("renders backend georeferencing readiness blockers", async () => {
    vi.mocked(api.getVideoGeoreferencingReadiness).mockResolvedValue({
      schema_version: "video-georeferencing-readiness-0001",
      video_id: "video-1",
      project_id: project.id,
      ready: false,
      state: "missing_calibration",
      issues: [
        {
          code: "missing_calibration",
          message:
            "Video georeferencing camera calibration has not been configured",
        },
        {
          code: "missing_surface_reference",
          message:
            "Project georeferencing height datum evidence has not been configured",
        },
      ],
      srt_available: true,
      airdata_available: false,
      airdata_alignment_valid: true,
      surface_reference_configured: false,
      calibration_available: false,
      calibration_valid: false,
      calibration_checksum_sha256: null,
      sampled_frame_indices: [0, 75, 150, 224, 299],
      synchronized_frame_count: 0,
      sampled_frame_count: 5,
      maximum_sync_error_s: null,
      zoom_compatible: null,
      max_allowed_sync_error_s: 0.1,
    });

    renderWorkspace();

    expect(await screen.findByText("Missing calibration")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Video georeferencing camera calibration has not been configured",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Project georeferencing height datum evidence has not been configured",
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Georeferencing readiness")).toHaveTextContent(
      "0/5 representative frames",
    );
  });

  it("imports video with optional SRT and AirData alignment inputs", async () => {
    renderWorkspace();
    await screen.findByText("Managed videos");

    const video = new File(["video"], "whale.mp4", { type: "video/mp4" });
    const srt = new File(["1"], "whale.srt", { type: "application/x-subrip" });
    const airdata = new File(["time(millisecond)"], "flight.csv", {
      type: "text/csv",
    });

    fireEvent.change(screen.getByLabelText("Video file"), {
      target: { files: [video] },
    });
    fireEvent.change(screen.getByLabelText("DJI SRT telemetry (optional)"), {
      target: { files: [srt] },
    });
    fireEvent.change(
      screen.getByLabelText("AirData CSV telemetry (optional)"),
      {
        target: { files: [airdata] },
      },
    );
    fireEvent.change(
      await screen.findByLabelText("AirData time offset (seconds)"),
      {
        target: { value: "6.19" },
      },
    );
    fireEvent.change(screen.getByLabelText("Alignment evidence"), {
      target: { value: "source-only SRT/AirData alignment" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Import video" }));

    await waitFor(() =>
      expect(api.importVideo).toHaveBeenCalledWith(project.id, video, {
        telemetryFile: srt,
        airdataFile: airdata,
        airdataTimeOffsetSeconds: 6.19,
        airdataTimeOffsetEvidence: "source-only SRT/AirData alignment",
      }),
    );
  });

  it("blocks a nonzero AirData offset without evidence", async () => {
    renderWorkspace();
    await screen.findByText("Managed videos");

    const video = new File(["video"], "whale.mp4", { type: "video/mp4" });
    const airdata = new File(["time(millisecond)"], "flight.csv", {
      type: "text/csv",
    });

    fireEvent.change(screen.getByLabelText("Video file"), {
      target: { files: [video] },
    });
    fireEvent.change(
      screen.getByLabelText("AirData CSV telemetry (optional)"),
      {
        target: { files: [airdata] },
      },
    );
    fireEvent.change(
      await screen.findByLabelText("AirData time offset (seconds)"),
      {
        target: { value: "6.19" },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Import video" }));

    expect(
      await screen.findByText(
        "Nonzero AirData time offsets require alignment evidence",
      ),
    ).toBeInTheDocument();
    expect(api.importVideo).not.toHaveBeenCalled();
  });

  it("shows managed video, frame, track, and automated tracking sections", async () => {
    renderWorkspace();

    expect(await screen.findByText("Managed videos")).toBeInTheDocument();
    expect(screen.getByText("Source-coordinate overlay")).toBeInTheDocument();
    expect(screen.getByText("Identities and keyframes")).toBeInTheDocument();
    expect(screen.getByText("Detector + tracker")).toBeInTheDocument();
    expect(
      await screen.findByText("Geographic observations"),
    ).toBeInTheDocument();
    expect(await screen.findByText(/fish\.mp4/)).toBeInTheDocument();
    expect(await screen.findByText(/300 frames/)).toBeInTheDocument();
  });
  it("seeks the video from map selection and ignores stale pre-seek playback updates", async () => {
    renderWorkspace();

    await screen.findByText(/fish\.mp4/);

    const mapPanel = await screen.findByTestId("mock-georeferenced-map-panel");

    expect(mapPanel).toBeInTheDocument();

    const video = document.querySelector("video") as HTMLVideoElement | null;

    expect(video).not.toBeNull();

    fireEvent.click(
      screen.getByRole("button", {
        name: "Select map observation",
      }),
    );

    expect(screen.getByTestId("mock-active-map-frame")).toHaveTextContent("42");

    expect(video?.currentTime).toBeCloseTo(1.4);

    if (!video) {
      throw new Error("Expected managed video element");
    }

    video.currentTime = 0.2;

    fireEvent.timeUpdate(video);

    expect(screen.getByTestId("mock-active-map-frame")).toHaveTextContent("42");

    video.currentTime = 1.4;

    fireEvent.timeUpdate(video);

    expect(screen.getByTestId("mock-active-map-frame")).toHaveTextContent("42");

    video.currentTime = 2;

    fireEvent.timeUpdate(video);

    expect(screen.getByTestId("mock-active-map-frame")).toHaveTextContent("60");
  });

  it("connects geographic segment seeking to video and map without refetching analytics", async () => {
    vi.mocked(api.getVideoTracks).mockResolvedValue([
      {
        id: "track-1",
        video_id: "video-1",
        label_class_id: "class-1",
        track_number: 1,
        geometry_kind: "bbox",
        keyframes_json: [
          {
            frame: 10,
            bbox: [10, 10, 30, 30],
            confidence: null,
          },
        ],
        interpolation: "linear",
        status: "verified",
        source_model_id: null,
        source_job_id: null,
        metadata_json: null,
        revision: 1,
      },
    ]);

    const location = {
      latitude_deg: 32.75,
      longitude_deg: -79.93,
      crs: "EPSG:4326",
    };

    const geographicData: GeographicTrackAnalytics = {
      track_id: "track-1",
      video_asset_id: "video-1",
      observation_count: 2,
      segment_count: 1,
      first_frame_index: 10,
      last_frame_index: 20,
      first_frame_time_s: 1,
      last_frame_time_s: 2,
      elapsed_time_s: 1,
      total_distance_m: 5,
      net_displacement_m: 5,
      mean_speed_m_s: 5,
      max_segment_speed_m_s: 5,
      start_location: location,
      end_location: location,
      segments: [
        {
          track_id: "track-1",
          video_asset_id: "video-1",
          start_observation_id: "observation-10",
          end_observation_id: "observation-20",
          start_frame_index: 10,
          end_frame_index: 20,
          start_frame_time_s: 1,
          end_frame_time_s: 2,
          elapsed_time_s: 1,
          start_location: location,
          end_location: location,
          distance_m: 5,
          speed_m_s: 5,
          cumulative_distance_m: 5,
          speed_valid: true,
          invalid_reason: null,
        },
      ],
    };

    vi.mocked(geographicApi.getVideoTrackGeographicAnalytics).mockResolvedValue(
      geographicData,
    );

    const { container } = renderWorkspace();

    await screen.findByRole("option", {
      name: /Track 1/,
    });

    const selector = screen.getByLabelText(
      "Existing track",
    ) as HTMLSelectElement;

    expect(
      geographicApi.getVideoTrackGeographicAnalytics,
    ).not.toHaveBeenCalled();

    fireEvent.change(selector, {
      target: { value: "track-1" },
    });

    const seekButton = await screen.findByRole("button", {
      name: "Seek to frame 20",
    });

    await waitFor(() => {
      expect(
        geographicApi.getVideoTrackGeographicAnalytics,
      ).toHaveBeenCalledTimes(1);
    });

    expect(geographicApi.getVideoTrackGeographicAnalytics).toHaveBeenCalledWith(
      "track-1",
      expect.any(AbortSignal),
    );

    const video = container.querySelector("video");

    expect(video).not.toBeNull();

    if (!video) {
      throw new Error("Expected managed video element was not rendered.");
    }

    // Segment navigation must use the persisted endpoint's
    // frame index and timestamp through the Task 15 handler.

    fireEvent.click(seekButton);

    expect(video.currentTime).toBe(2);

    expect(screen.getByTestId("mock-active-map-frame")).toHaveTextContent("20");

    expect(
      screen
        .getByTestId("geographic-movement-analytics-panel")
        .querySelector('tr[data-active-segment="true"]'),
    ).not.toBeNull();

    expect(selector.value).toBe("track-1");

    expect(
      geographicApi.getVideoTrackGeographicAnalytics,
    ).toHaveBeenCalledTimes(1);

    // Existing map selection must still use the same seek path.

    fireEvent.click(
      screen.getByRole("button", {
        name: "Select map observation",
      }),
    );

    expect(video.currentTime).toBe(1.4);

    expect(screen.getByTestId("mock-active-map-frame")).toHaveTextContent("42");

    expect(
      screen
        .getByTestId("geographic-movement-analytics-panel")
        .querySelector('tr[data-active-segment="true"]'),
    ).toBeNull();

    // Seeking or playback must never change the explicit
    // selected track or request analytics again.

    fireEvent.seeked(video);

    video.currentTime = 3;
    fireEvent.timeUpdate(video);

    expect(selector.value).toBe("track-1");

    expect(
      geographicApi.getVideoTrackGeographicAnalytics,
    ).toHaveBeenCalledTimes(1);
  });
});
