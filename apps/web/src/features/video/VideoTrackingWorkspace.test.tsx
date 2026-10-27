import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";
import type {
  VideoWorkspaceCommand,
  VideoWorkspaceContext,
} from "./videoWorkspaceBridge";
import { VideoTrackingWorkspace } from "./VideoTrackingWorkspace";
import * as api from "./videoApi";
import * as geographicApi from "./videoGeographicMovementAnalyticsApi";
import type { GeographicTrackAnalytics } from "./videoGeographicMovementAnalyticsApi";
import * as poseInteropApi from "./poseInteroperabilityApi";

vi.mock("./BehaviorDynamicsPanel", () => ({
  BehaviorDynamicsPanel: ({
    trackId,
    frameIndex,
  }: {
    trackId: string;
    frameIndex: number;
  }) => (
    <section data-testid="mock-behavior-dynamics-panel">
      {trackId} · frame {frameIndex}
    </section>
  ),
}));

vi.mock("./GeoreferencedMapPanel", () => ({
  GeoreferencedMapPanel: ({
    videoId,
    activeFrameIndex,
    showTrackLines,
    onFrameSelect,
  }: {
    videoId: string;
    activeFrameIndex?: number | null;
    showTrackLines?: boolean;
    onFrameSelect?: (frameIndex: number, frameTimeSeconds: number) => void;
  }) => (
    <section
      data-testid="mock-georeferenced-map-panel"
      data-show-track-lines={showTrackLines === false ? "false" : "true"}
    >
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

vi.mock("./poseInteroperabilityApi", async () => {
  const actual = await vi.importActual<
    typeof import("./poseInteroperabilityApi")
  >("./poseInteroperabilityApi");
  return {
    ...actual,
    importPoseInteroperability: vi.fn(),
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
    getVideoFrameSpatialMetrics: vi.fn(),
    getVideoTrackingRuns: vi.fn(),
    getTrackingModels: vi.fn(),
    createVideoTrackingJob: vi.fn(),
    getAnnotatedVideoExports: vi.fn(),
    importVideo: vi.fn(),
    updateVideoTrack: vi.fn(),
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

function renderWorkspace(
  options: {
    onWorkspaceContextChange?: (context: VideoWorkspaceContext | null) => void;
    workspaceCommand?: VideoWorkspaceCommand | null;
    onWorkspaceCommandHandled?: (commandId: number) => void;
  } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  const renderTree = (
    nextOptions: {
      onWorkspaceContextChange?: (
        context: VideoWorkspaceContext | null,
      ) => void;
      workspaceCommand?: VideoWorkspaceCommand | null;
      onWorkspaceCommandHandled?: (commandId: number) => void;
    } = options,
  ) => (
    <QueryClientProvider client={queryClient}>
      <VideoTrackingWorkspace project={project} {...nextOptions} />
    </QueryClientProvider>
  );

  const result = render(renderTree());

  return {
    ...result,
    rerenderWorkspace: (nextOptions: {
      onWorkspaceContextChange?: (
        context: VideoWorkspaceContext | null,
      ) => void;
      workspaceCommand?: VideoWorkspaceCommand | null;
      onWorkspaceCommandHandled?: (commandId: number) => void;
    }) => result.rerender(renderTree(nextOptions)),
  };
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
    vi.mocked(api.getVideoFrameSpatialMetrics).mockResolvedValue({
      video_id: "video-1",
      frame_index: 0,
      object_count: 0,
      mean_nearest_neighbor_distance_pixels: null,
      minimum_nearest_neighbor_distance_pixels: null,
      mean_nearest_neighbor_distance_meters: null,
      minimum_nearest_neighbor_distance_meters: null,
      objects: [],
    });
    vi.mocked(api.getVideoTrackingRuns).mockResolvedValue([]);
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

  it("selects detector and segmenter models for hybrid tracking", async () => {
    const base = {
      project_id: project.id,
      source_filename: "fish.pt",
      managed_path: "projects/project-1/models/fish.pt",
      sha256: "b".repeat(64),
      file_size_bytes: 100,
      framework: "ultralytics",
      provider_name: "ultralytics",
      provider_version: "8.3.228",
      class_map_json: { mapping: { fish: "class-1" } },
      input_size_json: null,
      metadata_json: {},
      notes: null,
      created_at: "2026-10-22T00:00:00Z",
      updated_at: "2026-10-22T00:00:00Z",
    } as const;
    vi.mocked(api.getTrackingModels).mockResolvedValue([
      {
        ...base,
        id: "detector-1",
        purpose: "detector",
        task: "detect",
        display_name: "Fish detector",
      },
      {
        ...base,
        id: "segmenter-1",
        purpose: "segmenter",
        task: "segment",
        display_name: "Fish segmenter",
      },
    ]);
    vi.mocked(api.createVideoTrackingJob).mockResolvedValue({
      id: "job-1",
      status: "queued",
    } as Awaited<ReturnType<typeof api.createVideoTrackingJob>>);
    renderWorkspace();
    const mode = await screen.findByLabelText("Tracking mode");
    fireEvent.change(mode, { target: { value: "hybrid" } });
    expect(await screen.findByLabelText("Detection model")).toHaveValue(
      "detector-1",
    );
    expect(screen.getByLabelText("Segmentation model")).toHaveValue(
      "segmenter-1",
    );
    fireEvent.click(screen.getByRole("button", { name: /Run hybrid/ }));
    await waitFor(() =>
      expect(api.createVideoTrackingJob).toHaveBeenCalledWith(
        "video-1",
        expect.objectContaining({
          tracking_mode: "hybrid",
          model_id: "detector-1",
          segmentation_model_id: "segmenter-1",
          hybrid_match_iou: 0.5,
        }),
      ),
    );
  });

  it("shows managed video, frame, track, and automated tracking sections", async () => {
    renderWorkspace();

    expect(await screen.findByText("Managed videos")).toBeInTheDocument();
    expect(screen.getByText("Source-coordinate overlay")).toBeInTheDocument();
    expect(screen.getByText("Identities and keyframes")).toBeInTheDocument();
    expect(
      screen.getByText("Detection / segmentation / hybrid video tracking"),
    ).toBeInTheDocument();
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

  it("smoke-tests pose prediction review with repeated landmarks and absent keypoints", async () => {
    const poseSchema = {
      schema_version: "pose-landmarks-0001" as const,
      groups: [
        { name: "bell_center", count: 1 },
        { name: "tentacle", count: 2 },
      ],
      expanded_labels: ["bell_center", "tentacle", "tentacle"],
      keypoint_count: 3,
      allows_repeated_labels: true,
    };
    const machineTrack: api.VideoTrackRecord = {
      id: "pose-track-1",
      video_id: "video-1",
      label_class_id: "class-1",
      track_number: 7,
      geometry_kind: "bbox",
      keyframes_json: [
        {
          frame: 0,
          bbox: [100, 120, 300, 260],
          confidence: 0.96,
          keypoints: [
            [200, 220, 0.98],
            [240, 300, 0.84],
            [0, 0, 0],
          ],
        },
      ],
      interpolation: "linear",
      status: "machine_generated",
      source_model_id: "pose-model-1",
      source_job_id: "pose-job-1",
      metadata_json: { pose_landmark_schema: poseSchema },
      revision: 3,
    };

    vi.mocked(api.getVideoTracks).mockResolvedValue([machineTrack]);
    vi.mocked(api.updateVideoTrack).mockImplementation(
      async (_trackId, payload) => ({
        ...machineTrack,
        keyframes_json: payload.keyframes,
        interpolation: payload.interpolation,
        status: payload.status,
        revision: payload.base_revision + 1,
      }),
    );

    renderWorkspace();

    await screen.findByRole("option", { name: /Track 7/ });
    fireEvent.change(screen.getByLabelText("Existing track"), {
      target: { value: machineTrack.id },
    });

    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Enable source-coordinate overlay",
      }),
    );

    expect(await screen.findByText("Pose review editor")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Pose interoperability" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Scientific pose visualization" }),
    ).toBeInTheDocument();
    const slpExport = screen.getByRole("link", { name: "SLEAP SLP" });
    const nwbExport = screen.getByRole("link", { name: "NWB" });
    const cocoExport = screen.getByRole("link", { name: "COCO pose" });
    const dlcExport = screen.getByRole("link", { name: "DeepLabCut CSV" });
    const yoloExport = screen.getByRole("link", {
      name: "Ultralytics pose ZIP",
    });
    expect(slpExport).toHaveAttribute(
      "href",
      expect.stringContaining(
        "/videos/video-1/pose-interoperability/export?format=slp",
      ),
    );
    expect(nwbExport).toHaveAttribute(
      "href",
      expect.stringContaining("format=nwb"),
    );
    expect(cocoExport).toHaveAttribute(
      "href",
      expect.stringContaining("format=coco"),
    );
    expect(dlcExport).toHaveAttribute(
      "href",
      expect.stringContaining("format=dlc_csv"),
    );
    expect(yoloExport).toHaveAttribute(
      "href",
      expect.stringContaining("format=ultralytics_pose"),
    );

    expect(screen.getByText("tentacle 1 / 2")).toBeInTheDocument();
    expect(screen.queryByLabelText("tentacle 2")).not.toBeInTheDocument();

    const stage = screen.getByTestId("pose-stage") as unknown as SVGSVGElement;
    Object.defineProperty(stage, "getBoundingClientRect", {
      configurable: true,
      value: () => ({
        x: 0,
        y: 0,
        left: 0,
        top: 0,
        right: 800,
        bottom: 520,
        width: 800,
        height: 520,
        toJSON: () => ({}),
      }),
    });

    const tentacle = screen.getByLabelText("tentacle 1");
    fireEvent.pointerDown(tentacle, {
      button: 0,
      clientX: 100,
      clientY: 100,
    });
    fireEvent.pointerMove(stage, {
      buttons: 1,
      clientX: 150,
      clientY: 130,
    });
    fireEvent.pointerUp(stage, {
      button: 0,
      clientX: 150,
      clientY: 130,
    });

    expect(screen.getByTestId("selected-landmark-source")).toHaveTextContent(
      "Source: corrected",
    );

    fireEvent.click(screen.getByRole("button", { name: "Save pose" }));

    await waitFor(() => expect(api.updateVideoTrack).toHaveBeenCalledTimes(1));
    const [, payload] = vi.mocked(api.updateVideoTrack).mock.calls[0];

    expect(payload.base_revision).toBe(3);
    expect(payload.keyframes).toHaveLength(1);
    const persisted = payload.keyframes[0];

    expect(persisted.keypoints).toHaveLength(3);
    expect(persisted.keypoints?.[0]).toEqual([200, 220, 0.98]);
    expect(persisted.keypoints?.[1]?.[2]).toBe(0.84);
    expect(persisted.keypoints?.[1]?.[0]).not.toBe(240);
    expect(persisted.keypoints?.[1]?.[1]).not.toBe(300);
    expect(persisted.keypoints?.[2]).toEqual([0, 0, 0]);

    expect(persisted.pose_observations).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          semantic_label: "bell_center",
          occurrence_index: 0,
          source: "model",
        }),
        expect.objectContaining({
          semantic_label: "tentacle",
          occurrence_index: 0,
          confidence: 0.84,
          source: "corrected",
        }),
      ]),
    );
    expect(
      persisted.pose_observations?.some(
        (observation) =>
          observation.semantic_label === "tentacle" &&
          observation.occurrence_index === 1,
      ),
    ).toBe(false);
  });

  it("renders and edits segmentation masks in source-pixel coordinates", async () => {
    const segmentationTrack: api.VideoTrackRecord = {
      id: "segment-track-1",
      video_id: "video-1",
      label_class_id: "class-1",
      track_number: 8,
      geometry_kind: "bbox",
      keyframes_json: [
        {
          frame: 0,
          bbox: [100, 120, 300, 260],
          confidence: 0.91,
          mask_polygons: [
            [
              [110, 130],
              [390, 140],
              [380, 360],
            ],
          ],
        },
      ],
      interpolation: "linear",
      status: "machine_generated",
      source_model_id: "segment-model-1",
      source_job_id: "segment-job-1",
      metadata_json: null,
      revision: 4,
    };

    vi.mocked(api.getVideoTracks).mockResolvedValue([segmentationTrack]);
    vi.mocked(api.updateVideoTrack).mockImplementation(
      async (_trackId, payload) => ({
        ...segmentationTrack,
        keyframes_json: payload.keyframes,
        interpolation: payload.interpolation,
        status: payload.status,
        revision: payload.base_revision + 1,
      }),
    );

    renderWorkspace();

    await screen.findByRole("option", { name: /Track 8/ });
    fireEvent.change(screen.getByLabelText("Existing track"), {
      target: { value: segmentationTrack.id },
    });
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Enable source-coordinate overlay",
      }),
    );

    const renderedMask = await screen.findByLabelText(
      "Segmentation mask 1 for track 8",
    );
    expect(renderedMask).toHaveAttribute("points", "110,130 390,140 380,360");

    const maskEditor = screen.getByLabelText("Mask polygons for frame 0");
    fireEvent.change(maskEditor, {
      target: {
        value: "[[[120,140],[400,150],[390,370]]]",
      },
    });
    fireEvent.blur(maskEditor);
    fireEvent.click(screen.getByRole("button", { name: "Save track" }));

    await waitFor(() => expect(api.updateVideoTrack).toHaveBeenCalledTimes(1));
    expect(api.updateVideoTrack).toHaveBeenCalledWith(
      segmentationTrack.id,
      expect.objectContaining({
        base_revision: 4,
        keyframes: [
          expect.objectContaining({
            frame: 0,
            mask_polygons: [
              [
                [120, 140],
                [400, 150],
                [390, 370],
              ],
            ],
          }),
        ],
      }),
    );
  });

  it("imports external pose data with explicit frame mapping confirmation", async () => {
    vi.mocked(poseInteropApi.importPoseInteroperability).mockResolvedValue({
      schema_version: "pose-interoperability-import-0001",
      video_id: "video-1",
      format: "slp",
      created_track_ids: ["imported-track-1"],
      track_count: 1,
      keyframe_count: 2,
      pose_schema_id: "schema-imported",
      pose_schema_revision: 1,
      used_reefvision_provenance: false,
      warnings: ["Frame mapping confirmed."],
    });

    renderWorkspace();

    expect(
      await screen.findByRole("heading", { name: "Pose interoperability" }),
    ).toBeInTheDocument();

    const poseFile = new File(["pose"], "external.slp", {
      type: "application/octet-stream",
    });
    fireEvent.change(
      screen.getByLabelText("Pose interoperability import file"),
      {
        target: { files: [poseFile] },
      },
    );
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: /I confirm external frame indices correspond to this video/,
      }),
    );
    const importButton = screen.getByRole("button", { name: "Import pose" });
    await waitFor(() => expect(importButton).toBeEnabled());
    expect(
      screen.getByRole("checkbox", {
        name: /I confirm external frame indices correspond to this video/,
      }),
    ).toBeChecked();
    fireEvent.click(importButton);

    await waitFor(() =>
      expect(poseInteropApi.importPoseInteroperability).toHaveBeenCalledWith(
        "video-1",
        "slp",
        poseFile,
        "class-1",
        true,
      ),
    );
    expect(
      await screen.findByText(/Imported 1 track with 2 pose keyframes/),
    ).toBeInTheDocument();
    expect(screen.getByText("Frame mapping confirmed.")).toBeInTheDocument();
  });

  it("clears unsubmitted pose import and frame confirmation when switching videos", async () => {
    const existingVideos = await api.getVideos(project.id);
    vi.mocked(api.getVideos).mockResolvedValue([
      ...existingVideos,
      {
        ...existingVideos[0],
        id: "video-2",
        original_filename: "second-video.mp4",
      },
    ]);
    renderWorkspace();
    expect(
      await screen.findByRole("heading", { name: "Pose interoperability" }),
    ).toBeInTheDocument();

    fireEvent.change(
      screen.getByLabelText("Pose interoperability import file"),
      {
        target: {
          files: [
            new File(["pose"], "unsubmitted.slp", {
              type: "application/octet-stream",
            }),
          ],
        },
      },
    );
    const confirmation = screen.getByRole("checkbox", {
      name: /I confirm external frame indices correspond to this video/,
    });
    fireEvent.click(confirmation);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Import pose" })).toBeEnabled(),
    );
    expect(confirmation).toBeChecked();

    fireEvent.change(screen.getByRole("combobox", { name: "Video" }), {
      target: { value: "video-2" },
    });
    await waitFor(() => expect(confirmation).not.toBeChecked());
    expect(screen.getByRole("button", { name: "Import pose" })).toBeDisabled();
    expect(
      (
        screen.getByLabelText(
          "Pose interoperability import file",
        ) as HTMLInputElement
      ).files,
    ).toHaveLength(0);
    expect(poseInteropApi.importPoseInteroperability).not.toHaveBeenCalled();
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

it("blocks pose inference until the ReefVision landmark schema is saved", async () => {
  vi.mocked(api.getTrackingModels).mockResolvedValue([
    {
      id: "pose-model-unbound",
      project_id: project.id,
      purpose: "detector",
      display_name: "Unbound pose model",
      source_filename: "pose.pt",
      managed_path: "projects/project-1/models/pose.pt",
      sha256: "b".repeat(64),
      file_size_bytes: 100,
      framework: "ultralytics",
      task: "pose",
      provider_name: "ultralytics",
      provider_version: "test",
      class_map_json: {},
      input_size_json: { width: 640, height: 640 },
      metadata_json: { pose_keypoint_shape: [3, 3] },
      notes: null,
      created_at: "2026-10-02T00:00:00Z",
      updated_at: "2026-10-02T00:00:00Z",
    },
  ]);

  renderWorkspace();

  const run = await screen.findByRole("button", {
    name: /Run pose/,
  });
  expect(run).toBeDisabled();
  expect(screen.getByText("Pose landmark schema")).toBeInTheDocument();
});

it("shows SLEAP-NN instance tracking controls without Ultralytics tracker knobs", async () => {
  vi.mocked(api.getTrackingModels).mockResolvedValue([
    {
      id: "sleap-pose-model",
      project_id: project.id,
      purpose: "detector",
      display_name: "Jellyfish SLEAP pose",
      source_filename: "jellyfish-pose.zip",
      managed_path: "projects/project-1/models/sleap.zip",
      sha256: "c".repeat(64),
      file_size_bytes: 100,
      framework: "sleap_nn",
      task: "pose",
      provider_name: "sleap_nn",
      provider_version: "0.3.3",
      class_map_json: {},
      input_size_json: null,
      metadata_json: {
        pose_keypoint_shape: [3, 3],
        pose_landmark_schema: {
          schema_version: "pose-landmarks-0001",
          schema_id: "schema-1",
          schema_revision: 1,
          content_hash: "d".repeat(64),
          groups: [
            { name: "bell_center", count: 1 },
            { name: "tentacle", count: 2 },
          ],
          expanded_labels: ["bell_center", "tentacle", "tentacle"],
          keypoint_count: 3,
          allows_repeated_labels: true,
        },
      },
      notes: null,
      created_at: "2026-10-02T00:00:00Z",
      updated_at: "2026-10-02T00:00:00Z",
    },
  ]);

  renderWorkspace();

  expect(
    await screen.findByText("SLEAP-NN animal-instance tracking"),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/fixed-window OKS\/Hungarian tracking/),
  ).toBeInTheDocument();
  expect(screen.queryByLabelText("Tracker")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Detector IoU")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", {
      name: "Run SLEAP-NN pose + instance tracking",
    }),
  ).toBeEnabled();
});

it("publishes timeline context and handles inspector seek commands without moving scientific ownership", async () => {
  const onWorkspaceContextChange = vi.fn();
  const onWorkspaceCommandHandled = vi.fn();

  const view = renderWorkspace({
    onWorkspaceContextChange,
    onWorkspaceCommandHandled,
  });

  await waitFor(() =>
    expect(onWorkspaceContextChange).toHaveBeenCalledWith(
      expect.objectContaining({
        projectId: project.id,
        selectedVideoId: "video-1",
        selectedVideoFilename: "fish.mp4",
        frameIndex: 0,
        frameCount: 300,
        fps: 30,
      }),
    ),
  );

  view.rerenderWorkspace({
    onWorkspaceContextChange,
    workspaceCommand: {
      id: 1,
      type: "seek_frame",
      frameIndex: 42,
    },
    onWorkspaceCommandHandled,
  });

  await waitFor(() =>
    expect(onWorkspaceCommandHandled).toHaveBeenCalledWith(1),
  );

  await waitFor(() =>
    expect(onWorkspaceContextChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        selectedVideoId: "video-1",
        frameIndex: 42,
      }),
    ),
  );

  expect(await screen.findByTestId("mock-active-map-frame")).toHaveTextContent(
    "42",
  );
});
