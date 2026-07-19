import { getApiBaseUrl } from "../../runtime";

export interface ProjectMeasurementSummary {
  project_id: string;
  mask_count: number;
  calibrated_mask_count: number;
  area_pixels: number;
  perimeter_pixels: number;
  contained_box_count: number;
  total_linear_extension_pixels: number;
  calibrated_area_by_unit: Record<string, number>;
  calibrated_perimeter_by_unit: Record<string, number>;
  calibrated_tle_by_unit: Record<string, number>;
  surface_area_by_unit: Record<string, number>;
  by_class: Array<Record<string, unknown>>;
}

export interface MeasurementValidationResponse {
  project_id: string;
  mask_count: number;
  observation_count: number;
  passed_count: number;
  failed_count: number;
  warnings: string[];
  summaries: Array<{
    metric: string;
    unit: string | null;
    observation_count: number;
    mean_measured: number;
    mean_reference: number;
    mean_bias: number;
    mean_absolute_error: number;
    root_mean_square_error: number;
    mean_absolute_percentage_error: number | null;
    maximum_absolute_error: number;
    passed_count: number;
    failed_count: number;
  }>;
  observations: Array<Record<string, unknown>>;
}

export interface DatasetVersionOption {
  id: string;
  version_number: number;
  name: string;
  status: string;
  image_count: number;
  annotation_count: number;
}

export interface ClassificationPreview {
  dataset_version_id: string;
  mode: "multiclass" | "binary_state";
  minimum_crop_size_px: number;
  eligible_crop_count: number;
  removed_during_preprocessing_count: number;
  missing_state_count: number;
  split_counts: Record<string, number>;
  classes: Array<{ key: string; label: string; crop_count: number }>;
  warnings: string[];
}

export interface ModelRecord {
  id: string;
  purpose: string;
  task: string;
  display_name: string;
  provider_name: string;
  metadata_json: Record<string, unknown>;
}

export interface TrainingRunRecord {
  id: string;
  run_name: string;
  task: string;
  status: string;
  stage: string;
  result_checkpoint_path: string | null;
  metrics: Record<string, number>;
  created_at: string;
}

export interface ImageListItem {
  id: string;
  original_filename: string;
  annotation_status: string;
  annotation_count: number;
}

export interface ImagePage {
  items: ImageListItem[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface ClassificationPrediction {
  id: string;
  image_id: string;
  annotation_id: string | null;
  model_id: string;
  classification_mode: string;
  predicted_label: string;
  label_class_id: string | null;
  confidence: number;
  probabilities_json: Record<string, number>;
  review_status: string;
  accepted_label_class_id: string | null;
}

export interface ClassificationPredictionPage {
  items: ClassificationPrediction[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface JobRecord {
  id: string;
  job_type: string;
  status: string;
  progress_current: number;
  progress_total: number;
  request_json: Record<string, unknown>;
  result_json: Record<string, unknown> | null;
  error_message: string | null;
}

export interface VideoAsset {
  id: string;
  project_id: string;
  original_filename: string;
  media_type: string;
  width_px: number;
  height_px: number;
  frame_count: number;
  fps: number;
  duration_seconds: number;
  metadata_json: Record<string, unknown>;
}

export interface VideoTrackKeyframe {
  frame_index: number;
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
  confidence?: number | null;
  source?: string;
}

export interface VideoTrack {
  id: string;
  video_id: string;
  label_class_id: string | null;
  track_number: number;
  geometry_kind: string;
  keyframes: VideoTrackKeyframe[];
  interpolation: string;
  status: string;
  metadata_json: Record<string, unknown>;
}

export interface VideoAnalytics {
  video_id: string;
  fps: number;
  distance_per_pixel: number | null;
  physical_unit: string | null;
  tracks: Array<{
    track_id: string;
    tracker_id: number;
    label_class_id: string | null;
    duration_seconds: number;
    distance_pixels: number;
    mean_speed_pixels_per_second: number;
    maximum_speed_pixels_per_second: number;
    active_time_seconds: number;
    inactive_time_seconds: number;
    distance_physical: number | null;
    mean_speed_physical_per_second: number | null;
    physical_unit: string | null;
    zone_time_seconds: Record<string, number>;
  }>;
  school_by_frame: Array<{
    frame_index: number;
    timestamp_seconds: number;
    active_track_count: number;
    mean_nearest_neighbor_pixels: number | null;
    school_spread_pixels: number | null;
  }>;
  heatmap_bins_x: number;
  heatmap_bins_y: number;
  heatmap: Array<{
    column: number;
    row: number;
    observation_count: number;
    occupancy_seconds: number;
  }>;
  warnings: string[];
}

export class PhaseApiError extends Error {}

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
    throw new PhaseApiError(message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function downloadUrl(path: string): string {
  return `${getApiBaseUrl()}${path}`;
}

export function getMeasurementSummary(projectId: string, signal?: AbortSignal) {
  return request<ProjectMeasurementSummary>(
    `/projects/${projectId}/measurement-summary`,
    { signal },
  );
}

export function validateMeasurements(
  projectId: string,
  payload: Record<string, unknown>,
) {
  return request<MeasurementValidationResponse>(
    `/projects/${projectId}/measurement-validation`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function getDatasetVersions(projectId: string, signal?: AbortSignal) {
  return request<DatasetVersionOption[]>(`/projects/${projectId}/dataset-versions`, {
    signal,
  });
}

export function previewClassification(
  projectId: string,
  payload: Record<string, unknown>,
) {
  return request<ClassificationPreview>(
    `/projects/${projectId}/classification-preview`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function createClassificationExport(
  versionId: string,
  payload: Record<string, unknown>,
) {
  return request<{ export: Record<string, unknown>; job: JobRecord }>(
    `/dataset-versions/${versionId}/exports`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function createClassificationTraining(
  projectId: string,
  payload: Record<string, unknown>,
) {
  return request<TrainingRunRecord>(
    `/projects/${projectId}/classification-training-runs`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function registerClassifier(projectId: string, trainingRunId: string) {
  return request<ModelRecord>(`/projects/${projectId}/classifiers/register-from-run`, {
    method: "POST",
    body: JSON.stringify({ training_run_id: trainingRunId }),
  });
}

export function getTrainingRuns(projectId: string, signal?: AbortSignal) {
  return request<TrainingRunRecord[]>(`/projects/${projectId}/training-runs`, {
    signal,
  });
}

export function getModels(projectId: string, signal?: AbortSignal) {
  return request<ModelRecord[]>(`/projects/${projectId}/models`, { signal });
}

export function getImages(projectId: string, signal?: AbortSignal) {
  return request<ImagePage>(`/projects/${projectId}/images?page=1&page_size=100`, {
    signal,
  });
}

export function createClassificationInference(
  projectId: string,
  payload: Record<string, unknown>,
) {
  return request<JobRecord>(
    `/projects/${projectId}/classification-inference-jobs`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function getClassificationPredictions(
  projectId: string,
  signal?: AbortSignal,
) {
  return request<ClassificationPredictionPage>(
    `/projects/${projectId}/classification-predictions?page=1&page_size=100`,
    { signal },
  );
}

export function reviewClassificationPrediction(
  predictionId: string,
  action: "accept" | "reject",
  labelClassId?: string,
) {
  return request<ClassificationPrediction>(
    `/classification-predictions/${predictionId}/review`,
    {
      method: "POST",
      body: JSON.stringify({ action, label_class_id: labelClassId }),
    },
  );
}

export async function uploadVideo(projectId: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  return request<{ video: VideoAsset; duplicate: boolean }>(
    `/projects/${projectId}/imports/videos`,
    { method: "POST", body: form },
  );
}

export function getVideos(projectId: string, signal?: AbortSignal) {
  return request<VideoAsset[]>(`/projects/${projectId}/videos`, { signal });
}

export function getVideoTracks(videoId: string, signal?: AbortSignal) {
  return request<VideoTrack[]>(`/videos/${videoId}/tracks`, { signal });
}

export function createVideoTrack(videoId: string, payload: Record<string, unknown>) {
  return request<VideoTrack>(`/videos/${videoId}/tracks`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateVideoTrack(trackId: string, payload: Record<string, unknown>) {
  return request<VideoTrack>(`/video-tracks/${trackId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteVideoTrack(trackId: string) {
  return request<void>(`/video-tracks/${trackId}`, { method: "DELETE" });
}

export function calibrateVideo(videoId: string, payload: Record<string, unknown>) {
  return request<VideoAsset>(`/videos/${videoId}/calibration`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function createVideoTracking(videoId: string, payload: Record<string, unknown>) {
  return request<JobRecord>(`/videos/${videoId}/tracking-jobs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function analyzeVideo(videoId: string, payload: Record<string, unknown>) {
  return request<VideoAnalytics>(`/videos/${videoId}/analytics`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
