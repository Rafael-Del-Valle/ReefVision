import { getApiBaseUrl } from "../../runtime";

export type PoseVisualizationMode =
  "confidence" | "occupancy" | "activity" | "trajectory";

export interface PoseVisualizationRequest {
  grid_rows: number;
  grid_columns: number;
  start_frame?: number;
  end_frame?: number;
  include_predicted: boolean;
  include_uncertain: boolean;
  minimum_landmark_confidence?: number;
}

export interface PoseVisualizationPoint {
  frame_index: number;
  time_s: number;
  semantic_label: string;
  occurrence_index: number;
  x_px: number;
  y_px: number;
  landmark_confidence: number | null;
  visibility_state: string;
  observation_source: string;
  coordinate_kind: "observed" | "predicted";
  landmark_track_id: string | null;
  association_state: string | null;
  verification_state: string | null;
}

export interface PoseVisualizationTrajectory {
  landmark_track_id: string;
  semantic_label: string;
  lifecycle_state: string;
  points: PoseVisualizationPoint[];
  path_length_pixels: number;
  evaluated_seconds: number;
  movement_segment_count: number;
}

export interface PoseVisualizationCell {
  row: number;
  column: number;
  x_min_pixels: number;
  y_min_pixels: number;
  x_max_pixels: number;
  y_max_pixels: number;
  sample_count: number;
  observed_sample_count: number;
  predicted_sample_count: number;
  confidence_sample_count: number;
  mean_landmark_confidence: number | null;
  sample_fraction: number;
  occupied_sampled_frame_count: number;
  occupied_sampled_frame_fraction: number;
  unique_landmark_track_count: number;
  movement_segment_count: number;
  movement_distance_pixels: number;
  movement_duration_seconds: number;
  mean_speed_pixels_per_second: number | null;
  maximum_speed_pixels_per_second: number | null;
}

export interface PoseProviderVisualizationCapabilities {
  provider_name: string | null;
  keypoint_scores_persisted: boolean;
  native_confidence_maps_persisted: boolean;
  part_affinity_fields_persisted: boolean;
  raw_tensor_export_available: boolean;
  reason: string;
}

export interface PosePafAvailability {
  available: boolean;
  provider_name: string | null;
  representation: "part_affinity_fields";
  persistence_state: "not_persisted";
  reason: string;
}

export interface PoseVisualizationResponse {
  schema_version: "pose-visualization-0001";
  parent_video_track_id: string;
  source_track_revision: number;
  video_id: string;
  coordinate_space: "source_pixels";
  video_width_pixels: number;
  video_height_pixels: number;
  fps: number;
  start_frame: number;
  end_frame: number;
  grid_rows: number;
  grid_columns: number;
  sampling_policy: "persisted_canonical_pose_keyframes";
  predicted_coordinate_policy:
    "exclude_occluded_predictions" | "include_occluded_predictions";
  identity_policy: "latest_resolved_temporal_association";
  identity_status: "not_built" | "current" | "stale";
  identity_warning: string | null;
  sampled_frame_count: number;
  spatial_sample_count: number;
  observed_sample_count: number;
  predicted_sample_count: number;
  resolved_identity_sample_count: number;
  unresolved_identity_sample_count: number;
  excluded_missing_coordinate_count: number;
  excluded_filter_count: number;
  activity_segment_count: number;
  cells: PoseVisualizationCell[];
  trajectories: PoseVisualizationTrajectory[];
  provider_capabilities: PoseProviderVisualizationCapabilities;
  paf: PosePafAvailability;
}

async function responseError(response: Response): Promise<string> {
  const fallback = `Pose visualization request failed with HTTP ${response.status}`;
  try {
    const payload = (await response.json()) as { detail?: string };
    return typeof payload.detail === "string" ? payload.detail : fallback;
  } catch {
    return fallback;
  }
}

export async function getPoseVisualization(
  trackId: string,
  payload: PoseVisualizationRequest,
  signal?: AbortSignal,
): Promise<PoseVisualizationResponse> {
  const response = await fetch(
    `${getApiBaseUrl()}/video-tracks/${encodeURIComponent(trackId)}/pose-visualization`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
      cache: "no-store",
    },
  );
  if (!response.ok) throw new Error(await responseError(response));
  return (await response.json()) as PoseVisualizationResponse;
}


export function poseVisualizationExportUrl(
  trackId: string,
  payload: PoseVisualizationRequest,
  format: PoseVisualizationExportFormat,
): string {
  const params = new URLSearchParams({
    format,
    grid_rows: String(payload.grid_rows),
    grid_columns: String(payload.grid_columns),
    include_predicted: String(payload.include_predicted),
    include_uncertain: String(payload.include_uncertain),
  });
  if (payload.start_frame !== undefined) {
    params.set("start_frame", String(payload.start_frame));
  }
  if (payload.end_frame !== undefined) {
    params.set("end_frame", String(payload.end_frame));
  }
  if (payload.minimum_landmark_confidence !== undefined) {
    params.set(
      "minimum_landmark_confidence",
      String(payload.minimum_landmark_confidence),
    );
  }
  return `${getApiBaseUrl()}/video-tracks/${encodeURIComponent(trackId)}/pose-visualization/export?${params.toString()}`;
}
