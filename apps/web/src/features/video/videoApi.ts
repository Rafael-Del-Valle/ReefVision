import { getApiBaseUrl } from "../../runtime";
import type { JobRecord, ModelRegistration } from "../../api/client";

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
}

export interface VideoTrackKeyframe {
  frame: number;
  bbox: [number, number, number, number];
  confidence?: number | null;
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

export function importVideo(
  projectId: string,
  file: File,
): Promise<VideoAssetRecord> {
  const form = new FormData();
  form.append("file", file);
  return request<VideoAssetRecord>(
    `/projects/${encodeURIComponent(projectId)}/imports/videos`,
    { method: "POST", body: form },
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
  return request<VideoTrackRecord>(`/video-tracks/${encodeURIComponent(trackId)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function deleteVideoTrack(trackId: string): Promise<void> {
  return request<void>(`/video-tracks/${encodeURIComponent(trackId)}`, {
    method: "DELETE",
  });
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

export async function getTrackingModels(
  projectId: string,
  signal?: AbortSignal,
): Promise<ModelRegistration[]> {
  const [detectors, segmenters] = await Promise.all([
    request<ModelRegistration[]>(
      `/projects/${encodeURIComponent(projectId)}/models?purpose=detector`,
      { signal },
    ),
    request<ModelRegistration[]>(
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
    tracker: string;
    confidence: number;
    iou: number;
    device: string;
    minimum_track_frames: number;
  },
): Promise<JobRecord> {
  return request<JobRecord>(
    `/videos/${encodeURIComponent(videoId)}/tracking-jobs`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}
