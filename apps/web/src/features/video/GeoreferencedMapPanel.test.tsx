import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./OpenStreetMapView", () => ({
  OpenStreetMapView: ({
    observations,
    activeObservationId,
    selectedObservationId,
    onObservationSelect,
    onTileFailure,
  }: {
    observations: GeoReferencedObservationSummary[];
    activeObservationId?: string | null;
    selectedObservationId?: string | null;
    onObservationSelect?: (
      observation: GeoReferencedObservationSummary,
    ) => void;
    onTileFailure?: () => void;
  }) => (
    <div
      data-testid="mock-openstreetmap-view"
      data-active-observation-id={activeObservationId ?? ""}
      data-selected-observation-id={selectedObservationId ?? ""}
    >
      <button type="button" onClick={() => onTileFailure?.()}>
        Simulate tile failure
      </button>

      {observations.map((observation) => (
        <button
          key={observation.id}
          type="button"
          aria-label={`OSM observation at frame ${observation.frame_index}`}
          onClick={() => onObservationSelect?.(observation)}
        >
          Frame {observation.frame_index}
        </button>
      ))}
    </div>
  ),
}));

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
    recomputeVideoGeoreferencedObservations: vi.fn(),
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

beforeEach(() => {
  Object.defineProperty(window.navigator, "onLine", {
    configurable: true,
    value: false,
  });
});

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

  it("highlights the playback-active observation and track without loading detail", async () => {
    const first = summary("observation-10", 10, "track-1");

    const second = summary("observation-20", 20, "track-1");

    vi.mocked(api.getVideoGeoreferencedObservations).mockResolvedValue({
      items: [first, second],
      count: 2,
    });

    const { rerender } = render(
      <GeoreferencedMapPanel videoId="video-1" activeFrameIndex={18} />,
    );

    await screen.findByRole("button", {
      name: "Observation at frame 20",
    });

    expect(
      document.querySelector('[data-active-observation-id="observation-20"]'),
    ).not.toBeNull();

    expect(
      document.querySelector(
        'polyline[data-track-id="track-1"][data-active-track="true"]',
      ),
    ).not.toBeNull();

    expect(api.getGeoreferencedObservation).not.toHaveBeenCalled();

    rerender(<GeoreferencedMapPanel videoId="video-1" activeFrameIndex={11} />);

    await waitFor(() => {
      expect(
        document.querySelector('[data-active-observation-id="observation-10"]'),
      ).not.toBeNull();
    });

    expect(api.getGeoreferencedObservation).not.toHaveBeenCalled();
  });

  it("shows selected observation uncertainty without refetching on playback", async () => {
    const observation = summary("observation-17", 12);

    vi.mocked(api.getVideoGeoreferencedObservations).mockResolvedValue({
      items: [observation],
      count: 1,
    });

    vi.mocked(api.getGeoreferencedObservation).mockResolvedValue(
      detail(observation),
    );

    const { rerender } = render(
      <GeoreferencedMapPanel videoId="video-1" activeFrameIndex={10} />,
    );

    expect(
      screen.queryByTestId("georeferencing-uncertainty-panel"),
    ).not.toBeInTheDocument();

    const point = await screen.findByRole("button", {
      name: "Observation at frame 12",
    });

    fireEvent.click(point);

    const panel = await screen.findByTestId("georeferencing-uncertainty-panel");

    expect(panel).toHaveAttribute("data-uncertainty-available", "false");

    expect(panel).toHaveTextContent(
      "Formal positional uncertainty: Not estimated",
    );

    expect(panel).toHaveTextContent("Test observation.");

    expect(panel).toHaveTextContent("Uncertainty method");

    expect(panel).toHaveTextContent("Calibration version");

    expect(api.getGeoreferencedObservation).toHaveBeenCalledTimes(1);

    // Playback should affect the active map observation, not
    // the selected-detail request or its uncertainty panel.
    rerender(<GeoreferencedMapPanel videoId="video-1" activeFrameIndex={20} />);

    expect(
      screen.getByTestId("georeferencing-uncertainty-panel"),
    ).toHaveTextContent("Formal positional uncertainty: Not estimated");

    expect(api.getGeoreferencedObservation).toHaveBeenCalledTimes(1);
  });
});

describe("Task 17E selected uncertainty overlay", () => {
  it("renders persisted 95% geometry and preserves it during playback", async () => {
    // TASK17E_RESET_MOCKS: isolate calls and one-time implementations.
    vi.mocked(api.getVideoGeoreferencedObservations).mockReset();
    vi.mocked(api.getGeoreferencedObservation).mockReset();

    const first = summary("overlay-first", 10);
    const second = summary("overlay-second", 20);
    const firstDetail = detail(first);
    const secondDetail = detail(second);

    vi.mocked(api.getVideoGeoreferencedObservations).mockResolvedValue({
      items: [first, second],
      count: 2,
    });

    vi.mocked(api.getGeoreferencedObservation)
      .mockResolvedValueOnce({
        ...firstDetail,
        uncertainty: {
          ...firstDetail.uncertainty,
          available: true,
          method: "empirical_validation",
          reason_unavailable: null,
          horizontal_95_m: 10,
        },
      })
      .mockResolvedValueOnce({
        ...secondDetail,
        uncertainty: {
          ...secondDetail.uncertainty,
          available: false,
          horizontal_95_m: 10,
        },
      });

    const { rerender } = render(
      <GeoreferencedMapPanel videoId="video-1" activeFrameIndex={10} />,
    );

    expect(
      screen.queryByTestId("georeferenced-uncertainty-radius"),
    ).not.toBeInTheDocument();

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Observation at frame 10",
      }),
    );

    const overlay = await screen.findByTestId(
      "georeferenced-uncertainty-radius",
    );

    expect(overlay).toHaveAttribute("data-observation-id", "overlay-first");
    expect(overlay).toHaveAttribute("data-radius-meters", "10");

    const horizontal = Number(overlay.getAttribute("rx"));
    const vertical = Number(overlay.getAttribute("ry"));

    expect(horizontal).toBeGreaterThan(0);
    expect(vertical).toBeGreaterThan(0);
    expect(horizontal).not.toBeCloseTo(vertical);

    expect(api.getGeoreferencedObservation).toHaveBeenCalledTimes(1);

    rerender(<GeoreferencedMapPanel videoId="video-1" activeFrameIndex={20} />);

    expect(
      screen.getByTestId("georeferenced-uncertainty-radius"),
    ).toHaveAttribute("data-observation-id", "overlay-first");

    expect(api.getGeoreferencedObservation).toHaveBeenCalledTimes(1);

    fireEvent.click(
      screen.getByRole("button", {
        name: "Observation at frame 20",
      }),
    );

    await screen.findByText("Test observation.");

    expect(
      screen.queryByTestId("georeferenced-uncertainty-radius"),
    ).not.toBeInTheDocument();

    expect(api.getGeoreferencedObservation).toHaveBeenCalledTimes(2);
    expect(api.getVideoGeoreferencedObservations).toHaveBeenCalledTimes(1);
  });

  it("does not draw a radius when an available detail lacks its value", async () => {
    // TASK17E_RESET_MOCKS: isolate calls and one-time implementations.
    vi.mocked(api.getVideoGeoreferencedObservations).mockReset();
    vi.mocked(api.getGeoreferencedObservation).mockReset();

    const first = summary("overlay-missing", 10);
    const second = summary("overlay-reference", 20);
    const firstDetail = detail(first);

    vi.mocked(api.getVideoGeoreferencedObservations).mockResolvedValue({
      items: [first, second],
      count: 2,
    });

    vi.mocked(api.getGeoreferencedObservation).mockResolvedValue({
      ...firstDetail,
      uncertainty: {
        ...firstDetail.uncertainty,
        available: true,
        method: "propagated_1sigma",
        reason_unavailable: null,
        horizontal_95_m: null,
      },
    });

    render(<GeoreferencedMapPanel videoId="video-1" />);

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Observation at frame 10",
      }),
    );

    await screen.findByTestId("georeferencing-numeric-uncertainty");

    expect(
      screen.queryByTestId("georeferenced-uncertainty-radius"),
    ).not.toBeInTheDocument();

    expect(api.getGeoreferencedObservation).toHaveBeenCalledTimes(1);
  });

  it("uses persisted detail rather than the summary availability flag", async () => {
    // TASK17E_RESET_MOCKS: isolate calls and one-time implementations.
    vi.mocked(api.getVideoGeoreferencedObservations).mockReset();
    vi.mocked(api.getGeoreferencedObservation).mockReset();

    const first = {
      ...summary("overlay-summary", 10),
      uncertainty_available: true,
    };
    const second = summary("overlay-reference", 20);
    const firstDetail = detail(first);

    vi.mocked(api.getVideoGeoreferencedObservations).mockResolvedValue({
      items: [first, second],
      count: 2,
    });

    vi.mocked(api.getGeoreferencedObservation).mockResolvedValue({
      ...firstDetail,
      uncertainty: {
        ...firstDetail.uncertainty,
        available: false,
        horizontal_95_m: 10,
      },
    });

    render(<GeoreferencedMapPanel videoId="video-1" />);

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Observation at frame 10",
      }),
    );

    const panel = await screen.findByTestId("georeferencing-uncertainty-panel");

    expect(panel).toHaveAttribute("data-uncertainty-available", "false");

    expect(
      screen.queryByTestId("georeferenced-uncertainty-radius"),
    ).not.toBeInTheDocument();

    expect(api.getGeoreferencedObservation).toHaveBeenCalledTimes(1);
  });
});

describe("Task 17F uncertainty legend", () => {
  beforeEach(() => {
    vi.mocked(api.getVideoGeoreferencedObservations).mockReset();
    vi.mocked(api.getGeoreferencedObservation).mockReset();
  });

  it("explains the persisted radius when the overlay appears", async () => {
    const first = summary("legend-first", 10);
    const second = summary("legend-second", 20);
    const firstDetail = detail(first);

    vi.mocked(api.getVideoGeoreferencedObservations).mockResolvedValue({
      items: [first, second],
      count: 2,
    });

    vi.mocked(api.getGeoreferencedObservation).mockResolvedValue({
      ...firstDetail,
      uncertainty: {
        ...firstDetail.uncertainty,
        available: true,
        method: "empirical_validation",
        reason_unavailable: null,
        horizontal_95_m: 10,
      },
    });

    render(<GeoreferencedMapPanel videoId="video-1" />);

    const legend = await screen.findByTestId(
      "georeferenced-uncertainty-legend",
    );

    expect(legend).toHaveAttribute("data-uncertainty-overlay", "hidden");

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Observation at frame 10",
      }),
    );

    await screen.findByTestId("georeferenced-uncertainty-radius");

    expect(legend).toHaveAttribute("data-uncertainty-overlay", "shown");
    expect(legend).toHaveTextContent(
      "persisted 95% horizontal uncertainty radius",
    );
    expect(legend).toHaveTextContent(
      "not independently validated geographic accuracy",
    );
  });

  it("explains why no overlay is shown without available uncertainty", async () => {
    const first = summary("legend-unavailable", 10);
    const second = summary("legend-reference", 20);
    const firstDetail = detail(first);

    vi.mocked(api.getVideoGeoreferencedObservations).mockResolvedValue({
      items: [first, second],
      count: 2,
    });

    vi.mocked(api.getGeoreferencedObservation).mockResolvedValue({
      ...firstDetail,
      uncertainty: {
        ...firstDetail.uncertainty,
        available: false,
        horizontal_95_m: 10,
      },
    });

    render(<GeoreferencedMapPanel videoId="video-1" />);

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Observation at frame 10",
      }),
    );

    await screen.findByTestId("georeferencing-uncertainty-panel");

    const legend = screen.getByTestId("georeferenced-uncertainty-legend");

    expect(legend).toHaveAttribute("data-uncertainty-overlay", "hidden");
    expect(legend).toHaveTextContent(
      "temporal synchronization is not geographic accuracy",
    );

    expect(
      screen.queryByTestId("georeferenced-uncertainty-radius"),
    ).not.toBeInTheDocument();
  });
});

describe("Map enhancement M2", () => {
  beforeEach(() => {
    vi.mocked(api.getVideoGeoreferencedObservations).mockReset();

    vi.mocked(api.getGeoreferencedObservation).mockReset();

    Object.defineProperty(window.navigator, "onLine", {
      configurable: true,
      value: true,
    });
  });

  it("uses OpenStreetMap by default and falls back when tiles fail", async () => {
    const first = summary("osm-first", 10);
    const second = summary("osm-second", 20);

    vi.mocked(api.getVideoGeoreferencedObservations).mockResolvedValue({
      items: [first, second],
      count: 2,
    });

    render(<GeoreferencedMapPanel videoId="video-osm" />);

    expect(
      await screen.findByTestId("mock-openstreetmap-view"),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("button", {
        name: "OpenStreetMap",
      }),
    ).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(
      screen.getByRole("button", {
        name: "Simulate tile failure",
      }),
    );

    expect(
      await screen.findByTestId("georeferenced-scientific-plot"),
    ).toBeInTheDocument();

    expect(screen.getByTestId("osm-offline-fallback")).toHaveTextContent(
      "OpenStreetMap tiles could not be loaded",
    );

    expect(
      screen.getByRole("button", {
        name: "Scientific plot",
      }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("allows manual switching between map views", async () => {
    const first = summary("manual-first", 10);
    const second = summary("manual-second", 20);

    vi.mocked(api.getVideoGeoreferencedObservations).mockResolvedValue({
      items: [first, second],
      count: 2,
    });

    render(<GeoreferencedMapPanel videoId="video-manual" />);

    await screen.findByTestId("mock-openstreetmap-view");

    fireEvent.click(
      screen.getByRole("button", {
        name: "Scientific plot",
      }),
    );

    expect(
      screen.getByTestId("georeferenced-scientific-plot"),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name: "OpenStreetMap",
      }),
    );

    expect(
      await screen.findByTestId("mock-openstreetmap-view"),
    ).toBeInTheDocument();

    expect(
      screen.queryByTestId("osm-offline-fallback"),
    ).not.toBeInTheDocument();
  });
});

describe("Georeferenced map class filters and recomputation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(window.navigator, "onLine", {
      configurable: true,
      value: false,
    });
  });

  it("filters mapped observations by class and restores all observations", async () => {
    const whale = summary("whale-observation", 10, "track-whale");
    const dolphin = summary("dolphin-observation", 20, "track-dolphin");

    vi.mocked(api.getVideoGeoreferencedObservations).mockResolvedValue({
      items: [whale, dolphin],
      count: 2,
    });

    render(
      <GeoreferencedMapPanel
        videoId="video-classes"
        classOptions={[
          { id: "class-whale", name: "Whale" },
          { id: "class-dolphin", name: "Dolphin" },
        ]}
        trackClassById={{
          "track-whale": "class-whale",
          "track-dolphin": "class-dolphin",
        }}
      />,
    );

    await screen.findByRole("button", {
      name: "Observation at frame 10",
    });

    fireEvent.click(screen.getByRole("button", { name: "Whale" }));

    expect(
      screen.getByRole("button", {
        name: "Observation at frame 10",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Observation at frame 20",
      }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show all" }));

    expect(
      screen.getByRole("button", {
        name: "Observation at frame 20",
      }),
    ).toBeInTheDocument();
  });

  it("recomputes stale geographic observations and refreshes the map", async () => {
    const observation = summary("recompute-observation", 12, "track-1");

    vi.mocked(api.getVideoGeoreferencedObservations).mockResolvedValue({
      items: [observation],
      count: 1,
    });

    vi.mocked(api.recomputeVideoGeoreferencedObservations).mockResolvedValue({
      video_id: "video-recompute",
      configuration_hash: "a".repeat(64),
      invalidated_count: 1,
      stale_count: 1,
      recomputed_count: 1,
      unchanged_count: 0,
    });

    render(<GeoreferencedMapPanel videoId="video-recompute" />);

    await screen.findByRole("button", {
      name: "Observation at frame 12",
    });

    fireEvent.click(
      screen.getByRole("button", {
        name: "Recompute geographic observations",
      }),
    );

    expect(
      await screen.findByText(/Recomputed 1 observation; 0 unchanged/i),
    ).toBeInTheDocument();

    expect(api.recomputeVideoGeoreferencedObservations).toHaveBeenCalledWith(
      "video-recompute",
    );
    expect(api.getVideoGeoreferencedObservations).toHaveBeenCalledTimes(2);
  });
});
