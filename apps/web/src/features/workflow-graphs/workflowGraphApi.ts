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
  return request<{ status: string }>(
    `/jobs/${encodeURIComponent(jobId)}/cancel`,
    {
      method: "POST",
    },
  );
}

/** Bounded local file preview. No asset persistence or calibration verification. */
export interface MeshPreviewCalibration {
  meters_per_unit: number;
  calibration_method:
    "ruler" | "photogrammetry_control" | "instrument" | "other";
  calibration_evidence: string;
  relative_scale_uncertainty?: number | null;
  coordinate_frame_id?: string;
}

export async function previewLocalMeshFile(
  projectId: string,
  file: File,
  calibration: MeshPreviewCalibration,
): Promise<Record<string, unknown>> {
  const extension = file.name.split(".").pop()?.toLowerCase();
  if (extension !== "obj" && extension !== "ply" && extension !== "glb") {
    throw new Error("Choose an OBJ, PLY, or GLB mesh file.");
  }
  const maxBytes = extension === "glb" ? 262_500 : 256_000;
  if (!file.size || file.size > maxBytes || file.name.length > 200) {
    throw new Error(
      "Mesh file is empty, oversized, or has an invalid filename.",
    );
  }
  if (
    !Number.isFinite(calibration.meters_per_unit) ||
    calibration.meters_per_unit <= 0 ||
    calibration.meters_per_unit > 1_000_000 ||
    !calibration.calibration_evidence.trim()
  ) {
    throw new Error("Provide a positive scale and calibration evidence.");
  }
  if (
    calibration.relative_scale_uncertainty != null &&
    (!Number.isFinite(calibration.relative_scale_uncertainty) ||
      calibration.relative_scale_uncertainty < 0 ||
      calibration.relative_scale_uncertainty > 1)
  ) {
    throw new Error("Relative scale uncertainty must be between 0 and 1.");
  }
  if (
    calibration.coordinate_frame_id !== undefined &&
    !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(calibration.coordinate_frame_id)
  ) {
    throw new Error("Mesh source frame ID must be a bounded label.");
  }
  let geometry: Record<string, string>;
  if (extension === "glb") {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = "";
    for (let offset = 0; offset < bytes.length; offset += 8192) {
      binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
    }
    geometry = { glb_base64: btoa(binary) };
  } else {
    const content = await file.text();
    if (content.length > 256_000) {
      throw new Error("Mesh text exceeds the supported preview limit.");
    }
    geometry =
      extension === "obj" ? { obj_text: content } : { ply_text: content };
  }
  return request<Record<string, unknown>>(
    `/projects/${encodeURIComponent(projectId)}/spatial/mesh-preview`,
    {
      method: "POST",
      body: JSON.stringify({
        ...calibration,
        ...geometry,
        source_label: file.name,
      }),
    },
  );
}

/** Temporary vertex-only ASCII PLY preview; no persistence or verification. */
export async function previewLocalPointCloudFile(
  projectId: string,
  file: File,
  calibration: MeshPreviewCalibration,
  pointIndexPairs?: Array<[number, number]>,
  preserveMeasuredChordEndpoints = false,
): Promise<Record<string, unknown>> {
  if (file.name.split(".").pop()?.toLowerCase() !== "ply") {
    throw new Error("Choose a vertex-only ASCII PLY point-cloud file.");
  }
  if (!file.size || file.size > 256_000 || file.name.length > 200) {
    throw new Error(
      "Point-cloud file is empty, oversized, or has an invalid filename.",
    );
  }
  if (
    !Number.isFinite(calibration.meters_per_unit) ||
    calibration.meters_per_unit <= 0 ||
    calibration.meters_per_unit > 1_000_000 ||
    !calibration.calibration_evidence.trim() ||
    calibration.calibration_evidence.length > 2_000
  ) {
    throw new Error(
      "Provide a positive scale and bounded calibration evidence.",
    );
  }
  if (
    calibration.relative_scale_uncertainty != null &&
    (!Number.isFinite(calibration.relative_scale_uncertainty) ||
      calibration.relative_scale_uncertainty < 0 ||
      calibration.relative_scale_uncertainty > 1)
  ) {
    throw new Error("Relative scale uncertainty must be between 0 and 1.");
  }
  if (
    pointIndexPairs &&
    (pointIndexPairs.length > 32 ||
      pointIndexPairs.some(
        (pair) =>
          !Array.isArray(pair) ||
          pair.length !== 2 ||
          pair.some(
            (index) => !Number.isInteger(index) || index < 0 || index >= 2_000,
          ) ||
          pair[0] === pair[1],
      ))
  ) {
    throw new Error(
      "Point chord indices must be distinct integers from 0 to 1999.",
    );
  }
  if (
    calibration.coordinate_frame_id !== undefined &&
    !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(calibration.coordinate_frame_id)
  ) {
    throw new Error("Point-cloud source frame ID must be a bounded label.");
  }
  const bytes = await file.arrayBuffer();
  if (!bytes.byteLength || bytes.byteLength > 256_000) {
    throw new Error("Point-cloud file exceeds the supported preview limit.");
  }
  const plyText = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  if (!/^[\x00-\x7F]*$/.test(plyText)) {
    throw new Error("Only ASCII PLY point clouds are supported.");
  }
  return request<Record<string, unknown>>(
    `/projects/${encodeURIComponent(projectId)}/spatial/point-cloud-preview`,
    {
      method: "POST",
      body: JSON.stringify({
        ...calibration,
        ply_text: plyText,
        source_label: file.name,
        ...(pointIndexPairs?.length
          ? { point_index_pairs: pointIndexPairs }
          : {}),
        ...(preserveMeasuredChordEndpoints
          ? { preserve_measured_chord_endpoints_in_preview: true }
          : {}),
      }),
    },
  );
}
