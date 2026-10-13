import { getApiBaseUrl } from "../../runtime";

/** Isolated inference never verifies annotations or deploys a model. */
export interface SegmentationEvaluationQueueInput {
  dataset_version_id: string;
  candidate_model_id: string;
  incumbent_model_id: string | null;
  split: "validation" | "test";
  minimum_images: number;
  minimum_masks: number;
  minimum_mask_map50: number;
  minimum_gain: number;
}

export interface SegmentationEvaluationJob {
  id: string;
  job_type: string;
  status: string;
  progress_current: number;
  progress_total: number;
  error_message: string | null;
}

export interface SegmentationMaskMetrics {
  mask_map50: number;
  precision: number;
  recall: number;
  mean_absolute_count_error: number;
  count_bias_per_image: number;
  mean_matched_mask_iou: number;
  per_class?: Record<string, unknown>;
}

export interface SegmentationEvaluationRecord {
  id: string;
  status: string;
  task: "segment";
  dataset_version_id: string;
  manifest_sha256: string;
  split: "validation" | "test";
  candidate_model_id: string;
  candidate_job_id: string;
  candidate_checksum: string;
  incumbent_model_id: string | null;
  incumbent_job_id: string | null;
  incumbent_checksum: string | null;
  candidate_metrics: SegmentationMaskMetrics | null;
  incumbent_metrics: SegmentationMaskMetrics | null;
  promotion_eligible: boolean;
  blockers: string[];
  warning: string;
}

export interface SegmentationDeploymentAudit {
  id: string;
  status: "succeeded";
  task: "segment";
  action: "promote" | "rollback";
  active_model_id: string | null;
  previous_model_id: string | null;
  approved_by: string;
  reason: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
    cache: "no-store",
  });
  if (!response.ok) {
    let message = `Segmentation evaluation request failed (HTTP ${response.status})`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      // Keep the status fallback when the API returns no JSON.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

function projectPath(projectId: string): string {
  return `/projects/${encodeURIComponent(projectId)}/learning/segmentation`;
}

export function queueSegmentationEvaluation(
  projectId: string,
  payload: SegmentationEvaluationQueueInput,
): Promise<SegmentationEvaluationJob> {
  return request<SegmentationEvaluationJob>(`${projectPath(projectId)}/queue`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getSegmentationEvaluation(
  projectId: string,
  evaluationId: string,
  signal?: AbortSignal,
): Promise<SegmentationEvaluationRecord> {
  return request<SegmentationEvaluationRecord>(
    `${projectPath(projectId)}/evaluations/${encodeURIComponent(evaluationId)}`,
    { signal },
  );
}

export function promoteSegmentationCandidate(
  projectId: string,
  evaluationId: string,
  payload: {
    expected_active_model_id: string | null;
    approved_by: string;
    reason: string;
  },
): Promise<SegmentationDeploymentAudit> {
  return request<SegmentationDeploymentAudit>(
    `${projectPath(projectId)}/evaluations/${encodeURIComponent(evaluationId)}/promote`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function rollbackSegmentationDeployment(
  projectId: string,
  deploymentId: string,
  payload: {
    expected_active_model_id: string;
    approved_by: string;
    reason: string;
  },
): Promise<SegmentationDeploymentAudit> {
  return request<SegmentationDeploymentAudit>(
    `${projectPath(projectId)}/deployments/${encodeURIComponent(deploymentId)}/rollback`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}
