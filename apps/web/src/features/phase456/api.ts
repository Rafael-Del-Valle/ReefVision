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
  project_id: string;
  image_id: string;
  annotation_id: string | null;
  mask_annotation_id: string | null;
  target_kind: "annotation" | "image" | "mask" | "fragment";
  target_key: string;
  fragment_key: string | null;
  model_id: string;
  inference_job_id: string | null;
  label_set: string;
  classification_mode: string;
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
  predicted_label: string;
  predicted_index: number | null;
  label_class_id: string | null;
  confidence: number;
  probabilities_json: Record<string, number>;
  review_status: string;
  accepted_label_class_id: string | null;
  inference_settings_json: Record<string, unknown>;
  provenance_json: Record<string, unknown>;
  created_at: string;
  reviewed_at: string | null;
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
  created_at: string;
  updated_at: string;
  revision: number;
}

export interface VideoTrackKeyframe {
  id: string | null;
  frame_index: number;
  timestamp_seconds: number | null;
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
  centroid_x: number | null;
  centroid_y: number | null;
  confidence?: number | null;
  source: string;
  manual_edit: boolean;
  automated_provenance: Record<string, unknown> | null;
  deleted_at: string | null;
  revision: number;
}

export interface VideoTrack {
  id: string;
  video_id: string;
  label_class_id: string | null;
  origin_job_id: string | null;
  track_number: number;
  name: string | null;
  geometry_kind: string;
  keyframes: VideoTrackKeyframe[];
  interpolation: string;
  status: string;
  source_type: string;
  is_ground_truth: boolean;
  metadata_json: Record<string, unknown>;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  revision: number;
}

export interface VideoTrackOperation {
  operation: string;
  operation_id: string | null;
  tracks: VideoTrack[];
  deleted_track_ids: string[];
  warnings: string[];
  replayed: boolean;
}

export interface VideoZone {
  id: string;
  video_id: string;
  name: string;
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface VideoAnalytics {
  analysis_id: string | null;
  video_id: string;
  fps: number;
  coordinate_unit: "pixels";
  timing_source: "video_fps" | "observation_timestamps";
  distance_per_pixel: number | null;
  physical_unit: string | null;
  tracks: Array<{
    track_id: string;
    tracker_id: number;
    label_class_id: string | null;
    duration_seconds: number;
    distance_pixels: number;
    net_displacement_pixels: number;
    total_path_length_pixels: number;
    path_tortuosity: number | null;
    mean_speed_pixels_per_second: number;
    maximum_speed_pixels_per_second: number;
    mean_acceleration_pixels_per_second_squared: number;
    maximum_acceleration_pixels_per_second_squared: number;
    mean_turning_angle_degrees: number | null;
    cumulative_turning_angle_degrees: number;
    mean_angular_velocity_degrees_per_second: number | null;
    mean_distance_to_wall_pixels: number;
    active_time_seconds: number;
    inactive_time_seconds: number;
    distance_physical: number | null;
    mean_speed_physical_per_second: number | null;
    mean_distance_to_wall_physical: number | null;
    physical_unit: string | null;
    zone_time_seconds: Record<string, number>;
  }>;
  schooling: Record<string, unknown>;
  zones: Record<string, unknown>[];
  heatmap: Record<string, unknown>;
  warnings: string[];
}

export interface VideoTrackingEvaluation {
  evaluation_id: string | null;
  video_id: string;
  candidate_job_id: string | null;
  evaluable: boolean;
  ground_truth_track_count: number;
  candidate_track_count: number;
  matched_observation_count: number;
  false_positive_observation_count: number;
  false_negative_observation_count: number;
  localization_iou_mean: number | null;
  detection_precision: number | null;
  detection_recall: number | null;
  identity_switch_count: number;
  fragmentation_count: number;
  mostly_tracked_count: number;
  mostly_lost_count: number;
  per_track: Array<Record<string, unknown>>;
  per_frame: Array<Record<string, unknown>>;
  configuration: Record<string, unknown>;
  provenance: Record<string, unknown>;
  warnings: string[];
}

export interface VideoExportResponse {
  export_id: string;
  job: JobRecord;
}

export interface VideoZoneRequest {
  name: string;
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
}

export interface VideoCalibrationRequest {
  distance_per_pixel: number | null;
  physical_unit: string | null;
}

export interface VideoTrackPatchRequest {
  expected_revision: number;
  operation_id?: string;
  name?: string | null;
  label_class_id?: string | null;
  is_ground_truth?: boolean;
}

export interface VideoObservationWriteRequest {
  expected_revision: number;
  operation_id?: string;
  observation_id?: string;
  frame_index: number;
  timestamp_seconds?: number | null;
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
  label_class_id?: string | null;
  confidence?: number | null;
}

export interface VideoTrackOperationRequest {
  expected_revision: number;
  operation_id?: string;
  operation: string;
  frame_index?: number;
  target_track_id?: string;
  observation_ids?: string[];
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    headers: {
      ...(options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...options.headers,
    },
    ...options,
  });
  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) message = payload.detail;
    } catch {
      // Preserve the status message when the API returns a non-JSON body.
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function getProjectMeasurements(projectId: string, signal?: AbortSignal) {
  return request<ProjectMeasurementSummary>(
    `/projects/${projectId}/measurements/summary`,
    { signal },
  );
}

export function validateProjectMeasurements(
  projectId: string,
  signal?: AbortSignal,
) {
  return request<MeasurementValidationResponse>(
    `/projects/${projectId}/measurements/validation`,
    { signal },
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
  return request<ModelRecord>(
    `/projects/${projectId}/classifiers/register-from-run`,
    {
      method: "POST",
      body: JSON.stringify({ training_run_id: trainingRunId }),
    },
  );
}

export function getTrainingRuns(projectId: string, signal?: AbortSignal) {
  return request<TrainingRunRecord[]>(`/projects/${projectId}/training-runs`, {
    signal,
  });
}

export function getModels(projectId: string, signal?: AbortSignal) {
  return request<ModelRecord[]>(`/projects/${projectId}/models`, { signal });
}

export function getJob(jobId: string, signal?: AbortSignal) {
  return request<JobRecord>(`/jobs/${jobId}`, { signal });
}

export function getImages(projectId: string, signal?: AbortSignal) {
  return request<ImagePage>(
    `/projects/${projectId}/images?page=1&page_size=100`,
    {
      signal,
    },
  );
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

export function getVideoZones(videoId: string, signal?: AbortSignal) {
  return request<VideoZone[]>(`/videos/${videoId}/zones`, { signal });
}

export function createVideoZone(videoId: string, payload: VideoZoneRequest) {
  return request<VideoZone>(`/videos/${videoId}/zones`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateVideoZone(
  videoId: string,
  zoneId: string,
  expectedRevision: number,
  payload: VideoZoneRequest,
) {
  return request<VideoZone>(`/videos/${videoId}/zones/${zoneId}`, {
    method: "PATCH",
    body: JSON.stringify({ expected_revision: expectedRevision, ...payload }),
  });
}

export function deleteVideoZone(
  videoId: string,
  zoneId: string,
  expectedRevision: number,
) {
  return request<void>(`/videos/${videoId}/zones/${zoneId}`, {
    method: "DELETE",
    body: JSON.stringify({ expected_revision: expectedRevision }),
  });
}

export function updateVideoCalibration(
  videoId: string,
  payload: VideoCalibrationRequest,
) {
  return request<VideoAsset>(`/videos/${videoId}/calibration`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function createVideoTrackingJob(
  projectId: string,
  videoId: string,
  payload: Record<string, unknown>,
) {
  return request<JobRecord>(
    `/projects/${projectId}/videos/${videoId}/tracking-jobs`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function updateVideoTrack(
  trackId: string,
  payload: VideoTrackPatchRequest,
) {
  return request<VideoTrackOperation>(`/video-tracks/${trackId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function addVideoObservation(
  trackId: string,
  payload: VideoObservationWriteRequest,
) {
  return request<VideoTrackOperation>(`/video-tracks/${trackId}/observations`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateVideoObservation(
  trackId: string,
  observationId: string,
  payload: VideoObservationWriteRequest,
) {
  return request<VideoTrackOperation>(
    `/video-tracks/${trackId}/observations/${observationId}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );
}

export function deleteVideoObservation(
  trackId: string,
  observationId: string,
  expectedRevision: number,
  operationId?: string,
) {
  return request<VideoTrackOperation>(
    `/video-tracks/${trackId}/observations/${observationId}`,
    {
      method: "DELETE",
      body: JSON.stringify({
        expected_revision: expectedRevision,
        operation_id: operationId,
      }),
    },
  );
}

export function applyVideoTrackOperation(
  trackId: string,
  payload: VideoTrackOperationRequest,
) {
  return request<VideoTrackOperation>(`/video-tracks/${trackId}/operations`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function analyzeVideo(
  videoId: string,
  payload: Record<string, unknown>,
) {
  return request<VideoAnalytics>(`/videos/${videoId}/analysis`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function evaluateVideoTracking(
  videoId: string,
  payload: Record<string, unknown>,
) {
  return request<VideoTrackingEvaluation>(`/videos/${videoId}/tracking-evaluation`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createVideoDataExport(
  videoId: string,
  payload: Record<string, unknown>,
) {
  return request<VideoExportResponse>(`/videos/${videoId}/exports/data`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createRenderedVideoExport(
  videoId: string,
  payload: Record<string, unknown>,
) {
  return request<VideoExportResponse>(`/videos/${videoId}/exports/rendered`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
