import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { beforeEach, describe, expect, it, vi } from "vitest";

import { GeoreferencedMapPanel } from "./GeoreferencedMapPanel";

import type {
  GeoReferencedObservationDetail,
  GeoReferencedObservationSummary,
} from "./videoGeoreferencedObservationsApi";

import * as api from "./videoGeoreferencedObservationsApi";

vi.mock("./videoGeoreferencedObservationsApi", async () => {
  const actual = await vi.importActual<
    typeof import("./videoGeoreferencedObservationsApi")
  >("./videoGeoreferencedObservationsApi");

  return {
    ...actual,
    getVideoGeoreferencedObservations: vi.fn(),
    getGeoreferencedObservation: vi.fn(),
  };
});

function summary(
  id: string,
  frameIndex: number,
  trackId: string | null = "track-1",
): GeoReferencedObservationSummary {
  return {
    id,
    project_id: "project-1",
    video_asset_id: "video-1",
    track_id: trackId,
    detection_id: null,
    frame_index: frameIndex,
    frame_width_px: 100,
    frame_height_px: 60,
    frame_time_s: frameIndex / 10,
    bbox: {
      x_min: 10,
      y_min: 12,
      x_max: 30,
      y_max: 20,
    },
    representative_pixel: {
      x: 20,
      y: 16,
      method: "bbox_center",
    },
    location: {
      latitude_deg: 32.75 + frameIndex * 0.000001,
      longitude_deg: -79.93 + frameIndex * 0.000001,
      crs: "EPSG:4326",
    },
    uncertainty_available: false,
    method_version: "opencv-dji-enu-flat-wgs84-v1",
    created_at: "2026-09-23T12:00:00Z",
  };
}

function detail(
  observation: GeoReferencedObservationSummary,
): GeoReferencedObservationDetail {
  return {
    schema_version: "geo-referenced-observation-0001",
    id: observation.id,
    project_id: observation.project_id,
    video_asset_id: observation.video_asset_id,
    detection_id: null,
    track_id: observation.track_id,
    frame_index: observation.frame_index,
    frame_width_px: 100,
    frame_height_px: 60,
    bbox: observation.bbox,
    representative_pixel: observation.representative_pixel,
    timestamp: {
      frame_time_s: observation.frame_time_s,
      utc: null,
      source: "frame_index_fps",
      fps: 10,
    },
    pose: {
      platform: {
        latitude_deg: 32.75,
        longitude_deg: -79.93,
        altitude_m: 100,
        altitude_datum: "relative_takeoff",
        height_above_surface_m: 105,
        yaw_deg: null,
        pitch_deg: null,
        roll_deg: null,
        heading_reference: "unknown",
      },
      camera: {
        yaw_deg: 0,
        pitch_deg: -90,
        roll_deg: 0,
        orientation_source: "gimbal_telemetry",
      },
    },
    calibration: {
      calibration_id: "sha256:calibration",
      calibration_version: "1",
      checksum_sha256: null,
      camera_model: "test-camera",
      image_width_px: 100,
      image_height_px: 60,
      focal_length_x_px: 50,
      focal_length_y_px: 50,
      principal_point_x_px: 50,
      principal_point_y_px: 30,
      distortion_model: "none",
      zoom_state: 1,
    },
    telemetry: {
      source_id: "test.srt",
      source_type: "dji_srt",
      sample_index: observation.frame_index,
      synchronization_method: "nearest",
      telemetry_time_s: observation.frame_time_s,
      telemetry_utc: null,
      signed_time_delta_ms: 0,
      absolute_time_error_ms: 0,
      within_sync_tolerance: true,
      sync_tolerance_ms: 100,
      field_provenance: {},
    },
    location: observation.location,
    uncertainty: {
      available: false,
      method: "not_estimated",
      reason_unavailable: "Test observation.",
    },
    method: {
      name: "camera_ray_surface_intersection",
      version: "opencv-dji-enu-flat-wgs84-v1",
      surface_model: "local_horizontal_plane",
      representative_pixel_policy_version: "1.0.0",
      synchronization_version: "nearest-frame-time-v1",
      pose_convention_version: "absolute-gimbal-ned-to-enu-v1",
    },
    created_at: "2026-09-23T12:00:00Z",
  };
}

describe("GeoreferencedMapPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading and then the successful empty state", async () => {
    let resolveRequest!: (value: {
      items: GeoReferencedObservationSummary[];
      count: number;
    }) => void;

    vi.mocked(api.getVideoGeoreferencedObservations).mockReturnValue(
      new Promise((resolve) => {
        resolveRequest = resolve;
      }),
    );

    render(<GeoreferencedMapPanel videoId="video-1" />);

    expect(
      screen.getByText("Loading georeferenced observations..."),
    ).toBeInTheDocument();

    resolveRequest({
      items: [],
      count: 0,
    });

    expect(
      await screen.findByText("No georeferenced observations"),
    ).toBeInTheDocument();
  });

  it("shows an initial error with retry", async () => {
    vi.mocked(api.getVideoGeoreferencedObservations).mockRejectedValue(
      new Error("Network unavailable"),
    );

    render(<GeoreferencedMapPanel videoId="video-1" />);

    expect(
      await screen.findByText("Unable to load georeferenced observations."),
    ).toBeInTheDocument();

    expect(screen.getByText("Network unavailable")).toBeInTheDocument();

    expect(
      screen.getByRole("button", {
        name: "Retry",
      }),
    ).toBeInTheDocument();
  });

  it("selects a point, emits frame selection, and loads provenance detail", async () => {
    const observation = summary("observation-1", 12);

    const onFrameSelect = vi.fn();

    vi.mocked(api.getVideoGeoreferencedObservations).mockResolvedValue({
      items: [observation],
      count: 1,
    });

    vi.mocked(api.getGeoreferencedObservation).mockResolvedValue(
      detail(observation),
    );

    render(
      <GeoreferencedMapPanel videoId="video-1" onFrameSelect={onFrameSelect} />,
    );

    const point = await screen.findByRole("button", {
      name: "Observation at frame 12",
    });

    fireEvent.click(point);

    expect(onFrameSelect).toHaveBeenCalledWith(12, 1.2);

    expect(await screen.findByText("Frame 12")).toBeInTheDocument();

    await waitFor(() =>
      expect(api.getGeoreferencedObservation).toHaveBeenCalledWith(
        "observation-1",
        expect.any(AbortSignal),
      ),
    );

    expect(
      await screen.findByText("Georeferencing details"),
    ).toBeInTheDocument();

    expect(screen.getByText("sha256:calibration")).toBeInTheDocument();

    expect(screen.getByText("test.srt")).toBeInTheDocument();
  });

  it("keeps map points visible when detail loading fails", async () => {
    const observation = summary("observation-1", 12);

    vi.mocked(api.getVideoGeoreferencedObservations).mockResolvedValue({
      items: [observation],
      count: 1,
    });

    vi.mocked(api.getGeoreferencedObservation).mockRejectedValue(
      new Error("Detail unavailable"),
    );

    render(<GeoreferencedMapPanel videoId="video-1" />);

    const point = await screen.findByRole("button", {
      name: "Observation at frame 12",
    });

    fireEvent.click(point);

    expect(
      await screen.findByText("Unable to load observation details."),
    ).toBeInTheDocument();

    expect(screen.getByText("Detail unavailable")).toBeInTheDocument();

    expect(
      screen.getByRole("button", {
        name: "Observation at frame 12",
      }),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("button", {
        name: "Retry details",
      }),
    ).toBeInTheDocument();
  });

  it("retains map points when a refresh fails", async () => {
    const observation = summary("observation-1", 2);

    vi.mocked(api.getVideoGeoreferencedObservations)
      .mockResolvedValueOnce({
        items: [observation],
        count: 1,
      })
      .mockRejectedValueOnce(new Error("Refresh unavailable"));

    render(<GeoreferencedMapPanel videoId="video-1" />);

    expect(
      await screen.findByRole("button", {
        name: "Observation at frame 2",
      }),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name: "Refresh map",
      }),
    );

    expect(
      await screen.findByText(/Could not refresh geographic observations/),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("button", {
        name: "Observation at frame 2",
      }),
    ).toBeInTheDocument();
  });
});
