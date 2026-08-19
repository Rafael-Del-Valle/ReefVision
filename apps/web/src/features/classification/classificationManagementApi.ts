import { getApiBaseUrl } from "../../runtime";

export interface ClassificationLabelSet {
  id: string;
  project_id: string;
  key: string;
  name: string;
  description: string | null;
  target_kind: "annotation" | "image" | "mask" | "fragment";
  cardinality: "single" | "multi";
  allowed_class_ids_json: string[];
  replaces_primary_class: boolean;
  is_active: boolean;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ManagedClassificationPrediction {
  id: string;
  image_id: string;
  target_kind: string;
  target_key: string;
  label_set: string;
  predicted_label: string;
  label_class_id: string | null;
  confidence: number;
  review_status: string;
  model_id: string;
}

export interface ClassificationComparison {
  project_id: string;
  target_count: number;
  agreement_count: number;
  disagreement_count: number;
  minimum_models: number;
  targets: Array<{
    target_kind: string;
    target_key: string;
    image_id: string;
    label_set: string;
    model_count: number;
    agreement: boolean;
    compared_values: string[];
    predictions: Array<{
      prediction_id: string;
      model_id: string;
      model_name: string;
      predicted_label: string;
      label_class_id: string | null;
      confidence: number;
      review_status: string;
    }>;
  }>;
}

export interface ClassificationDatasetSnapshot {
  id: string;
  project_id: string;
  label_set_id: string;
  name: string;
  target_kind: string;
  cardinality: string;
  manifest_sha256: string;
  sample_count: number;
  class_count: number;
  warnings_json: string[];
  created_at: string;
}

export interface ClassificationSnapshotTrainingResponse {
  training_run_id: string;
  job_id: string;
  project_id: string;
  snapshot_id: string;
  snapshot_manifest_sha256: string;
  split_manifest_sha256: string;
  target_kind: string;
  label_set_id: string;
  cardinality: string;
  status: string;
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
      // Keep HTTP fallback for non-JSON errors.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function listClassificationLabelSets(
  projectId: string,
  signal?: AbortSignal,
) {
  return request<ClassificationLabelSet[]>(
    `/projects/${projectId}/classification-label-sets`,
    { signal },
  );
}

export function createClassificationLabelSet(
  projectId: string,
  payload: Record<string, unknown>,
) {
  return request<ClassificationLabelSet>(
    `/projects/${projectId}/classification-label-sets`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function updateClassificationLabelSet(
  labelSetId: string,
  payload: Record<string, unknown>,
) {
  return request<ClassificationLabelSet>(
    `/classification-label-sets/${labelSetId}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );
}

export function listPendingClassificationPredictions(
  projectId: string,
  signal?: AbortSignal,
) {
  return request<{ items: ManagedClassificationPrediction[] }>(
    `/projects/${projectId}/classification-predictions?page=1&page_size=500&review_status=pending`,
    { signal },
  );
}

export function bulkReviewClassificationPredictions(
  projectId: string,
  payload: Record<string, unknown>,
) {
  return request<{
    accepted_count: number;
    rejected_count: number;
    unchanged_count: number;
    failed_count: number;
    items: Array<Record<string, unknown>>;
  }>(`/projects/${projectId}/classification-predictions/bulk-review`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function compareClassificationModels(
  projectId: string,
  labelSet?: string,
) {
  const search = new URLSearchParams({ minimum_models: "2" });
  if (labelSet) search.set("label_set", labelSet);
  return request<ClassificationComparison>(
    `/projects/${projectId}/classification-model-comparison?${search}`,
  );
}

export function listClassificationDatasetSnapshots(
  projectId: string,
  signal?: AbortSignal,
) {
  return request<ClassificationDatasetSnapshot[]>(
    `/projects/${projectId}/classification-dataset-snapshots`,
    { signal },
  );
}

export function createClassificationDatasetSnapshot(
  projectId: string,
  payload: Record<string, unknown>,
) {
  return request<{ snapshot: ClassificationDatasetSnapshot }>(
    `/projects/${projectId}/classification-dataset-snapshots`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function trainClassificationDatasetSnapshot(
  projectId: string,
  snapshotId: string,
  payload: Record<string, unknown>,
) {
  return request<ClassificationSnapshotTrainingResponse>(
    `/projects/${projectId}/classification-dataset-snapshots/${snapshotId}/training-runs`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function classificationScientificDownloadUrl(
  projectId: string,
  format: "csv" | "npz",
): string {
  return `${getApiBaseUrl()}/projects/${projectId}/classification-assignments/scientific-export.${format}`;
}
