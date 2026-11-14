import { getApiBaseUrl } from "../../runtime";

export interface GeoBoundingBoxPixels {
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
}

export interface GeoRepresentativePixel {
  x: number;
  y: number;
  method: string;
}

export interface GeoLocation {
  latitude_deg: number;
  longitude_deg: number;
  crs: string;
}

export interface GeoReferencedObservationSummary {
  id: string;
  project_id: string;
  video_asset_id: string;
  track_id: string | null;
  detection_id: string | null;
  frame_index: number;
  frame_width_px: number;
  frame_height_px: number;
  frame_time_s: number;
  bbox: GeoBoundingBoxPixels;
  representative_pixel: GeoRepresentativePixel;
  location: GeoLocation;
  uncertainty_available: boolean;
  is_stale?: boolean;
  method_version: string;
  created_at: string;
}

export interface GeoReferencedObservationListResponse {
  items: GeoReferencedObservationSummary[];
  count: number;
}

export interface GeoReferencedObservationRecomputeResponse {
  video_id: string;
  configuration_hash: string | null;
  invalidated_count: number;
  stale_count: number;
  recomputed_count: number;
  unchanged_count: number;
}

export interface GeoObservationTimestamp {
  frame_time_s: number;
  utc: string | null;
  source: string;
  fps: number;
}

export interface GeoPlatformPose {
  latitude_deg: number;
  longitude_deg: number;
  altitude_m: number | null;
  altitude_datum: string | null;
  height_above_surface_m: number | null;
  yaw_deg: number | null;
  pitch_deg: number | null;
  roll_deg: number | null;
  heading_reference: string | null;
}

export interface GeoCameraPose {
  yaw_deg: number | null;
  pitch_deg: number | null;
  roll_deg: number | null;
  orientation_source: string | null;
}

export interface GeoObservationPose {
  platform: GeoPlatformPose;
  camera: GeoCameraPose;
}

export interface GeoCalibrationReference {
  calibration_id: string;
  calibration_version: string;
  checksum_sha256: string | null;
  camera_model: string;
  image_width_px: number;
  image_height_px: number;
  focal_length_x_px: number;
  focal_length_y_px: number;
  principal_point_x_px: number;
  principal_point_y_px: number;
  distortion_model: string;
  zoom_state: number | null;
}

export interface GeoTelemetryReference {
  source_id: string;
  source_type: string;
  sample_index: number | null;
  synchronization_method: string;
  telemetry_time_s: number | null;
  telemetry_utc: string | null;
  signed_time_delta_ms: number | null;
  absolute_time_error_ms: number | null;
  within_sync_tolerance: boolean | null;
  sync_tolerance_ms: number | null;
  field_provenance: Record<string, unknown>;
}

export interface GeoGeoreferencingUncertainty {
  available: boolean;
  method: string;
  reason_unavailable: string | null;
  [key: string]: unknown;
}

export interface GeoGeoreferencingMethod {
  name: string;
  version: string;
  surface_model: string;
  representative_pixel_policy_version: string;
  synchronization_version: string;
  pose_convention_version: string;
}

export interface GeoReferencedObservationDetail {
  schema_version: string;
  id: string;
  project_id: string;
  video_asset_id: string;
  detection_id: string | null;
  track_id: string | null;
  frame_index: number;
  frame_width_px: number;
  frame_height_px: number;
  bbox: GeoBoundingBoxPixels;
  representative_pixel: GeoRepresentativePixel;
  timestamp: GeoObservationTimestamp;
  pose: GeoObservationPose;
  calibration: GeoCalibrationReference;
  telemetry: GeoTelemetryReference;
  location: GeoLocation;
  uncertainty: GeoGeoreferencingUncertainty & {
    horizontal_sigma_m?: number | null;
    horizontal_95_m?: number | null;
    major_axis_95_m?: number | null;
    minor_axis_95_m?: number | null;
    major_axis_bearing_deg?: number | null;
    telemetry_component_m?: number | null;
    pose_component_m?: number | null;
    height_component_m?: number | null;
    calibration_component_m?: number | null;
  };
  method: GeoGeoreferencingMethod;
  created_at: string;
}

export interface GeoObservationFilters {
  trackId?: string;
  frameIndex?: number;
}

async function responseError(response: Response): Promise<string> {
  const fallback = `Georeferenced observation request failed with HTTP ${response.status}`;

  try {
    const payload = (await response.json()) as {
      detail?: string;
    };

    return typeof payload.detail === "string" ? payload.detail : fallback;
  } catch {
    return fallback;
  }
}

async function requestGeoJson<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    signal,
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(await responseError(response));
  }

  return (await response.json()) as T;
}

export function getVideoGeoreferencedObservations(
  videoId: string,
  filters: GeoObservationFilters = {},
  signal?: AbortSignal,
): Promise<GeoReferencedObservationListResponse> {
  const parameters = new URLSearchParams();

  if (filters.trackId) {
    parameters.set("track_id", filters.trackId);
  }

  if (filters.frameIndex !== undefined) {
    parameters.set("frame_index", String(filters.frameIndex));
  }

  const query = parameters.toString();

  return requestGeoJson<GeoReferencedObservationListResponse>(
    `/videos/${encodeURIComponent(videoId)}/georeferenced-observations${
      query ? `?${query}` : ""
    }`,
    signal,
  );
}

export function getTrackGeoreferencedObservations(
  trackId: string,
  signal?: AbortSignal,
): Promise<GeoReferencedObservationListResponse> {
  return requestGeoJson<GeoReferencedObservationListResponse>(
    `/video-tracks/${encodeURIComponent(trackId)}/georeferenced-observations`,
    signal,
  );
}

export function getFrameGeoreferencedObservations(
  videoId: string,
  frameIndex: number,
  signal?: AbortSignal,
): Promise<GeoReferencedObservationListResponse> {
  return requestGeoJson<GeoReferencedObservationListResponse>(
    `/videos/${encodeURIComponent(videoId)}/frames/${frameIndex}/georeferenced-observations`,
    signal,
  );
}

export function getGeoreferencedObservation(
  observationId: string,
  signal?: AbortSignal,
): Promise<GeoReferencedObservationDetail> {
  return requestGeoJson<GeoReferencedObservationDetail>(
    `/georeferenced-observations/${encodeURIComponent(observationId)}`,
    signal,
  );
}

export async function recomputeVideoGeoreferencedObservations(
  videoId: string,
): Promise<GeoReferencedObservationRecomputeResponse> {
  const response = await fetch(
    `${getApiBaseUrl()}/videos/${encodeURIComponent(videoId)}/georeferenced-observations/recompute`,
    {
      method: "POST",
      cache: "no-store",
    },
  );

  if (!response.ok) {
    throw new Error(await responseError(response));
  }

  return (await response.json()) as GeoReferencedObservationRecomputeResponse;
}
