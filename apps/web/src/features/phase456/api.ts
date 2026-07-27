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

export interface MeasurementValidationSummary {
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
}

export interface MeasurementValidationResponse {
  project_id: string;
  mask_count: number;
  observation_count: number;
  passed_count: number;
  failed_count: number;
  warnings: string[];
  summaries: MeasurementValidationSummary[];
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
  managed_path?: string;
  sha256?: string;
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

export interface VideoTrajectorySample {
  observation_id: string | null;
  frame_index: number;
  timestamp_seconds: number;
  center_x_pixels: number;
  center_y_pixels: number;
  center_x_physical: number | null;
  center_y_physical: number | null;
  distance_from_previous_pixels?: number | null;
  distance_from_previous_physical?: number | null;
  speed_pixels_per_second?: number | null;
  speed_physical_per_second?: number | null;
  acceleration_pixels_per_second_squared?: number | null;
  turning_angle_degrees?: number | null;
  angular_velocity_degrees_per_second?: number | null;
  interpolated: boolean;
  manual_edit: boolean;
}

export interface VideoTrackAnalytics {
  track_id: string;
  tracker_id: number;
  label_class_id: string | null;
  first_frame?: number;
  last_frame?: number;
  observed_frame_count?: number;
  persisted_observation_count?: number;
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
  net_displacement_physical?: number | null;
  mean_speed_physical_per_second: number | null;
  maximum_speed_physical_per_second?: number | null;
  mean_acceleration_physical_per_second_squared?: number | null;
  maximum_acceleration_physical_per_second_squared?: number | null;
  mean_distance_to_wall_physical: number | null;
  physical_unit: string | null;
  zone_time_seconds: Record<string, number>;
  trajectory: VideoTrajectorySample[];
}

export interface VideoHeatmapCell {
  column: number;
  row: number;
  observation_count: number;
  occupancy_seconds: number;
}

export interface VideoZoneEvent {
  track_id: string;
  zone_name: string;
  event_type: "entry" | "exit";
  frame_index: number;
  timestamp_seconds: number;
}

export interface VideoAnalytics {
  analysis_id: string | null;
  video_id: string;
  fps: number;
  coordinate_unit: "pixels";
  timing_source: "video_fps" | "observation_timestamps";
  distance_per_pixel: number | null;
  physical_unit: string | null;
  tracks: VideoTrackAnalytics[];
  school_by_frame: Array<Record<string, unknown>>;
  heatmap_bins_x: number;
  heatmap_bins_y: number;
  heatmap: VideoHeatmapCell[];
  zone_events: VideoZoneEvent[];
  configuration: Record<string, unknown>;
  source_track_revisions: Array<Record<string, unknown>>;
  analysis_sha256: string | null;
  warnings: string[];
}

export interface TrackingMetricSummary {
  candidate_name: string;
  parameters: Record<string, unknown>;
  reference_detection_count?: number;
  predicted_detection_count?: number;
  matched_detection_count?: number;
  false_positive_count?: number;
  false_negative_count?: number;
  false_positive_track_count: number;
  false_negative_track_count: number;
  identity_switch_count: number;
  fragmentation_count: number;
  mostly_tracked_count: number;
  mostly_lost_count: number;
  mota: number;
  motp: number;
  localization_iou: number;
  detection_precision: number;
  detection_recall: number;
  id_precision?: number;
  id_recall?: number;
  idf1: number;
  detection_accuracy?: number;
  association_accuracy?: number;
  hota: number;
  mean_center_error?: number | null;
  mean_depth_error?: number | null;
  mean_track_lifespan_frames?: number | null;
  mean_track_continuity: number | null;
  matches?: Array<Record<string, unknown>>;
  per_frame: Array<Record<string, unknown>>;
  per_track: Array<Record<string, unknown>>;
}

export interface VideoTrackingEvaluation {
  evaluation_id: string;
  video_id: string;
  ground_truth_available: boolean;
  minimum_iou: number;
  ranked_by_hota: TrackingMetricSummary[];
  best_candidate_name: string | null;
  configuration: Record<string, unknown>;
  source_track_revisions: Array<Record<string, unknown>>;
  evaluation_sha256: string;
  warnings: string[];
}

export interface VideoDataExportResponse {
  artifact_id: string;
  video_id: string;
  archive_path: string;
  manifest_path: string;
  archive_sha256: string;
  archive_size_bytes: number;
  manifest_sha256: string;
  formats: string[];
}

export interface VideoRenderExportResponse {
  job: JobRecord;
}

export type VideoExportResponse =
  VideoDataExportResponse | VideoRenderExportResponse;

export interface VideoZoneRequest {
  name: string;
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
}

export interface VideoZoneUpdateRequest extends VideoZoneRequest {
  expected_revision: number;
}

export interface VideoCalibrationRequest {
  distance_per_pixel: number;
  unit: string;
  source?: string;
  notes?: string | null;
}

export interface VideoTrackPatchRequest {
  expected_revision: number;
  operation_id?: string;
  name?: string | null;
  label_class_id?: string | null;
  status?: string;
  is_ground_truth?: boolean;
}

export interface VideoObservationWriteRequest {
  expected_revision: number;
  operation_id?: string;
  frame_index: number;
  timestamp_seconds?: number | null;
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
  confidence?: number | null;
}

export interface VideoObservationAddRequest {
  expected_revision: number;
  operation_id?: string;
  observation: Record<string, unknown>;
}

export interface VideoRevisionRequest {
  expected_revision: number;
  operation_id?: string;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
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
      const payload = (await response.json()) as {
        detail?: string | { message?: string; reason?: string };
      };
      if (typeof payload.detail === "string") message = payload.detail;
      if (payload.detail && typeof payload.detail === "object") {
        message = payload.detail.message ?? payload.detail.reason ?? message;
      }
    } catch {
      // Preserve the status message when the API returns a non-JSON body.
    }
    throw new Error(message);
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

export const getProjectMeasurements = getMeasurementSummary;

export function validateMeasurements(
  projectId: string,
  payload: Record<string, unknown>,
  signal?: AbortSignal,
) {
  return request<MeasurementValidationResponse>(
    `/projects/${projectId}/measurement-validation`,
    { method: "POST", body: JSON.stringify(payload), signal },
  );
}

export const validateProjectMeasurements = validateMeasurements;

export function getDatasetVersions(projectId: string, signal?: AbortSignal) {
  return request<DatasetVersionOption[]>(
    `/projects/${projectId}/dataset-versions`,
    {
      signal,
    },
  );
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

export function cancelJob(jobId: string) {
  return request<JobRecord>(`/jobs/${jobId}/cancel`, { method: "POST" });
}

export function getImages(projectId: string, signal?: AbortSignal) {
  return request<ImagePage>(
    `/projects/${projectId}/images?page=1&page_size=100`,
    { signal },
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

export function createVideoTrack(
  videoId: string,
  payload: Record<string, unknown>,
) {
  return request<VideoTrack>(`/videos/${videoId}/tracks`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getVideoZones(videoId: string, signal?: AbortSignal) {
  return request<VideoZone[]>(`/videos/${videoId}/zones`, { signal });
}

export function createVideoZone(
  videoId: string,
  payload: Record<string, unknown>,
) {
  return request<VideoZone>(`/videos/${videoId}/zones`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateVideoZone(
  zoneId: string,
  payload: Record<string, unknown>,
): Promise<VideoZone>;
export function updateVideoZone(
  _videoId: string,
  zoneId: string,
  expectedRevision: number,
  payload: VideoZoneRequest,
): Promise<VideoZone>;
export function updateVideoZone(
  first: string,
  second: string | Record<string, unknown>,
  third?: number,
  fourth?: VideoZoneRequest,
) {
  const zoneId = typeof second === "string" ? second : first;
  const payload =
    typeof second === "string"
      ? { expected_revision: third, ...fourth }
      : second;
  return request<VideoZone>(`/video-zones/${zoneId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function deleteVideoZone(
  zoneId: string,
  expectedRevision: number,
): Promise<void>;
export function deleteVideoZone(
  _videoId: string,
  zoneId: string,
  expectedRevision: number,
): Promise<void>;
export function deleteVideoZone(
  first: string,
  second: string | number,
  third?: number,
) {
  const zoneId = typeof second === "string" ? second : first;
  const expectedRevision = typeof second === "number" ? second : third;
  return request<void>(
    `/video-zones/${zoneId}?expected_revision=${encodeURIComponent(String(expectedRevision))}`,
    { method: "DELETE" },
  );
}

export function calibrateVideo(
  videoId: string,
  payload: VideoCalibrationRequest,
) {
  return request<VideoAsset>(`/videos/${videoId}/calibration`, {
    method: "PUT",
    body: JSON.stringify({ source: "manual", ...payload }),
  });
}

export const updateVideoCalibration = calibrateVideo;

export function createVideoTracking(
  videoId: string,
  payload: Record<string, unknown>,
) {
  return request<JobRecord>(`/videos/${videoId}/tracking-jobs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createVideoTrackingJob(
  _projectId: string,
  videoId: string,
  payload: Record<string, unknown>,
) {
  return createVideoTracking(videoId, payload);
}

export function updateVideoTrack(
  trackId: string,
  payload: VideoTrackPatchRequest,
) {
  return request<VideoTrack>(`/video-tracks/${trackId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function addVideoTrackObservation(
  trackId: string,
  payload: Record<string, unknown>,
) {
  return request<VideoTrackOperation>(`/video-tracks/${trackId}/observations`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function addVideoObservation(
  trackId: string,
  payload: VideoObservationWriteRequest,
) {
  const { expected_revision, operation_id, ...observation } = payload;
  return addVideoTrackObservation(trackId, {
    expected_revision,
    operation_id,
    observation,
  });
}

export function updateVideoTrackObservation(
  trackId: string,
  observationId: string,
  payload: Record<string, unknown>,
) {
  return request<VideoTrackOperation>(
    `/video-tracks/${trackId}/observations/${observationId}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );
}

export const updateVideoObservation = updateVideoTrackObservation;

export function deleteVideoTrackObservation(
  trackId: string,
  observationId: string,
  payload: VideoRevisionRequest,
) {
  return request<VideoTrackOperation>(
    `/video-tracks/${trackId}/observations/${observationId}/delete`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function restoreVideoTrackObservation(
  trackId: string,
  observationId: string,
  payload: VideoRevisionRequest,
) {
  return request<VideoTrackOperation>(
    `/video-tracks/${trackId}/observations/${observationId}/restore`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function deleteVideoObservation(
  trackId: string,
  observationId: string,
  expectedRevision: number,
  operationId?: string,
) {
  return deleteVideoTrackObservation(trackId, observationId, {
    expected_revision: expectedRevision,
    operation_id: operationId,
  });
}

export function archiveVideoTrack(
  trackId: string,
  payload: VideoRevisionRequest,
) {
  return request<VideoTrackOperation>(`/video-tracks/${trackId}/delete`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function splitVideoTrack(
  trackId: string,
  payload: Record<string, unknown>,
) {
  return request<VideoTrackOperation>(`/video-tracks/${trackId}/split`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function mergeVideoTracks(payload: Record<string, unknown>) {
  return request<VideoTrackOperation>(`/video-tracks/merge`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function correctVideoTrackIdentity(payload: Record<string, unknown>) {
  return request<VideoTrackOperation>(`/video-tracks/identity-switch`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function reassignVideoTrackObservations(
  payload: Record<string, unknown>,
) {
  return request<VideoTrackOperation>(`/video-tracks/reassign-observations`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function analyzeVideo(
  videoId: string,
  payload: Record<string, unknown>,
) {
  return request<VideoAnalytics>(`/videos/${videoId}/analytics`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function evaluateVideoTracking(
  videoId: string,
  payload: Record<string, unknown>,
) {
  return request<VideoTrackingEvaluation>(
    `/videos/${videoId}/tracking-evaluations`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function getVideoTrackingEvaluations(
  videoId: string,
  signal?: AbortSignal,
) {
  return request<VideoTrackingEvaluation[]>(
    `/videos/${videoId}/tracking-evaluations`,
    { signal },
  );
}

export function createVideoDataExport(
  videoId: string,
  payload: Record<string, unknown>,
) {
  return request<VideoDataExportResponse>(`/videos/${videoId}/data-exports`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createVideoRenderExport(
  videoId: string,
  payload: Record<string, unknown>,
) {
  return request<VideoRenderExportResponse>(
    `/videos/${videoId}/render-exports`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export const createRenderedVideoExport = createVideoRenderExport;
