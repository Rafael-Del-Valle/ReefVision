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
  execution_blocker: string;
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
