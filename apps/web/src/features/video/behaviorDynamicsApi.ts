import { getApiBaseUrl } from "../../runtime";

export type BehaviorFeaturePreset =
  | "track_only"
  | "track_pose_geometry"
  | "track_pose_identity";
export type BehaviorExportFormat = "json" | "bouts_csv" | "predictions_csv";

export interface BehaviorStateDefinition {
  id: string;
  ethogram_revision_id: string;
  code: string;
  label: string;
  channel: string;
  description: string | null;
  sort_order: number;
}

export interface BehaviorEthogram {
  id: string;
  ethogram_series_id: string;
  project_id: string;
  revision: number;
  supersedes_revision_id: string | null;
  name: string;
  description: string | null;
  definition_sha256: string;
  created_by: string;
  created_at: string;
  states: BehaviorStateDefinition[];
}

export interface BehaviorBout {
  id: string;
  bout_series_id: string;
  revision: number;
  supersedes_bout_id: string | null;
  video_track_id: string;
  ethogram_revision_id: string;
  behavior_state_id: string;
  behavior_code: string;
  behavior_label: string;
  channel: string;
  start_frame: number;
  end_frame: number;
  start_time_seconds: number;
  end_time_seconds: number;
  duration_seconds: number;
  source: string;
  confidence: number | null;
  review_status: string;
  source_track_revision: number;
  stale_against_track: boolean;
  source_behavior_classifier_id: string | null;
  source_behavior_prediction_id: string | null;
  revision_reason: string;
  note: string | null;
  created_by: string;
  created_at: string;
}

export interface BehaviorStateDynamics {
  behavior_state_id: string;
  behavior_code: string;
  behavior_label: string;
  channel: string;
  bout_count: number;
  dwell_frames: number;
  dwell_seconds: number;
  fraction_of_evaluated_time: number;
  fraction_of_labeled_time: number;
  mean_bout_seconds: number | null;
  maximum_bout_seconds: number | null;
}

export interface BehaviorTransitionDynamics {
  channel: string;
  from_behavior_state_id: string;
  from_behavior_code: string;
  to_behavior_state_id: string;
  to_behavior_code: string;
  count: number;
  probability_from_state: number;
}

export interface BehaviorChannelDynamics {
  channel: string;
  evaluated_frames: number;
  evaluated_seconds: number;
  labeled_frames: number;
  labeled_seconds: number;
  unlabeled_frames: number;
  unlabeled_seconds: number;
  coverage_fraction: number;
  states: BehaviorStateDynamics[];
  transitions: BehaviorTransitionDynamics[];
}

export interface BehaviorDynamics {
  schema_version: "behavior-dynamics-0001";
  track_id: string;
  video_id: string;
  track_number: number;
  ethogram_revision_id: string;
  ethogram_definition_sha256: string;
  start_frame: number;
  end_frame: number;
  fps: number;
  transition_policy: "adjacent-labeled-bouts-only";
  interval_policy: "inclusive-frame-intervals";
  annotation_policy: "verified_only" | "include_unreviewed";
  excluded_unreviewed_bout_count: number;
  provenance_status: "current" | "stale";
  provenance_warning: string | null;
  stale_bout_count: number;
  channels: BehaviorChannelDynamics[];
}

export interface BehaviorModel {
  id: string;
  project_id: string;
  ethogram_revision_id: string;
  channel: string;
  display_name: string;
  algorithm: string;
  algorithm_version: string;
  feature_set_version: string;
  feature_preset: BehaviorFeaturePreset | string;
  feature_names: string[];
  feature_request: Record<string, unknown>;
  scaler: Record<string, unknown>;
  centroids: Record<string, unknown>;
  class_counts: Record<string, number>;
  training_track_ids: string[];
  training_bout_ids: string[];
  training_sample_count: number;
  training_manifest_sha256: string;
  created_by: string;
  created_at: string;
}

export interface BehaviorPrediction {
  id: string;
  video_track_id: string;
  model_id: string;
  ethogram_revision_id: string;
  behavior_state_id: string;
  behavior_code: string;
  behavior_label: string;
  channel: string;
  start_frame: number;
  end_frame: number;
  prediction_score: number;
  score_semantics: "normalized_inverse_distance_not_calibrated";
  scores: Record<string, unknown>;
  feature_vector: Record<string, number>;
  feature_parameters_sha256: string;
  source_track_revision: number;
  stale_against_track: boolean;
  review_status: string;
  accepted_bout_series_id: string | null;
  reviewed_at: string | null;
  reviewed_by: string | null;
  created_at: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = `Behavior request failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string") message = payload.detail;
    } catch {
      // Keep HTTP fallback for non-JSON errors.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function getBehaviorEthograms(
  projectId: string,
  signal?: AbortSignal,
): Promise<BehaviorEthogram[]> {
  return request<BehaviorEthogram[]>(
    `/projects/${encodeURIComponent(projectId)}/behavior-ethograms`,
    { signal },
  );
}

export function createBehaviorEthogram(
  projectId: string,
  payload: {
    name: string;
    description?: string | null;
    states: Array<{
      code: string;
      label: string;
      channel: string;
      description?: string | null;
    }>;
  },
): Promise<BehaviorEthogram> {
  return request<BehaviorEthogram>(
    `/projects/${encodeURIComponent(projectId)}/behavior-ethograms`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function getBehaviorBouts(
  trackId: string,
  ethogramRevisionId: string,
  signal?: AbortSignal,
): Promise<BehaviorBout[]> {
  const query = new URLSearchParams({
    ethogram_revision_id: ethogramRevisionId,
  });
  return request<BehaviorBout[]>(
    `/video-tracks/${encodeURIComponent(trackId)}/behavior-bouts?${query.toString()}`,
    { signal },
  );
}

export function createBehaviorBout(
  trackId: string,
  payload: {
    ethogram_revision_id: string;
    behavior_state_id: string;
    start_frame: number;
    end_frame: number;
    source: "manual";
    note?: string | null;
  },
): Promise<BehaviorBout> {
  return request<BehaviorBout>(
    `/video-tracks/${encodeURIComponent(trackId)}/behavior-bouts`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function getBehaviorDynamics(
  trackId: string,
  ethogramRevisionId: string,
  signal?: AbortSignal,
): Promise<BehaviorDynamics> {
  return request<BehaviorDynamics>(
    `/video-tracks/${encodeURIComponent(trackId)}/behavior-dynamics`,
    {
      method: "POST",
      body: JSON.stringify({
        ethogram_revision_id: ethogramRevisionId,
        include_unreviewed: false,
      }),
      signal,
    },
  );
}

export function getBehaviorModels(
  projectId: string,
  ethogramRevisionId: string,
  signal?: AbortSignal,
): Promise<BehaviorModel[]> {
  const query = new URLSearchParams({
    ethogram_revision_id: ethogramRevisionId,
  });
  return request<BehaviorModel[]>(
    `/projects/${encodeURIComponent(projectId)}/behavior-models?${query.toString()}`,
    { signal },
  );
}

export function trainBehaviorModel(
  projectId: string,
  payload: {
    ethogram_revision_id: string;
    channel: string;
    display_name: string;
    feature_preset: BehaviorFeaturePreset;
    track_ids: string[];
  },
): Promise<BehaviorModel> {
  return request<BehaviorModel>(
    `/projects/${encodeURIComponent(projectId)}/behavior-models`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function getBehaviorPredictions(
  trackId: string,
  modelId?: string,
  signal?: AbortSignal,
): Promise<BehaviorPrediction[]> {
  const query = new URLSearchParams();
  if (modelId) query.set("model_id", modelId);
  const queryString = query.toString();
  const suffix = queryString ? `?${queryString}` : "";
  return request<BehaviorPrediction[]>(
    `/video-tracks/${encodeURIComponent(trackId)}/behavior-predictions${suffix}`,
    { signal },
  );
}

export function runBehaviorPredictions(
  trackId: string,
  payload: {
    model_id: string;
    window_frames: number;
    stride_frames: number;
  },
): Promise<{
  track_id: string;
  model_id: string;
  source_track_revision: number;
  prediction_count: number;
  predictions: BehaviorPrediction[];
}> {
  return request(
    `/video-tracks/${encodeURIComponent(trackId)}/behavior-predictions`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function reviewBehaviorPrediction(
  predictionId: string,
  payload: {
    action: "accept" | "edit_and_accept" | "reject";
    behavior_state_id?: string;
    start_frame?: number;
    end_frame?: number;
    note?: string | null;
  },
): Promise<BehaviorPrediction> {
  return request<BehaviorPrediction>(
    `/behavior-predictions/${encodeURIComponent(predictionId)}/review`,
    { method: "PUT", body: JSON.stringify(payload) },
  );
}

export function behaviorExportUrl(
  trackId: string,
  ethogramRevisionId: string,
  format: BehaviorExportFormat,
  modelId?: string,
): string {
  const query = new URLSearchParams({
    ethogram_revision_id: ethogramRevisionId,
    format,
  });
  if (modelId) query.set("model_id", modelId);
  return `${getApiBaseUrl()}/video-tracks/${encodeURIComponent(trackId)}/behavior-export?${query.toString()}`;
}
