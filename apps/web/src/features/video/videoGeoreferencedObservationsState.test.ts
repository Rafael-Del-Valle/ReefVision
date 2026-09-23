import { describe, expect, it } from "vitest";

import type {
  GeoReferencedObservationDetail,
  GeoReferencedObservationSummary,
} from "./videoGeoreferencedObservationsApi";

import {
  createGeoMapState,
  geoMapReducer,
  groupGeoObservationsByTrack,
  toGeoMapPoint,
} from "./videoGeoreferencedObservationsState";

function summary(
  id: string,
  frameIndex: number,
  trackId: string | null,
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

function detail(id: string): GeoReferencedObservationDetail {
  return {
    schema_version: "geo-referenced-observation-0001",
    id,
    project_id: "project-1",
    video_asset_id: "video-1",
    detection_id: null,
    track_id: "track-1",
    frame_index: 1,
    frame_width_px: 100,
    frame_height_px: 60,
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
    timestamp: {
      frame_time_s: 0.1,
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
      sample_index: 1,
      synchronization_method: "nearest",
      telemetry_time_s: 0.1,
      telemetry_utc: null,
      signed_time_delta_ms: 0,
      absolute_time_error_ms: 0,
      within_sync_tolerance: true,
      sync_tolerance_ms: 100,
      field_provenance: {},
    },
    location: {
      latitude_deg: 32.750001,
      longitude_deg: -79.929999,
      crs: "EPSG:4326",
    },
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

describe("georeferenced observation map state", () => {
  it("preserves authoritative coordinates when creating a map point", () => {
    const observation = summary("observation-1", 12, "track-1");

    const point = toGeoMapPoint(observation);

    expect(point).toEqual({
      observationId: "observation-1",
      trackId: "track-1",
      frameIndex: 12,
      frameTimeSeconds: 1.2,
      latitude: observation.location.latitude_deg,
      longitude: observation.location.longitude_deg,
      uncertaintyAvailable: false,
    });
  });

  it("groups tracked observations and preserves untracked observations", () => {
    const groups = groupGeoObservationsByTrack([
      summary("track-frame-2", 2, "track-1"),
      summary("untracked", 5, null),
      summary("track-frame-1", 1, "track-1"),
    ]);

    expect(
      groups.tracked.get("track-1")?.map((item) => item.frame_index),
    ).toEqual([1, 2]);

    expect(groups.untracked.map((item) => item.id)).toEqual(["untracked"]);
  });

  it("retains existing observations if a refresh fails", () => {
    let state = createGeoMapState();

    state = geoMapReducer(state, {
      type: "collection-success",
      observations: [summary("observation-1", 1, "track-1")],
    });

    state = geoMapReducer(state, {
      type: "collection-loading",
    });

    state = geoMapReducer(state, {
      type: "collection-error",
      error: "Network unavailable",
    });

    expect(state.observations).toHaveLength(1);

    expect(state.collectionStatus).toBe("error");

    expect(state.collectionError).toBe("Network unavailable");
  });

  it("ignores stale point-detail responses after selection changes", () => {
    let state = createGeoMapState();

    state = geoMapReducer(state, {
      type: "select-observation",
      observationId: "A",
      requestId: 1,
    });

    state = geoMapReducer(state, {
      type: "select-observation",
      observationId: "B",
      requestId: 2,
    });

    state = geoMapReducer(state, {
      type: "detail-success",
      observationId: "A",
      requestId: 1,
      observation: detail("A"),
    });

    expect(state.selectedObservationId).toBe("B");

    expect(state.selectedObservation).toBeNull();

    expect(state.detailStatus).toBe("loading");
  });

  it("caches successful detail and reuses it on later selection", () => {
    let state = createGeoMapState();

    state = geoMapReducer(state, {
      type: "select-observation",
      observationId: "A",
      requestId: 1,
    });

    const observation = detail("A");

    state = geoMapReducer(state, {
      type: "detail-success",
      observationId: "A",
      requestId: 1,
      observation,
    });

    state = geoMapReducer(state, {
      type: "clear-selection",
    });

    state = geoMapReducer(state, {
      type: "select-observation",
      observationId: "A",
      requestId: 2,
    });

    expect(state.selectedObservation).toEqual(observation);

    expect(state.detailStatus).toBe("success");

    expect(state.activeDetailRequestId).toBeNull();
  });
});
