import { getApiBaseUrl } from "../../runtime";

export class AdvancementApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${getApiBaseUrl()}${path}`, { ...init, headers });
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string") message = payload.detail;
    } catch {
      // Keep the HTTP fallback when the response is not JSON.
    }
    throw new AdvancementApiError(message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export interface ProjectIntegrityIssue {
  severity: "info" | "warning" | "error";
  code: string;
  resource_kind: string;
  record_id: string | null;
  managed_path: string | null;
  message: string;
  repairable: boolean;
}

export interface ProjectIntegrityReport {
  project_id: string;
  project_name: string;
  checked_at: string;
  verify_checksums: boolean;
  stale_job_minutes: number;
  valid: boolean;
  error_count: number;
  warning_count: number;
  total_referenced_files: number;
  existing_referenced_files: number;
  missing_referenced_files: number;
  total_existing_bytes: number;
  categories: Array<{
    resource_kind: string;
    record_count: number;
    referenced_file_count: number;
    existing_file_count: number;
    missing_file_count: number;
    total_existing_bytes: number;
    checksum_verified_count: number;
    checksum_mismatch_count: number;
  }>;
  issues: ProjectIntegrityIssue[];
}

export interface SegmentationEvaluation {
  project_id: string;
  model_id: string;
  image_count: number;
  ground_truth_count: number;
  prediction_count: number;
  matched_count: number;
  false_positive_count: number;
  false_negative_count: number;
  instance_precision: number;
  instance_recall: number;
  mean_iou: number | null;
  mean_dice: number | null;
  per_class: Array<{
    label_class_id: string | null;
    ground_truth_count: number;
    prediction_count: number;
    matched_count: number;
    false_positive_count: number;
    false_negative_count: number;
    instance_precision: number;
    instance_recall: number;
    mean_iou: number | null;
    mean_dice: number | null;
    mean_pixel_precision: number | null;
    mean_pixel_recall: number | null;
  }>;
  warnings: string[];
}

export interface ClassificationEvaluation {
  project_id: string;
  model_id: string;
  sample_count: number;
  correct_count: number;
  accuracy: number;
  macro_precision: number;
  macro_recall: number;
  macro_f1: number;
  weighted_f1: number;
  mean_confidence: number | null;
  expected_calibration_error: number | null;
  top_label_brier_score: number | null;
  per_class: Array<{
    label_class_id: string;
    support: number;
    predicted_count: number;
    true_positive_count: number;
    false_positive_count: number;
    false_negative_count: number;
    precision: number;
    recall: number;
    f1: number;
  }>;
  calibration_bins: Array<{
    lower_bound: number;
    upper_bound: number;
    sample_count: number;
    mean_confidence: number | null;
    accuracy: number | null;
    absolute_gap: number | null;
  }>;
  warnings: string[];
}

export interface ImageEmbeddingRecord {
  id: string;
  project_id: string;
  image_id: string;
  embedding_model_id: string;
  embedding_model_checksum: string | null;
  dimension: number;
  vector_sha256: string;
  source_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface EmbeddingDiversitySelection {
  project_id: string;
  embedding_model_id: string;
  embedding_model_checksum: string | null;
  candidate_count: number;
  selected_count: number;
  skipped_missing_embedding_count: number;
  vector_dimension: number | null;
  diversity_weight: number;
  maximum_items_per_group: number | null;
  selections: Array<{
    image_id: string;
    group_key: string | null;
    rank: number;
    base_score: number;
    normalized_base_score: number;
    novelty_score: number;
    selection_score: number;
    nearest_selected_image_id: string | null;
    vector_sha256: string;
  }>;
  warnings: string[];
}

export interface WorkflowNodeDefinition {
  node_type: string;
  display_name: string;
  inputs: Array<{ name: string; data_type: string; required: boolean }>;
  outputs: Array<{ name: string; data_type: string; required: boolean }>;
  requires_model: boolean;
  supported_model_tasks: string[];
}

export interface WorkflowTemplate {
  template_id: string;
  name: string;
  description: string;
  workflow: Record<string, unknown>;
}

export interface WorkflowValidation {
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
}

export function inspectProjectIntegrity(
  projectId: string,
  verifyChecksums: boolean,
  staleJobMinutes: number,
) {
  const search = new URLSearchParams({
    verify_checksums: String(verifyChecksums),
    stale_job_minutes: String(staleJobMinutes),
  });
  return request<ProjectIntegrityReport>(
    `/projects/${projectId}/integrity?${search}`,
  );
}

export function evaluateSegmentation(
  projectId: string,
  payload: Record<string, unknown>,
) {
  return request<SegmentationEvaluation>(
    `/projects/${projectId}/segmentation-evaluations`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function evaluateClassification(
  projectId: string,
  payload: Record<string, unknown>,
) {
  return request<ClassificationEvaluation>(
    `/projects/${projectId}/classification-evaluations`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function listEmbeddings(projectId: string, modelId?: string) {
  const search = new URLSearchParams();
  if (modelId) search.set("embedding_model_id", modelId);
  const suffix = search.size ? `?${search}` : "";
  return request<ImageEmbeddingRecord[]>(
    `/projects/${projectId}/embeddings${suffix}`,
  );
}

export function selectEmbeddingDiversity(
  projectId: string,
  payload: Record<string, unknown>,
) {
  return request<EmbeddingDiversitySelection>(
    `/projects/${projectId}/embedding-diversity-selection`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function getWorkflowDefinitions() {
  return request<WorkflowNodeDefinition[]>("/workflow-node-definitions");
}

export function getWorkflowTemplates() {
  return request<WorkflowTemplate[]>("/workflow-templates");
}

export function validateWorkflow(
  projectId: string,
  payload: Record<string, unknown>,
) {
  return request<WorkflowValidation>(
    `/projects/${projectId}/workflows/validate`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function createCocoExport(versionId: string) {
  return request<{
    export: { id: string; dataset_version_id: string; format: string };
    job: { id: string; status: string };
  }>(`/dataset-versions/${versionId}/exports`, {
    method: "POST",
    body: JSON.stringify({ format: "coco_instances" }),
  });
}
