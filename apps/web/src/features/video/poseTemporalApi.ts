import { getApiBaseUrl } from "../../runtime";

export type PoseVisibilityState =
  | "visible"
  | "occluded"
  | "out_of_frame"
  | "uncertain"
  | "absent";
export type PoseAssociationState =
  | "provisional"
  | "confirmed"
  | "unresolved"
  | "identity_break";

export interface TemporalPoseLandmarkTrack {
  id: string;
  parent_video_track_id: string;
  pose_schema_id: string;
  pose_schema_revision: number;
  semantic_label: string;
  lifecycle_state: "tentative" | "confirmed" | "terminated" | string;
  first_frame: number;
  last_frame: number | null;
  origin: string;
  source_model_id: string | null;
  source_job_id: string | null;
  association_algorithm: string | null;
  association_algorithm_version: string | null;
  association_parameters_json: Record<string, unknown>;
  association_parameters_hash: string | null;
  created_at: string;
  terminated_at: string | null;
}

export interface TemporalPoseObservation {
  id: string;
  observation_series_id: string;
  revision: number;
  supersedes_observation_id: string | null;
  parent_video_track_id: string;
  frame_index: number;
  time_s: number | null;
  pose_schema_id: string;
  pose_schema_revision: number;
  semantic_label: string;
  occurrence_index: number;
  observed_x_px: number | null;
  observed_y_px: number | null;
  predicted_x_px: number | null;
  predicted_y_px: number | null;
  landmark_confidence: number | null;
  visibility_state: PoseVisibilityState;
  observation_source: "model" | "manual" | "corrected" | "import" | string;
  source_model_id: string | null;
  source_job_id: string | null;
  created_at: string;
}

export interface TemporalPoseAssociationDecision {
  id: string;
  observation_id: string;
  decision_revision: number;
  supersedes_decision_id: string | null;
  selected_landmark_track_id: string | null;
  previous_observation_id: string | null;
  association_state: PoseAssociationState;
  association_confidence: number | null;
  verification_state:
    | "unreviewed"
    | "human_confirmed"
    | "human_corrected"
    | string;
  association_source: "tracker" | "human" | "import" | string;
  candidate_margin: number | null;
  total_cost: number | null;
  cost_breakdown_json: Record<string, unknown> | null;
  algorithm: string | null;
  algorithm_version: string | null;
  parameters_hash: string | null;
  created_at: string;
}

export interface TemporalPoseIdentityBreak {
  id: string;
  parent_video_track_id: string;
  predecessor_landmark_track_id: string;
  successor_landmark_track_id: string | null;
  break_after_frame: number;
  successor_start_frame: number | null;
  reason: string;
  decision_confidence: number | null;
  source: "tracker" | "human" | "import" | string;
  human_verified: boolean;
  correction_id: string | null;
  created_at: string;
}

export interface TemporalPoseCorrection {
  id: string;
  parent_video_track_id: string;
  action: string;
  target_type: string;
  target_id: string;
  frame_start: number | null;
  frame_end: number | null;
  reason_code: string | null;
  note: string | null;
  before_json: Record<string, unknown>;
  after_json: Record<string, unknown>;
  actor: string;
  created_at: string;
}

export interface TemporalPoseSummary {
  schema_version: "pose-temporal-summary-0001";
  parent_video_track_id: string;
  landmark_tracks: TemporalPoseLandmarkTrack[];
  observations: TemporalPoseObservation[];
  association_decisions: TemporalPoseAssociationDecision[];
  identity_breaks: TemporalPoseIdentityBreak[];
  corrections: TemporalPoseCorrection[];
}

export interface TemporalPoseBuildResult {
  schema_version: "pose-temporal-build-0001";
  parent_video_track_id: string;
  created_landmark_tracks: number;
  created_observations: number;
  created_association_decisions: number;
  unresolved_associations: number;
  identity_breaks: number;
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
    let message = `Pose tracking request failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string") message = payload.detail;
    } catch {
      // Keep the HTTP fallback.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function getTemporalPoseSummary(
  trackId: string,
  signal?: AbortSignal,
): Promise<TemporalPoseSummary> {
  return request<TemporalPoseSummary>(
    `/video-tracks/${encodeURIComponent(trackId)}/pose-temporal`,
    { signal, cache: "no-store" },
  );
}

export function buildTemporalPoseAssociations(
  trackId: string,
  options: {
    max_gap_frames?: number;
    max_normalized_displacement?: number;
    ambiguity_margin?: number;
    confirm_after_observations?: number;
    replace_existing?: boolean;
  } = {},
): Promise<TemporalPoseBuildResult> {
  return request<TemporalPoseBuildResult>(
    `/video-tracks/${encodeURIComponent(trackId)}/pose-temporal-associations`,
    { method: "POST", body: JSON.stringify(options) },
  );
}

export function correctTemporalPoseAssociation(
  observationId: string,
  payload: {
    selected_landmark_track_id: string | null;
    association_state: PoseAssociationState;
    reason_code?: string | null;
    note?: string | null;
  },
): Promise<TemporalPoseAssociationDecision> {
  return request<TemporalPoseAssociationDecision>(
    `/pose-landmark-observations/${encodeURIComponent(observationId)}/association-corrections`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function createTemporalPoseIdentityBreak(
  landmarkTrackId: string,
  payload: {
    successor_landmark_track_id?: string | null;
    break_after_frame: number;
    successor_start_frame?: number | null;
    reason:
      | "ambiguous_crossing"
      | "occlusion_gap_exceeded"
      | "parent_track_break"
      | "schema_change"
      | "camera_cut"
      | "manual_split"
      | "algorithm_reset"
      | "low_confidence"
      | "out_of_frame_gap"
      | "unknown";
    decision_confidence?: number | null;
    note?: string | null;
  },
): Promise<TemporalPoseIdentityBreak> {
  return request<TemporalPoseIdentityBreak>(
    `/pose-landmark-tracks/${encodeURIComponent(landmarkTrackId)}/identity-breaks`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function temporalPoseExportUrl(
  trackId: string,
  format: "csv" | "json",
): string {
  return `${getApiBaseUrl()}/video-tracks/${encodeURIComponent(trackId)}/pose-temporal/export?format=${format}`;
}
