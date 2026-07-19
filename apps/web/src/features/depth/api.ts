import { getApiBaseUrl } from "../../runtime";

export interface DepthMapRecord {
  id: string;
  project_id: string;
  image_id: string;
  provider_id: string;
  model_id: string;
  model_checksum: string | null;
  depth_kind: "relative" | "metric";
  unit: string | null;
  minimum_depth: number;
  maximum_depth: number;
  median_depth: number;
  valid_pixel_count: number;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface DepthJobResult {
  depth_map_id: string;
  job: {
    id: string;
    status: string;
    progress_current: number;
    progress_total: number;
  };
}

export interface DepthMaskMeasurement {
  mask_annotation_id: string;
  image_id: string;
  depth_map_id: string;
  depth_kind: "relative" | "metric";
  unit: string | null;
  depth: {
    valid_pixel_count: number;
    minimum: number | null;
    percentile_05: number | null;
    median: number | null;
    mean: number | null;
    percentile_95: number | null;
    maximum: number | null;
  };
  pixel_area: number;
  depth_weighted_area_index: number | null;
  metric_area: number | null;
  metric_width: number | null;
  metric_height: number | null;
  centroid_x: number | null;
  centroid_y: number | null;
  centroid_z: number | null;
  method: string;
  warnings: string[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, init);
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      // Keep fallback.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function listDepthMaps(imageId: string, signal?: AbortSignal) {
  return request<DepthMapRecord[]>(`/images/${imageId}/depth-maps`, { signal });
}

export function queueDepthMap(
  imageId: string,
  payload: Record<string, unknown>,
) {
  return request<DepthJobResult>(`/images/${imageId}/depth-jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function measureMaskDepth(
  maskId: string,
  depthMapId: string,
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({ depth_map_id: depthMapId });
  return request<DepthMaskMeasurement>(
    `/mask-annotations/${maskId}/depth-measurement?${params}`,
    { signal },
  );
}

export function depthPreviewUrl(depthMapId: string) {
  return `${getApiBaseUrl()}/depth-maps/${depthMapId}/preview`;
}

export function depthContentUrl(depthMapId: string) {
  return `${getApiBaseUrl()}/depth-maps/${depthMapId}/content`;
}
