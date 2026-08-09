import { getApiBaseUrl } from "../../runtime";

export interface WorkflowNodeDefinition {
  node_type: string;
  display_name: string;
  category: string;
  description: string;
  input_ports: Array<{
    port_id: string;
    display_name: string;
    accepted_types: string[];
    required: boolean;
    multiple: boolean;
  }>;
  output_ports: Array<{
    port_id: string;
    display_name: string;
    accepted_types: string[];
    required: boolean;
    multiple: boolean;
  }>;
  required_parameters: string[];
  optional_parameters: Record<string, unknown>;
  execution_state: string;
  executable: boolean;
  implementation_notes: string[];
}

export interface WorkflowGraphIssue {
  severity: "error" | "warning";
  code: string;
  message: string;
  node_id: string | null;
  edge_id: string | null;
}

export interface WorkflowGraphValidation {
  valid: boolean;
  graph_id: string;
  issues: WorkflowGraphIssue[];
  topological_order: string[];
  referenced_model_ids: string[];
  referenced_dataset_version_ids: string[];
  referenced_video_ids: string[];
}

export interface WorkflowGraphPlan {
  valid: boolean;
  graph_id: string;
  executable: boolean;
  issues: WorkflowGraphIssue[];
  steps: Array<{
    order: number;
    node_id: string;
    node_type: string;
    display_name: string;
    execution_state: string;
    executable: boolean;
    parameters: Record<string, unknown>;
    input_bindings: Array<{
      target_port_id: string;
      source_node_id: string;
      source_port_id: string;
      data_type: string;
    }>;
    output_types: Record<string, string[]>;
    action: string;
  }>;
  execution_blocker: string | null;
}

export interface WorkflowGraphRecord {
  id: string;
  project_id: string;
  graph_key: string;
  name: string;
  schema_version: string;
  revision: number;
  graph_json: Record<string, unknown>;
  graph_sha256: string;
  created_at: string;
  updated_at: string;
}

export interface WorkflowRun {
  id: string;
  project_id: string;
  workflow_graph_record_id: string;
  job_id: string | null;
  status: string;
  graph_sha256: string;
  input_json: Record<string, unknown>;
  result_json: Record<string, unknown>;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface WorkflowNodeRun {
  id: string;
  workflow_run_id: string;
  node_id: string;
  node_type: string;
  execution_order: number;
  status: string;
  parameters_json: Record<string, unknown>;
  input_artifact_ids_json: string[];
  output_artifact_ids_json: string[];
  result_json: Record<string, unknown>;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface WorkflowArtifact {
  id: string;
  workflow_run_id: string;
  producer_node_run_id: string;
  producer_port_id: string;
  data_type: string;
  payload_json: Record<string, unknown>;
  payload_sha256: string;
  created_at: string;
}

export interface WorkflowRunDetail {
  run: WorkflowRun;
  nodes: WorkflowNodeRun[];
  artifacts: WorkflowArtifact[];
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
    let message = `Workflow request failed with HTTP ${response.status}`;
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

export function getWorkflowNodeRegistry(
  signal?: AbortSignal,
): Promise<WorkflowNodeDefinition[]> {
  return request<WorkflowNodeDefinition[]>("/workflow-graphs/node-registry", {
    signal,
  });
}

export function validateWorkflowGraph(
  projectId: string,
  graph: Record<string, unknown>,
): Promise<WorkflowGraphValidation> {
  return request<WorkflowGraphValidation>(
    `/projects/${encodeURIComponent(projectId)}/workflow-graphs/validate`,
    { method: "POST", body: JSON.stringify(graph) },
  );
}

export function planWorkflowGraph(
  projectId: string,
  graph: Record<string, unknown>,
): Promise<WorkflowGraphPlan> {
  return request<WorkflowGraphPlan>(
    `/projects/${encodeURIComponent(projectId)}/workflow-graphs/plan`,
    { method: "POST", body: JSON.stringify(graph) },
  );
}

export function listSavedWorkflowGraphs(
  projectId: string,
  signal?: AbortSignal,
): Promise<WorkflowGraphRecord[]> {
  return request<WorkflowGraphRecord[]>(
    `/projects/${encodeURIComponent(projectId)}/workflow-graphs`,
    { signal },
  );
}

export function saveWorkflowGraph(
  projectId: string,
  graph: Record<string, unknown>,
): Promise<WorkflowGraphRecord> {
  return request<WorkflowGraphRecord>(
    `/projects/${encodeURIComponent(projectId)}/workflow-graphs`,
    {
      method: "POST",
      body: JSON.stringify({ graph, create_new_revision: true }),
    },
  );
}

export function listWorkflowRuns(
  projectId: string,
  signal?: AbortSignal,
): Promise<WorkflowRun[]> {
  return request<WorkflowRun[]>(
    `/projects/${encodeURIComponent(projectId)}/workflow-runs`,
    { signal },
  );
}

export function queueWorkflowRun(
  projectId: string,
  graphRecordId: string,
): Promise<WorkflowRun> {
  return request<WorkflowRun>(
    `/projects/${encodeURIComponent(projectId)}/workflow-runs`,
    {
      method: "POST",
      body: JSON.stringify({ graph_record_id: graphRecordId, inputs: {} }),
    },
  );
}

export function getWorkflowRunDetail(
  runId: string,
  signal?: AbortSignal,
): Promise<WorkflowRunDetail> {
  return request<WorkflowRunDetail>(
    `/workflow-runs/${encodeURIComponent(runId)}`,
    { signal },
  );
}

export function resumeWorkflowReviewNode(
  nodeRunId: string,
  reviewedBy = "local_user",
  note?: string,
): Promise<WorkflowRun> {
  return request<WorkflowRun>(
    `/workflow-node-runs/${encodeURIComponent(nodeRunId)}/resume-review`,
    {
      method: "POST",
      body: JSON.stringify({ reviewed_by: reviewedBy, note: note ?? null }),
    },
  );
}

export function cancelWorkflowRunJob(
  jobId: string,
): Promise<{ status: string }> {
  return request<{ status: string }>(`/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
}
