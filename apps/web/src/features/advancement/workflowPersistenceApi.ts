import { getApiBaseUrl } from "../../runtime";

export interface PersistedWorkflow {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  status: "draft" | "published" | "archived";
  current_revision_number: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface WorkflowRunRecord {
  id: string;
  workflow_id: string;
  workflow_revision_id: string;
  project_id: string;
  job_id: string | null;
  status:
    | "queued"
    | "running"
    | "cancel_requested"
    | "cancelled"
    | "succeeded"
    | "failed";
  stage: string;
  current_node_id: string | null;
  input_json: Record<string, unknown>;
  result_json: Record<string, unknown>;
  node_state_json: Record<string, Record<string, unknown>>;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface WorkflowRetryResponse {
  run: WorkflowRunRecord;
  job: {
    id: string;
    status: string;
    job_type: string;
    progress_current: number;
    progress_total: number;
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers,
  });
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string") message = payload.detail;
    } catch {
      // Keep the HTTP fallback for non-JSON errors.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function listPersistedWorkflows(projectId: string, signal?: AbortSignal) {
  return request<PersistedWorkflow[]>(`/projects/${projectId}/workflows`, {
    signal,
  });
}

export function listWorkflowRuns(workflowId: string, signal?: AbortSignal) {
  return request<WorkflowRunRecord[]>(`/workflows/${workflowId}/runs`, {
    signal,
  });
}

export function retryWorkflowRun(
  runId: string,
  payload: { from_node_id?: string; use_cache?: boolean },
) {
  return request<WorkflowRetryResponse>(`/workflow-runs/${runId}/retry`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
