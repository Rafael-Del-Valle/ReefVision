import { getApiBaseUrl } from "../../runtime";
import type {
  DatasetVersionRecord,
  JobRecord,
  ModelRegistration,
  ProjectImageListItem,
} from "../../api/client";

export interface ImageLabelRecord {
  id: string;
  image_id: string;
  label_class_id: string;
  label_set: string;
  confidence: number | null;
  source_type: string;
  source_model_id: string | null;
  source_prediction_id: string | null;
  status: string;
  revision: number;
}

export interface ClassificationDatasetRecord {
  id: string;
  project_id: string;
  dataset_version_id: string;
  mode: "image" | "box_crop" | "mask_crop" | string;
  label_set: string;
  status: string;
  manifest_sha256: string;
  sample_count: number;
  created_at: string;
}

export interface ClassificationPredictionRecord {
  id: string;
  project_id: string;
  image_id: string;
  model_id: string;
  label_class_id: string;
  label_set: string;
  confidence: number;
  rank: number;
  scores_json: Record<string, unknown>;
  status: string;
  accepted_image_label_id: string | null;
}

interface ImagePage {
  items: ProjectImageListItem[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
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
    let message = `Classification request failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string") message = payload.detail;
    } catch {
      // Preserve the HTTP fallback for non-JSON responses.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function getClassificationImages(
  projectId: string,
  signal?: AbortSignal,
): Promise<ImagePage> {
  return request<ImagePage>(
    `/projects/${encodeURIComponent(projectId)}/images?page=1&page_size=100`,
    { signal },
  );
}

export function getClassificationVersions(
  projectId: string,
  signal?: AbortSignal,
): Promise<DatasetVersionRecord[]> {
  return request<DatasetVersionRecord[]>(
    `/projects/${encodeURIComponent(projectId)}/dataset-versions`,
    { signal },
  );
}

export function getClassificationDatasets(
  projectId: string,
  signal?: AbortSignal,
): Promise<ClassificationDatasetRecord[]> {
  return request<ClassificationDatasetRecord[]>(
    `/projects/${encodeURIComponent(projectId)}/classification-datasets`,
    { signal },
  );
}

export function createClassificationDataset(
  projectId: string,
  payload: {
    dataset_version_id: string;
    mode: "image" | "box_crop" | "mask_crop";
    label_set: string;
    minimum_crop_pixels: number;
  },
): Promise<ClassificationDatasetRecord> {
  return request<ClassificationDatasetRecord>(
    `/projects/${encodeURIComponent(projectId)}/classification-datasets`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function getImageClassificationLabels(
  imageId: string,
  labelSet: string,
  signal?: AbortSignal,
): Promise<ImageLabelRecord[]> {
  return request<ImageLabelRecord[]>(
    `/images/${encodeURIComponent(imageId)}/classification-labels?label_set=${encodeURIComponent(labelSet)}`,
    { signal },
  );
}

export function replaceImageClassificationLabels(
  imageId: string,
  labelSet: string,
  labelClassIds: string[],
): Promise<ImageLabelRecord[]> {
  return request<ImageLabelRecord[]>(
    `/images/${encodeURIComponent(imageId)}/classification-labels`,
    {
      method: "PUT",
      body: JSON.stringify({
        label_set: labelSet,
        label_class_ids: labelClassIds,
      }),
    },
  );
}

export function getClassifierModels(
  projectId: string,
  signal?: AbortSignal,
): Promise<ModelRegistration[]> {
  return request<ModelRegistration[]>(
    `/projects/${encodeURIComponent(projectId)}/models?purpose=classifier`,
    { signal },
  );
}

export function createClassificationTrainingJob(
  projectId: string,
  payload: {
    classification_dataset_id: string;
    architecture: string;
    run_name: string;
    epochs: number;
    image_size: number;
    batch: number;
    device: string;
  },
): Promise<JobRecord> {
  return request<JobRecord>(
    `/projects/${encodeURIComponent(projectId)}/classification-training-jobs`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function createClassificationInferenceJob(
  projectId: string,
  payload: {
    model_id: string;
    image_ids: string[];
    label_set: string;
    top_k: number;
    device: string;
  },
): Promise<JobRecord> {
  return request<JobRecord>(
    `/projects/${encodeURIComponent(projectId)}/classification-inference-jobs`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function getClassificationPredictions(
  projectId: string,
  imageId: string,
  signal?: AbortSignal,
): Promise<ClassificationPredictionRecord[]> {
  return request<ClassificationPredictionRecord[]>(
    `/projects/${encodeURIComponent(projectId)}/classification-predictions?image_id=${encodeURIComponent(imageId)}`,
    { signal },
  );
}

export function reviewClassificationPrediction(
  predictionId: string,
  action: "accept" | "reject",
): Promise<ClassificationPredictionRecord> {
  return request<ClassificationPredictionRecord>(
    `/classification-predictions/${encodeURIComponent(predictionId)}/review`,
    { method: "PUT", body: JSON.stringify({ action }) },
  );
}
