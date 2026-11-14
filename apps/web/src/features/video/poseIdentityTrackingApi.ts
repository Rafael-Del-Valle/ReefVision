import { getApiBaseUrl } from "../../runtime";

export interface PoseIdentityRun {
  id: string;
  project_id: string;
  video_id: string;
  source_model_id: string | null;
  source_job_id: string | null;
  pose_schema_id: string;
  pose_schema_revision: number;
  pose_schema_content_hash: string;
  algorithm: string;
  algorithm_version: string;
  parameters_json: Record<string, unknown>;
  parameters_sha256: string;
  input_manifest_sha256: string;
  source_coordinate_space: string;
  source_width: number;
  source_height: number;
  status: string;
  progress_json: Record<string, unknown>;
  error_json: Record<string, unknown> | null;
  revision: number;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface PoseAnimalIdentity {
  id: string;
  stable_identity_key: string;
  display_name: string | null;
  origin: string;
  verification_state: string;
  lifecycle_state: string;
  first_frame: number;
  last_frame: number | null;
  mean_association_confidence: number | null;
  revision: number;
}

export interface PoseIdentityObservation {
  id: string;
  observation_series_id: string;
  revision: number;
  supersedes_observation_id: string | null;
  animal_identity_id: string | null;
  source_video_track_id: string;
  source_detection_key: string;
  frame_index: number;
  bbox_json: number[];
  landmarks_json: Array<{
    landmark_id: string;
    x: number | null;
    y: number | null;
    confidence: number | null;
    visibility: string;
  }>;
  detection_confidence: number | null;
  association_confidence: number | null;
  visibility_state: string;
  assignment_source: string;
  verification_state: string;
  coordinate_space: string;
  is_current: boolean;
}

export interface PoseIdentityDecision {
  id: string;
  observation_id: string;
  candidate_identity_id: string | null;
  candidate_rank: number;
  selected: boolean;
  passed_gate: boolean;
  gate_reason: string | null;
  total_cost: number;
  acceptance_threshold: number;
  association_confidence: number;
  score_components_json: Record<string, number | null>;
  algorithm: string;
  algorithm_version: string;
  parameters_sha256: string;
}

export interface PoseIdentityCorrection {
  id: string;
  association_run_id: string;
  revision: number;
  action: string;
  target_type: string;
  target_id: string;
  frame_start: number | null;
  frame_end: number | null;
  before_json: Record<string, unknown>;
  after_json: Record<string, unknown>;
  before_sha256: string;
  after_sha256: string;
  reason: string | null;
  actor: string;
  created_at: string;
}

export interface PoseIdentityJob {
  id: string;
  status: string;
  progress_current: number;
  progress_total: number;
  result_json: { run_id?: string; stage?: string } | null;
  error_message: string | null;
}

export type PoseIdentityCorrectionAction =
  "reassign" | "split" | "merge" | "swap" | "accept" | "reject";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, init);
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) message = payload.detail;
    } catch {
      // Keep the status-based fallback for non-JSON failures.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function listPoseIdentityRuns(
  projectId: string,
  signal?: AbortSignal,
): Promise<PoseIdentityRun[]> {
  return requestJson(`/projects/${projectId}/pose-identity-runs`, { signal });
}

export function createPoseIdentityRun(
  projectId: string,
  payload: {
    video_id: string;
    source_track_ids: string[];
    pose_schema_id: string;
    pose_schema_revision: number;
    pose_schema_content_hash: string;
    device: "auto" | "cpu" | "cuda";
    parameters: Record<string, number>;
  },
): Promise<PoseIdentityJob> {
  return requestJson(`/projects/${projectId}/pose-identity-runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getPoseIdentityIdentities(
  runId: string,
  signal?: AbortSignal,
): Promise<PoseAnimalIdentity[]> {
  return requestJson(`/pose-identity-runs/${runId}/identities`, { signal });
}

export function getPoseIdentityObservations(
  runId: string,
  signal?: AbortSignal,
): Promise<PoseIdentityObservation[]> {
  return requestJson(`/pose-identity-runs/${runId}/observations`, { signal });
}

export function getPoseIdentityDecisions(
  runId: string,
  signal?: AbortSignal,
): Promise<PoseIdentityDecision[]> {
  return requestJson(`/pose-identity-runs/${runId}/decisions`, { signal });
}

export function getPoseIdentityReviewQueue(
  runId: string,
  signal?: AbortSignal,
): Promise<PoseIdentityObservation[]> {
  return requestJson(`/pose-identity-runs/${runId}/review-queue`, { signal });
}

export function getPoseIdentityCorrections(
  runId: string,
  signal?: AbortSignal,
): Promise<PoseIdentityCorrection[]> {
  return requestJson(`/pose-identity-runs/${runId}/corrections`, { signal });
}

export function createPoseIdentityCorrection(
  runId: string,
  payload: {
    action: PoseIdentityCorrectionAction;
    target_type: "observation" | "identity" | "range";
    target_id: string;
    destination_identity_id: string | null;
    frame_start: number | null;
    frame_end: number | null;
    reason: string | null;
    actor: string;
  },
): Promise<PoseIdentityCorrection> {
  return requestJson(`/pose-identity-runs/${runId}/corrections`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function cancelPoseIdentityJob(jobId: string): Promise<PoseIdentityJob> {
  return requestJson(`/jobs/${jobId}/cancel`, { method: "POST" });
}

export function poseIdentityExportUrl(
  runId: string,
  format: "json" | "csv",
): string {
  return `${getApiBaseUrl()}/pose-identity-runs/${runId}/export?format=${format}`;
}
