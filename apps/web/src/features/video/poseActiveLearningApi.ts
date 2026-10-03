import { getApiBaseUrl } from "../../runtime";

export type PoseActiveLearningSelectionUnit = "frame" | "clip";

export interface PoseActiveLearningRound {
  id: string;
  project_id: string;
  video_id: string;
  name: string;
  status: string;
  selection_unit: PoseActiveLearningSelectionUnit;
  requested_size: number;
  selected_count: number;
  clip_radius_frames: number;
  minimum_frame_spacing: number;
  model_ids_json: string[];
  scoring_config_json: Record<string, unknown>;
  selection_manifest_json: Record<string, unknown>;
  selection_sha256: string;
  created_by: string;
  created_at: string;
  completed_at: string | null;
}

export interface PoseActiveLearningReviewTarget {
  workspace: "pose_annotation_editor";
  video_id: string;
  video_track_id: string;
  focus_frame: number;
  frame_start: number;
  frame_end: number;
  pose_schema_id: string;
  pose_schema_revision: number;
}

export interface PoseActiveLearningCandidate {
  id: string;
  round_id: string;
  video_track_id: string;
  focus_frame: number;
  frame_start: number;
  frame_end: number;
  acquisition_score: number;
  score_components_json: Record<string, number>;
  reason_codes_json: string[];
  pose_schema_id: string;
  pose_schema_revision: number;
  source_track_revision: number;
  source_model_ids_json: string[];
  source_job_ids_json: string[];
  provenance_json: Record<string, unknown>;
  provenance_sha256: string;
  review_status: string;
  review_started_track_revision: number | null;
  verified_track_revision: number | null;
  verified_pose_sha256: string | null;
  correction_id: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
  review_target: PoseActiveLearningReviewTarget;
}

interface PoseActiveLearningCreatePayload {
  name: string;
  video_id: string;
  track_ids?: string[];
  model_ids?: string[];
  selection_unit: PoseActiveLearningSelectionUnit;
  requested_size: number;
  clip_radius_frames: number;
  minimum_frame_spacing: number;
}

interface PoseActiveLearningReviewPayload {
  action: "start_review" | "verify" | "skip";
  reviewed_by?: string;
  note?: string | null;
  verified_track_revision?: number;
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
    let message = `Pose Active Learning request failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as {
        detail?: string;
      };
      if (typeof payload.detail === "string") {
        message = payload.detail;
      }
    } catch {
      // Keep HTTP fallback.
    }
    throw new Error(message);
  }

  return (await response.json()) as T;
}

export function createPoseActiveLearningRound(
  projectId: string,
  payload: PoseActiveLearningCreatePayload,
): Promise<PoseActiveLearningRound> {
  return request(
    `/projects/${encodeURIComponent(projectId)}/pose-active-learning-rounds`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function getPoseActiveLearningRounds(
  projectId: string,
  videoId: string,
  signal?: AbortSignal,
): Promise<PoseActiveLearningRound[]> {
  const query = new URLSearchParams({
    video_id: videoId,
  });
  return request(
    `/projects/${encodeURIComponent(projectId)}/pose-active-learning-rounds?${query.toString()}`,
    { signal },
  );
}

export function getPoseActiveLearningCandidates(
  roundId: string,
  signal?: AbortSignal,
): Promise<PoseActiveLearningCandidate[]> {
  return request(
    `/pose-active-learning-rounds/${encodeURIComponent(roundId)}/candidates`,
    { signal },
  );
}

export function reviewPoseActiveLearningCandidate(
  candidateId: string,
  payload: PoseActiveLearningReviewPayload,
): Promise<PoseActiveLearningCandidate> {
  return request(
    `/pose-active-learning-candidates/${encodeURIComponent(candidateId)}/review`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
  );
}

export function poseActiveLearningRetrainingManifestUrl(
  roundId: string,
): string {
  return `${getApiBaseUrl()}/pose-active-learning-rounds/${encodeURIComponent(roundId)}/retraining-manifest`;
}
