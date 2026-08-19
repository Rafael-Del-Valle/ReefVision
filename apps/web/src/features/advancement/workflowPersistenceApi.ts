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

export interface PersistedWorkflowRevision {
  id: string;
  workflow_id: string;
  revision_number: number;
  workflow_json: Record<string, unknown>;
  workflow_checksum: string;
  validation_json: Record<string, unknown>;
  created_by: string;
  created_at: string;
}

export interface PersistedWorkflowDetail {
  workflow: PersistedWorkflow;
  current_revision: PersistedWorkflowRevision;
  validation: {
    project_id: string;
    name: string;
    valid: boolean;
    workflow_checksum: string;
    topological_order: string[];
    execution_stages: Array<{ stage_index: number; node_ids: string[] }>;
    issues: Array<{
      severity: "error" | "warning";
      code: string;
      message: string;
      node_id: string | null;
      edge_index: number | null;
    }>;
  };
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

export type WorkflowRunCreateResponse = WorkflowRetryResponse;

export interface EditableWorkflowPayload {
  name: string;
  nodes: Array<{
    id: string;
    node_type: string;
    label?: string | null;
    configuration: Record<string, unknown>;
  }>;
  edges: Array<{
    source_node_id: string;
    source_port: string;
    target_node_id: string;
    target_port: string;
  }>;
}

export interface WorkflowArtifactCleanupAction {
  action_id: string;
  action_kind: "quarantine_file" | "clear_missing_reference";
  artifact_id: string;
  node_id: string;
  port_name: string;
  managed_path: string;
  size_bytes: number;
  file_sha256: string | null;
  eligible: boolean;
  blockers: string[];
}

export interface WorkflowArtifactCleanupPreview {
  workflow_run_id: string;
  run_status: string;
  preview_checksum: string;
  action_count: number;
  eligible_action_count: number;
  reclaimable_bytes: number;
  actions: WorkflowArtifactCleanupAction[];
}

export interface WorkflowArtifactCleanupResult {
  workflow_run_id: string;
  applied_action_count: number;
  quarantined_file_count: number;
  cleared_reference_count: number;
  reclaimed_bytes: number;
  quarantine_paths: string[];
}

export interface WorkflowArtifactQuarantineItem {
  artifact_id: string;
  node_id: string;
  port_name: string;
  original_managed_path: string;
  quarantine_path: string;
  file_sha256: string | null;
  size_bytes: number;
  quarantined_at: string;
  restorable: boolean;
  blockers: string[];
}

export interface WorkflowArtifactQuarantine {
  workflow_run_id: string;
  item_count: number;
  restorable_count: number;
  total_bytes: number;
  items: WorkflowArtifactQuarantineItem[];
}

export interface WorkflowArtifactRestoreResult {
  workflow_run_id: string;
  restored_artifact_count: number;
  restored_bytes: number;
  restored_paths: string[];
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
      const payload = (await response.json()) as {
        detail?: string | { message?: string; reason?: string };
      };
      if (typeof payload.detail === "string") message = payload.detail;
      if (payload.detail && typeof payload.detail === "object") {
        message = payload.detail.message ?? payload.detail.reason ?? message;
      }
    } catch {
      // Keep the HTTP fallback for non-JSON errors.
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function listPersistedWorkflows(projectId: string, signal?: AbortSignal) {
  return request<PersistedWorkflow[]>(`/projects/${projectId}/workflows`, {
    signal,
  });
}

export function createPersistedWorkflow(
  projectId: string,
  payload: {
    name: string;
    description?: string | null;
    workflow: EditableWorkflowPayload;
    status?: "draft" | "published" | "archived";
    creator?: string;
  },
) {
  return request<PersistedWorkflowDetail>(`/projects/${projectId}/workflows`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getPersistedWorkflow(workflowId: string, signal?: AbortSignal) {
  return request<PersistedWorkflowDetail>(`/workflows/${workflowId}`, { signal });
}

export function createWorkflowRevision(
  workflowId: string,
  workflow: EditableWorkflowPayload,
  creator = "local_user",
) {
  return request<PersistedWorkflowDetail>(`/workflows/${workflowId}/revisions`, {
    method: "POST",
    body: JSON.stringify({ workflow, creator }),
  });
}

export function listWorkflowRevisions(workflowId: string, signal?: AbortSignal) {
  return request<PersistedWorkflowRevision[]>(`/workflows/${workflowId}/revisions`, {
    signal,
  });
}

export function queueWorkflowRun(
  workflowId: string,
  payload: {
    workflow_revision_id?: string;
    inputs?: Record<string, unknown>;
    use_cache?: boolean;
  } = {},
) {
  return request<WorkflowRunCreateResponse>(`/workflows/${workflowId}/runs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listWorkflowRuns(workflowId: string, signal?: AbortSignal) {
  return request<WorkflowRunRecord[]>(`/workflows/${workflowId}/runs`, {
    signal,
  });
}

export function getWorkflowRun(runId: string, signal?: AbortSignal) {
  return request<WorkflowRunRecord>(`/workflow-runs/${runId}`, { signal });
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

export function previewWorkflowArtifactCleanup(
  runId: string,
  nodeIds: string[] = [],
) {
  return request<WorkflowArtifactCleanupPreview>(
    `/workflow-runs/${runId}/artifact-cleanup/preview`,
    {
      method: "POST",
      body: JSON.stringify({ node_ids: nodeIds }),
    },
  );
}

export function applyWorkflowArtifactCleanup(
  runId: string,
  payload: {
    preview_checksum: string;
    action_ids: string[];
    node_ids?: string[];
  },
) {
  return request<WorkflowArtifactCleanupResult>(
    `/workflow-runs/${runId}/artifact-cleanup/apply`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function listWorkflowArtifactQuarantine(
  runId: string,
  signal?: AbortSignal,
) {
  return request<WorkflowArtifactQuarantine>(
    `/workflow-runs/${runId}/artifact-quarantine`,
    { signal },
  );
}

export function restoreWorkflowArtifacts(
  runId: string,
  artifactIds: string[],
) {
  return request<WorkflowArtifactRestoreResult>(
    `/workflow-runs/${runId}/artifact-quarantine/restore`,
    {
      method: "POST",
      body: JSON.stringify({ artifact_ids: artifactIds }),
    },
  );
}
