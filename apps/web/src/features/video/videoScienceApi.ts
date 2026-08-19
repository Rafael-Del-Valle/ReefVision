import { getApiBaseUrl } from "../../runtime";

export type VideoDistanceUnit = "mm" | "cm" | "m";

export interface VideoSpatialCalibration {
  schema_version: "video-spatial-calibration-0001";
  video_id: string;
  unit: VideoDistanceUnit;
  reference_distance: number;
  reference_pixels: number;
  pixels_per_unit: number;
  units_per_pixel: number;
  method: string;
  reference_label: string | null;
  notes: string | null;
  calibration_revision: number;
  calibration_updated_at: string;
  video_revision: number;
}

export interface CalibratedTrackAnalytics {
  schema_version: "calibrated-video-track-analytics-0001";
  track_id: string;
  video_id: string;
  track_number: number;
  label_class_id: string;
  first_frame: number;
  last_frame: number;
  observed_frame_count: number;
  duration_seconds: number;
  path_length_pixels: number;
  mean_speed_pixels_per_second: number;
  maximum_speed_pixels_per_second: number;
  displacement_pixels: number;
  distance_unit: VideoDistanceUnit;
  path_length: number;
  mean_speed_per_second: number;
  maximum_speed_per_second: number;
  displacement: number;
  calibration: VideoSpatialCalibration;
}

export interface SchoolingFrameMetrics {
  frame: number;
  timestamp_seconds: number;
  active_track_count: number;
  mean_pairwise_distance_pixels: number;
  mean_nearest_neighbor_distance_pixels: number;
  mean_distance_to_centroid_pixels: number;
  mean_pairwise_distance: number;
  mean_nearest_neighbor_distance: number;
  mean_distance_to_centroid: number;
  mean_speed_pixels_per_second: number | null;
  mean_speed_per_second: number | null;
  polarization: number | null;
}

export interface SchoolingAnalytics {
  schema_version: "video-schooling-analytics-0001";
  video_id: string;
  track_ids: string[];
  start_frame: number;
  end_frame: number;
  trajectory_policy: "configured_track_interpolation";
  frames_evaluated: number;
  mean_group_size: number;
  mean_pairwise_distance_pixels: number;
  mean_nearest_neighbor_distance_pixels: number;
  mean_distance_to_centroid_pixels: number;
  mean_pairwise_distance: number;
  mean_nearest_neighbor_distance: number;
  mean_distance_to_centroid: number;
  mean_speed_pixels_per_second: number | null;
  mean_speed_per_second: number | null;
  mean_polarization: number | null;
  distance_unit: VideoDistanceUnit;
  calibration: VideoSpatialCalibration;
  frames: SchoolingFrameMetrics[];
}

export interface VideoCameraIntrinsics {
  schema_version: "video-camera-intrinsics-0001";
  video_id: string;
  fx_px: number;
  fy_px: number;
  cx_px: number;
  cy_px: number;
  method: string;
  notes: string | null;
  video_revision: number;
}

export interface VideoDepthSample {
  track_id: string;
  frame: number;
  depth: number;
  confidence?: number | null;
}

export interface VideoDepthTrackPoint3D {
  frame: number;
  timestamp_seconds: number;
  center_x_px: number;
  center_y_px: number;
  x: number;
  y: number;
  z: number;
  depth_confidence: number | null;
}

export interface VideoDepthTrack3DAnalytics {
  track_id: string;
  track_number: number;
  label_class_id: string;
  observed_frame_count: number;
  first_frame: number;
  last_frame: number;
  duration_seconds: number;
  path_length_3d: number;
  displacement_3d: number;
  mean_speed_3d_per_second: number;
  maximum_speed_3d_per_second: number;
  mean_depth: number;
  minimum_depth: number;
  maximum_depth: number;
  skipped_gap_count: number;
  points: VideoDepthTrackPoint3D[];
}

export interface VideoDepthTrackAnalytics {
  schema_version: "video-depth-track-analytics-0001";
  video_id: string;
  unit: VideoDistanceUnit;
  camera_intrinsics: VideoCameraIntrinsics;
  tracks: VideoDepthTrack3DAnalytics[];
  warnings: string[];
}

async function errorMessage(
  response: Response,
  fallback: string,
): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string };
    return typeof payload.detail === "string" ? payload.detail : fallback;
  } catch {
    return fallback;
  }
}

export async function getVideoCalibration(
  videoId: string,
  signal?: AbortSignal,
): Promise<VideoSpatialCalibration | null> {
  const response = await fetch(
    `${getApiBaseUrl()}/videos/${encodeURIComponent(videoId)}/calibration`,
    { signal },
  );
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(
      await errorMessage(
        response,
        `Calibration request failed with HTTP ${response.status}`,
      ),
    );
  }
  return (await response.json()) as VideoSpatialCalibration;
}

export async function setVideoCalibration(
  videoId: string,
  payload: {
    unit: VideoDistanceUnit;
    reference_distance: number;
    reference_pixels: number;
    method: string;
    reference_label?: string | null;
    notes?: string | null;
  },
): Promise<VideoSpatialCalibration> {
  const response = await fetch(
    `${getApiBaseUrl()}/videos/${encodeURIComponent(videoId)}/calibration`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    throw new Error(
      await errorMessage(
        response,
        `Calibration update failed with HTTP ${response.status}`,
      ),
    );
  }
  return (await response.json()) as VideoSpatialCalibration;
}

export async function clearVideoCalibration(videoId: string): Promise<void> {
  const response = await fetch(
    `${getApiBaseUrl()}/videos/${encodeURIComponent(videoId)}/calibration`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    throw new Error(
      await errorMessage(
        response,
        `Calibration delete failed with HTTP ${response.status}`,
      ),
    );
  }
}

export async function getCalibratedTrackAnalytics(
  trackId: string,
  signal?: AbortSignal,
): Promise<CalibratedTrackAnalytics> {
  const response = await fetch(
    `${getApiBaseUrl()}/video-tracks/${encodeURIComponent(trackId)}/calibrated-analytics`,
    { signal },
  );
  if (!response.ok) {
    throw new Error(
      await errorMessage(
        response,
        `Calibrated track analytics failed with HTTP ${response.status}`,
      ),
    );
  }
  return (await response.json()) as CalibratedTrackAnalytics;
}

export async function getSchoolingAnalytics(
  videoId: string,
  payload: {
    track_ids: string[];
    start_frame?: number;
    end_frame?: number;
  },
): Promise<SchoolingAnalytics> {
  const response = await fetch(
    `${getApiBaseUrl()}/videos/${encodeURIComponent(videoId)}/schooling-analytics`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    throw new Error(
      await errorMessage(
        response,
        `Schooling analytics failed with HTTP ${response.status}`,
      ),
    );
  }
  return (await response.json()) as SchoolingAnalytics;
}

export async function getVideoCameraIntrinsics(
  videoId: string,
  signal?: AbortSignal,
): Promise<VideoCameraIntrinsics | null> {
  const response = await fetch(
    `${getApiBaseUrl()}/videos/${encodeURIComponent(videoId)}/camera-intrinsics`,
    { signal },
  );
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(
      await errorMessage(
        response,
        `Camera intrinsics request failed with HTTP ${response.status}`,
      ),
    );
  }
  return (await response.json()) as VideoCameraIntrinsics;
}

export async function setVideoCameraIntrinsics(
  videoId: string,
  payload: {
    fx_px: number;
    fy_px: number;
    cx_px: number;
    cy_px: number;
    method: string;
    notes?: string | null;
  },
): Promise<VideoCameraIntrinsics> {
  const response = await fetch(
    `${getApiBaseUrl()}/videos/${encodeURIComponent(videoId)}/camera-intrinsics`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    throw new Error(
      await errorMessage(
        response,
        `Camera intrinsics update failed with HTTP ${response.status}`,
      ),
    );
  }
  return (await response.json()) as VideoCameraIntrinsics;
}

export async function clearVideoCameraIntrinsics(
  videoId: string,
): Promise<void> {
  const response = await fetch(
    `${getApiBaseUrl()}/videos/${encodeURIComponent(videoId)}/camera-intrinsics`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    throw new Error(
      await errorMessage(
        response,
        `Camera intrinsics delete failed with HTTP ${response.status}`,
      ),
    );
  }
}

export async function getDepthTrackAnalytics(
  videoId: string,
  payload: {
    unit: VideoDistanceUnit;
    samples: VideoDepthSample[];
    maximum_frame_gap?: number | null;
  },
): Promise<VideoDepthTrackAnalytics> {
  const response = await fetch(
    `${getApiBaseUrl()}/videos/${encodeURIComponent(videoId)}/depth-track-analytics`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    throw new Error(
      await errorMessage(
        response,
        `3D depth-track analytics failed with HTTP ${response.status}`,
      ),
    );
  }
  return (await response.json()) as VideoDepthTrackAnalytics;
}
