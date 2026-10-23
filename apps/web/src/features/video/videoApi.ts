import { getApiBaseUrl } from "../../runtime";
import type { JobRecord } from "../../api/client";

export interface TrackingModelRecord {
  id: string;
  project_id: string;
  purpose: "detector" | "segmenter" | string;
  display_name: string;
  source_filename: string;
  managed_path: string;
  sha256: string;
  file_size_bytes: number;
  framework: string;
  task: "detect" | "segment" | "pose" | string;
  provider_name: string;
  provider_version: string;
  class_map_json: Record<string, unknown>;
  input_size_json: Record<string, unknown> | null;
  metadata_json: Record<string, unknown>;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface PoseLandmarkGroup {
  name: string;
  count: number;
}

export interface PoseLandmarkSchema {
  schema_version: "pose-landmarks-0001";
  schema_id?: string;
  schema_revision?: number;
  content_hash?: string;
  groups: PoseLandmarkGroup[];
  expanded_labels: string[];
  keypoint_count: number;
  allows_repeated_labels: boolean;
}

export function poseLandmarkSchemaFromMetadata(
  metadata: Record<string, unknown> | null | undefined,
): PoseLandmarkSchema | null {
  const raw = metadata?.pose_landmark_schema;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const schema = raw as Record<string, unknown>;
  if (schema.schema_version !== "pose-landmarks-0001") return null;
  if (!Array.isArray(schema.groups) || !Array.isArray(schema.expanded_labels)) {
    return null;
  }

  const groups: PoseLandmarkGroup[] = [];
  for (const rawGroup of schema.groups) {
    if (!rawGroup || typeof rawGroup !== "object" || Array.isArray(rawGroup)) {
      return null;
    }
    const group = rawGroup as Record<string, unknown>;
    if (
      typeof group.name !== "string" ||
      typeof group.count !== "number" ||
      !Number.isInteger(group.count) ||
      group.count < 1
    ) {
      return null;
    }
    groups.push({ name: group.name, count: group.count });
  }

  const expandedLabels = schema.expanded_labels.filter(
    (label): label is string => typeof label === "string",
  );
  if (expandedLabels.length !== schema.expanded_labels.length) return null;

  const keypointCount =
    typeof schema.keypoint_count === "number"
      ? schema.keypoint_count
      : expandedLabels.length;

  const schemaId =
    typeof schema.schema_id === "string" && schema.schema_id.length > 0
      ? schema.schema_id
      : undefined;
  const schemaRevision =
    typeof schema.schema_revision === "number" &&
    Number.isInteger(schema.schema_revision) &&
    schema.schema_revision >= 1
      ? schema.schema_revision
      : undefined;
  const contentHash =
    typeof schema.content_hash === "string" ? schema.content_hash : undefined;

  return {
    schema_version: "pose-landmarks-0001",
    schema_id: schemaId,
    schema_revision: schemaRevision,
    content_hash: contentHash,
    groups,
    expanded_labels: expandedLabels,
    keypoint_count: keypointCount,
    allows_repeated_labels:
      schema.allows_repeated_labels === true ||
      groups.some((group) => group.count > 1),
  };
}

export interface VideoTelemetryMetadata {
  found: boolean;
  available: boolean;
  source_type: "dji_srt" | "airdata" | null;
  source_path: string | null;
  path_kind: "managed" | "external" | null;
  sample_count: number;
  error: string | null;
}

export interface AirDataAlignmentRecord {
  time_offset_s: number;
  evidence: string | null;
}

export type VideoGeoreferencingReadinessState =
  | "ready"
  | "missing_calibration"
  | "invalid_calibration"
  | "missing_surface_reference"
  | "missing_telemetry"
  | "alignment_problem"
  | "synchronization_problem"
  | "zoom_mismatch";

export type VideoGeoreferencingReadinessIssueCode =
  | "missing_calibration"
  | "invalid_calibration"
  | "missing_surface_reference"
  | "missing_telemetry"
  | "invalid_airdata_alignment"
  | "telemetry_out_of_sync"
  | "calibration_zoom_mismatch";

export interface VideoGeoreferencingReadinessIssue {
  code: VideoGeoreferencingReadinessIssueCode;
  message: string;
}

export interface VideoGeoreferencingReadinessRecord {
  schema_version: "video-georeferencing-readiness-0001";
  video_id: string;
  project_id: string;
  ready: boolean;
  state: VideoGeoreferencingReadinessState;
  issues: VideoGeoreferencingReadinessIssue[];
  srt_available: boolean;
  airdata_available: boolean;
  airdata_alignment_valid: boolean;
  surface_reference_configured: boolean;
  calibration_available: boolean;
  calibration_valid: boolean;
  calibration_checksum_sha256: string | null;
  sampled_frame_indices: number[];
  synchronized_frame_count: number;
  sampled_frame_count: number;
  maximum_sync_error_s: number | null;
  zoom_compatible: boolean | null;
  max_allowed_sync_error_s: number;
}

export interface VideoGeoreferencingCalibrationRecord {
  schema_version: "video-georeferencing-calibration-0001";
  video_id: string;
  width_px: number;
  height_px: number;
  fx_px: number;
  fy_px: number;
  cx_px: number;
  cy_px: number;
  distortion_coefficients: number[];
  digital_zoom_ratio: number;
  camera_mode: string;
  source: string;
  evidence: string;
  checksum_sha256: string;
  calibration_revision: number;
  calibration_updated_at: string;
  video_revision: number;
}

export interface VideoGeoreferencingCalibrationSetPayload {
  width_px: number;
  height_px: number;
  fx_px: number;
  fy_px: number;
  cx_px: number;
  cy_px: number;
  distortion_coefficients: number[];
  digital_zoom_ratio: number;
  camera_mode: string;
  source: string;
  evidence: string;
}

export interface VideoAssetRecord {
  id: string;
  project_id: string;
  original_filename: string;
  managed_path: string;
  sha256: string;
  media_type: string;
  width_px: number;
  height_px: number;
  frame_count: number;
  fps: number;
  duration_seconds: number;
  metadata_json: Record<string, unknown>;
  frame_directory_path: string | null;
  extraction_job_id: string | null;
  status: string;
  revision: number;
  created_at: string;
  updated_at: string;
  telemetry: VideoTelemetryMetadata;
  airdata_telemetry: VideoTelemetryMetadata;
  airdata_alignment: AirDataAlignmentRecord;
}

export type VideoPoseKeypoint = [number, number, number];

export interface VideoPoseObservation {
  id: string;
  semantic_label: string;
  occurrence_index: number;
  x: number;
  y: number;
  confidence: number | null;
  status: "visible" | "occluded" | "out_of_frame" | "uncertain" | "absent";
  source: "model" | "manual" | "corrected";
}

export interface PoseProviderUncertaintyEvidence {
  schema_version: "pose-provider-uncertainty-0001";
  provider_id: string;
  provider_version: string;
  capabilities: {
    keypoint_confidence: boolean;
    heatmap_entropy: boolean;
    paf_ambiguity: boolean;
  };
  available_signals: string[];
  mean_keypoint_confidence: number | null;
  minimum_keypoint_confidence: number | null;
  heatmap_entropy: number | null;
  paf_ambiguity: number | null;
}

export interface VideoTrackKeyframe {
  frame: number;
  bbox: [number, number, number, number];
  confidence?: number | null;
  keypoints?: VideoPoseKeypoint[] | null;
  pose_observations?: VideoPoseObservation[] | null;
  pose_uncertainty?: PoseProviderUncertaintyEvidence | null;
  mask_polygons?: [number, number][][] | null;
}

export interface VideoTrackRecord {
  id: string;
  video_id: string;
  label_class_id: string;
  track_number: number;
  geometry_kind: string;
  keyframes_json: VideoTrackKeyframe[];
  interpolation: "linear" | "hold" | string;
  status: string;
  source_model_id: string | null;
  source_job_id: string | null;
  metadata_json: Record<string, unknown> | null;
  revision: number;
}

export interface InterpolatedTrackFrame {
  frame: number;
  timestamp_seconds: number;
  bbox: [number, number, number, number];
  center_x: number;
  center_y: number;
  source: "keyframe" | "interpolated";
}

export interface VideoTrackInterpolation {
  track_id: string;
  video_id: string;
  interpolation: string;
  frames: InterpolatedTrackFrame[];
}

export interface VideoTrackAnalytics {
  track_id: string;
  video_id: string;
  track_number: number;
  label_class_id: string;
  first_frame: number;
  last_frame: number;
  observed_frame_count: number;
  duration_seconds: number;
  path_length_pixels: number;
  mean_speed_pixels_per_second: number;
  maximum_speed_pixels_per_second: number;
  displacement_pixels: number;
  mean_bbox_area_pixels: number;
  occupancy_grid: Record<string, number>;
}

export interface VideoFrameObjectMetric {
  track_id: string;
  track_number: number;
  label_class_id: string;
  bbox: [number, number, number, number];
  center_x: number;
  center_y: number;
  nearest_neighbor_track_id: string | null;
  nearest_neighbor_distance_pixels: number | null;
  nearest_neighbor_track_id_meters: string | null;
  nearest_neighbor_distance_meters: number | null;
}

export interface VideoFrameSpatialMetrics {
  video_id: string;
  frame_index: number;
  object_count: number;
  mean_nearest_neighbor_distance_pixels: number | null;
  minimum_nearest_neighbor_distance_pixels: number | null;
  mean_nearest_neighbor_distance_meters: number | null;
  minimum_nearest_neighbor_distance_meters: number | null;
  objects: VideoFrameObjectMetric[];
}

export interface VideoTrackingRun {
  job_id: string;
  project_id: string;
  video_id: string;
  status: string;
  stage: string;
  tracker: string;
  model_id: string;
  tracking_mode?: "auto" | "detect" | "segment" | "hybrid";
  segmentation_model_id?: string | null;
  link_detections: boolean;
  confidence: number;
  iou: number;
  device: string;
  minimum_track_frames: number;
  progress_current: number;
  progress_total: number;
  track_count: number;
  observation_count: number;
  live_detection_count: number;
  live_observation_count: number;
  live_tracks_seen: number;
  heartbeat_at: string | null;
  stale: boolean;
  unmapped_labels: string[];
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface VideoTrackingEvaluationPerTrack {
  ground_truth_track_id: string;
  ground_truth_track_number: number;
  label_class_id: string;
  ground_truth_observations: number;
  matched_observations: number;
  missed_observations: number;
  recall: number;
  id_switches: number;
  fragmentations: number;
  matched_prediction_track_ids: string[];
  mean_iou: number | null;
  mean_center_error_pixels: number | null;
}

export interface VideoTrackingEvaluation {
  schema_version: "video-tracking-evaluation-0001";
  video_id: string;
  start_frame: number;
  end_frame: number;
  iou_threshold: number;
  class_aware: boolean;
  matching_policy: "temporal-continuity-then-greedy-iou";
  ground_truth_track_ids: string[];
  prediction_track_ids: string[];
  ground_truth_track_count: number;
  prediction_track_count: number;
  ground_truth_observations: number;
  prediction_observations: number;
  matched_observations: number;
  missed_observations: number;
  false_positive_observations: number;
  recall: number;
  precision: number;
  missed_tracks: number;
  false_positive_tracks: number;
  false_positive_prediction_track_ids: string[];
  id_switches: number;
  fragmentations: number;
  mean_iou: number | null;
  mean_center_error_pixels: number | null;
  mota: number;
  per_track: VideoTrackingEvaluationPerTrack[];
}

export interface VideoTrackingBenchmarkCandidate {
  name: string;
  prediction_track_ids?: string[];
  source_job_id?: string;
}

export interface VideoTrackingBenchmarkResult {
  rank: number;
  name: string;
  source_job_id: string | null;
  prediction_track_ids: string[];
  tracker: string | null;
  model_id: string | null;
  job_status: string | null;
  tracking_settings: Record<string, unknown>;
  evaluation: VideoTrackingEvaluation;
}

export interface VideoTrackingBenchmark {
  schema_version: "video-tracking-benchmark-0001";
  video_id: string;
  winner: string;
  ground_truth_track_ids: string[];
  start_frame: number;
  end_frame: number;
  iou_threshold: number;
  class_aware: boolean;
  results: VideoTrackingBenchmarkResult[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = `Video request failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string") message = payload.detail;
    } catch {
      // Keep the HTTP fallback.
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function requestOptional<T>(
  path: string,
  init?: RequestInit,
): Promise<T | null> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...init?.headers,
    },
  });
  if (response.status === 404) return null;
  if (!response.ok) {
    let message = `Video request failed with HTTP ${response.status}`;
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

export function videoContentUrl(videoId: string): string {
  return `${getApiBaseUrl()}/videos/${encodeURIComponent(videoId)}/content`;
}

export function videoFrameUrl(videoId: string, frame: number): string {
  return `${getApiBaseUrl()}/videos/${encodeURIComponent(videoId)}/frames/${frame}`;
}

export function getVideos(
  projectId: string,
  signal?: AbortSignal,
): Promise<VideoAssetRecord[]> {
  return request<VideoAssetRecord[]>(
    `/projects/${encodeURIComponent(projectId)}/videos`,
    { signal },
  );
}

export interface VideoImportOptions {
  telemetryFile?: File | null;
  airdataFile?: File | null;
  airdataTimeOffsetSeconds?: number;
  airdataTimeOffsetEvidence?: string | null;
}

export function importVideo(
  projectId: string,
  file: File,
  options: VideoImportOptions = {},
): Promise<VideoAssetRecord> {
  const form = new FormData();
  form.append("file", file);
  if (options.telemetryFile) {
    form.append("telemetry_file", options.telemetryFile);
  }
  if (options.airdataFile) {
    form.append("airdata_file", options.airdataFile);
    form.append(
      "airdata_time_offset_s",
      String(options.airdataTimeOffsetSeconds ?? 0),
    );
    const evidence = options.airdataTimeOffsetEvidence?.trim();
    if (evidence) {
      form.append("airdata_time_offset_evidence", evidence);
    }
  }
  return request<VideoAssetRecord>(
    `/projects/${encodeURIComponent(projectId)}/imports/videos`,
    { method: "POST", body: form },
  );
}

export function importVideoPath(
  projectId: string,
  sourcePath: string,
): Promise<VideoAssetRecord> {
  const form = new FormData();
  form.append("source_path", sourcePath);

  return request<VideoAssetRecord>(
    `/projects/${encodeURIComponent(projectId)}/imports/videos/path`,
    { method: "POST", body: form },
  );
}

export function getVideoGeoreferencingReadiness(
  videoId: string,
  signal?: AbortSignal,
): Promise<VideoGeoreferencingReadinessRecord> {
  return request<VideoGeoreferencingReadinessRecord>(
    `/videos/${encodeURIComponent(videoId)}/georeferencing-readiness`,
    { signal, cache: "no-store" },
  );
}

export function getVideoGeoreferencingCalibration(
  videoId: string,
  signal?: AbortSignal,
): Promise<VideoGeoreferencingCalibrationRecord | null> {
  return requestOptional<VideoGeoreferencingCalibrationRecord>(
    `/videos/${encodeURIComponent(videoId)}/georeferencing-calibration`,
    { signal },
  );
}

export function setVideoGeoreferencingCalibration(
  videoId: string,
  payload: VideoGeoreferencingCalibrationSetPayload,
): Promise<VideoGeoreferencingCalibrationRecord> {
  return request<VideoGeoreferencingCalibrationRecord>(
    `/videos/${encodeURIComponent(videoId)}/georeferencing-calibration`,
    { method: "PUT", body: JSON.stringify(payload) },
  );
}

export function clearVideoGeoreferencingCalibration(
  videoId: string,
): Promise<void> {
  return request<void>(
    `/videos/${encodeURIComponent(videoId)}/georeferencing-calibration`,
    { method: "DELETE" },
  );
}

export function extractVideoFrames(
  videoId: string,
  everyNFrames: number,
): Promise<JobRecord> {
  return request<JobRecord>(`/videos/${encodeURIComponent(videoId)}/extract`, {
    method: "POST",
    body: JSON.stringify({ every_n_frames: everyNFrames }),
  });
}

export function getVideoTracks(
  videoId: string,
  signal?: AbortSignal,
): Promise<VideoTrackRecord[]> {
  return request<VideoTrackRecord[]>(
    `/videos/${encodeURIComponent(videoId)}/tracks`,
    { signal },
  );
}

export function getVideoTrackingRuns(
  videoId: string,
  signal?: AbortSignal,
): Promise<VideoTrackingRun[]> {
  const pollToken = Date.now();
  return request<VideoTrackingRun[]>(
    `/videos/${encodeURIComponent(videoId)}/tracking-runs?poll=${pollToken}`,
    { signal, cache: "no-store" },
  );
}

export function createVideoTrack(
  videoId: string,
  payload: {
    label_class_id: string;
    track_number?: number | null;
    geometry_kind: "bbox";
    keyframes: VideoTrackKeyframe[];
    interpolation: "linear" | "hold";
    status: string;
  },
): Promise<VideoTrackRecord> {
  return request<VideoTrackRecord>(
    `/videos/${encodeURIComponent(videoId)}/tracks`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function updateVideoTrack(
  trackId: string,
  payload: {
    base_revision: number;
    label_class_id: string;
    keyframes: VideoTrackKeyframe[];
    interpolation: "linear" | "hold";
    status: string;
  },
): Promise<VideoTrackRecord> {
  return request<VideoTrackRecord>(
    `/video-tracks/${encodeURIComponent(trackId)}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
  );
}

export function deleteVideoTrack(trackId: string): Promise<void> {
  return request<void>(`/video-tracks/${encodeURIComponent(trackId)}`, {
    method: "DELETE",
  });
}

export function deleteVideoTracks(
  videoId: string,
  machineOnly = true,
): Promise<{ deleted_tracks: number }> {
  return request<{ deleted_tracks: number }>(
    `/videos/${encodeURIComponent(videoId)}/tracks?machine_only=${machineOnly}`,
    { method: "DELETE" },
  );
}

export function getVideoFrameSpatialMetrics(
  videoId: string,
  frameIndex: number,
  signal?: AbortSignal,
): Promise<VideoFrameSpatialMetrics> {
  return request<VideoFrameSpatialMetrics>(
    `/videos/${encodeURIComponent(videoId)}/spatial-metrics?frame=${frameIndex}`,
    { signal },
  );
}

export function getVideoTrackInterpolation(
  trackId: string,
  signal?: AbortSignal,
): Promise<VideoTrackInterpolation> {
  return request<VideoTrackInterpolation>(
    `/video-tracks/${encodeURIComponent(trackId)}/interpolation`,
    { signal },
  );
}

export function getVideoTrackAnalytics(
  trackId: string,
  signal?: AbortSignal,
): Promise<VideoTrackAnalytics> {
  return request<VideoTrackAnalytics>(
    `/video-tracks/${encodeURIComponent(trackId)}/analytics`,
    { signal },
  );
}

export function evaluateVideoTracking(
  videoId: string,
  payload: {
    ground_truth_track_ids: string[];
    prediction_track_ids: string[];
    iou_threshold?: number;
    class_aware?: boolean;
    start_frame?: number;
    end_frame?: number;
  },
): Promise<VideoTrackingEvaluation> {
  return request<VideoTrackingEvaluation>(
    `/videos/${encodeURIComponent(videoId)}/tracking-evaluation`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function benchmarkVideoTracking(
  videoId: string,
  payload: {
    ground_truth_track_ids: string[];
    candidates: VideoTrackingBenchmarkCandidate[];
    iou_threshold?: number;
    class_aware?: boolean;
    start_frame?: number;
    end_frame?: number;
  },
): Promise<VideoTrackingBenchmark> {
  return request<VideoTrackingBenchmark>(
    `/videos/${encodeURIComponent(videoId)}/tracking-benchmark`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export async function getTrackingModels(
  projectId: string,
  signal?: AbortSignal,
): Promise<TrackingModelRecord[]> {
  const [detectors, segmenters] = await Promise.all([
    request<TrackingModelRecord[]>(
      `/projects/${encodeURIComponent(projectId)}/models?purpose=detector`,
      { signal },
    ),
    request<TrackingModelRecord[]>(
      `/projects/${encodeURIComponent(projectId)}/models?purpose=segmenter`,
      { signal },
    ),
  ]);
  return [...detectors, ...segmenters];
}

export function createVideoTrackingJob(
  videoId: string,
  payload: {
    model_id: string;
    tracking_mode?: "auto" | "detect" | "segment" | "hybrid";
    segmentation_model_id?: string | null;
    hybrid_match_iou?: number;
    tracker: string;
    confidence: number;
    iou: number;
    device: string;
    minimum_track_frames: number;
    link_detections: boolean;
  },
): Promise<JobRecord> {
  return request<JobRecord>(
    `/videos/${encodeURIComponent(videoId)}/tracking-jobs`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function setPoseLandmarkSchema(
  modelId: string,
  groups: PoseLandmarkGroup[],
): Promise<TrackingModelRecord> {
  return request<TrackingModelRecord>(
    `/models/${encodeURIComponent(modelId)}/pose-landmark-schema`,
    {
      method: "PUT",
      body: JSON.stringify({ groups }),
    },
  );
}

export function deleteTrackingModel(modelId: string): Promise<void> {
  return request<void>(`/models/${encodeURIComponent(modelId)}`, {
    method: "DELETE",
  });
}

export type AnnotatedVideoPreset = "clean_tracking" | "full_review";

export interface AnnotatedVideoOverlayOptions {
  boxes: boolean;
  track_ids: boolean;
  class_labels: boolean;
  confidence: boolean;
  trails: boolean;
  frame_time: boolean;
  counters: boolean;
}

export interface AnnotatedVideoExportPayload {
  source_tracking_job_id: string;
  preset: AnnotatedVideoPreset;
  overlays: AnnotatedVideoOverlayOptions;
  trail_length: number;
}

export function getAnnotatedVideoExports(
  videoId: string,
  signal?: AbortSignal,
): Promise<JobRecord[]> {
  const poll = Date.now();
  return request<JobRecord[]>(
    `/videos/${encodeURIComponent(videoId)}/annotated-video-exports?poll=${poll}`,
    { signal, cache: "no-store" },
  );
}

export function createAnnotatedVideoExport(
  videoId: string,
  payload: AnnotatedVideoExportPayload,
): Promise<JobRecord> {
  return request<JobRecord>(
    `/videos/${encodeURIComponent(videoId)}/annotated-video-exports`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function annotatedVideoExportContentUrl(jobId: string): string {
  return `${getApiBaseUrl()}/video-annotated-exports/${encodeURIComponent(jobId)}/content`;
}
