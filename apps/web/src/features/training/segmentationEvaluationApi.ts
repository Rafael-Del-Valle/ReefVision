import type { JobRecord } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";

export interface SegmentationEvaluationRequest {
  dataset_version_id: string;
  candidate_model_id: string;
  incumbent_model_id: string | null;
  split: "validation" | "test";
  minimum_images: number;
  minimum_masks: number;
  minimum_mask_map50: number;
  minimum_gain: number;
}

export interface SegmentationDeploymentAudit {
  id: string;
  status: "succeeded";
  task: "segment";
  action: "promote" | "rollback";
  evaluation_id: string | null;
  deployment_id: string | null;
  active_model_id: string | null;
  previous_model_id: string | null;
  approved_by: string;
  reason: string;
}

async function request<T>(path: string, body: object): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let message = `Segmentation operation failed (HTTP ${response.status})`;
    try {
      const error = (await response.json()) as { detail?: string };
      if (typeof error.detail === "string") message = error.detail;
    } catch {
      // Keep the HTTP status when the server does not return JSON.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export async function listSegmentationEvaluations(
  projectId: string,
  signal?: AbortSignal,
): Promise<JobRecord[]> {
  const response = await fetch(
    `${getApiBaseUrl()}/projects/${projectId}/learning/segmentation/evaluations`,
    { signal, cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(
      `Unable to load evaluation history (HTTP ${response.status})`,
    );
  }
  return (await response.json()) as JobRecord[];
}

export function queueSegmentationEvaluation(
  projectId: string,
  payload: SegmentationEvaluationRequest,
): Promise<JobRecord> {
  return request<JobRecord>(
    `/projects/${projectId}/learning/segmentation/queue`,
    payload,
  );
}

export function promoteSegmentationCandidate(
  projectId: string,
  evaluationId: string,
  expectedActiveModelId: string | null,
  approvedBy: string,
  reason: string,
): Promise<SegmentationDeploymentAudit> {
  return request<SegmentationDeploymentAudit>(
    `/projects/${projectId}/learning/segmentation/evaluations/${evaluationId}/promote`,
    {
      expected_active_model_id: expectedActiveModelId,
      approved_by: approvedBy,
      reason,
    },
  );
}

export function rollbackSegmentationDeployment(
  projectId: string,
  deploymentId: string,
  expectedActiveModelId: string,
  approvedBy: string,
  reason: string,
): Promise<SegmentationDeploymentAudit> {
  return request<SegmentationDeploymentAudit>(
    `/projects/${projectId}/learning/segmentation/deployments/${deploymentId}/rollback`,
    {
      expected_active_model_id: expectedActiveModelId,
      approved_by: approvedBy,
      reason,
    },
  );
}
