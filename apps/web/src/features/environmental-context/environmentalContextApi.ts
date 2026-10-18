import { getApiBaseUrl } from "../../runtime";

export type ScientificSourceKind =
  "observed" | "remotely_sensed" | "modeled" | "derived";
export type ScientificQc = "unassessed" | "accepted" | "suspect" | "rejected";

export interface ScientificSubject {
  image_id?: string | null;
  video_id?: string | null;
  frame_index?: number | null;
  track_id?: string | null;
  annotation_id?: string | null;
  mask_id?: string | null;
  prediction_id?: string | null;
  model_run_id?: string | null;
}

export interface ScientificRecordCreate {
  schema_version?: "1.1.0";
  variable: string;
  value: number;
  unit: string;
  observed_at: string;
  source_kind: ScientificSourceKind;
  subject?: ScientificSubject;
  location?: {
    crs?: "EPSG:4326";
    latitude: number;
    longitude: number;
    horizontal_uncertainty_m?: number | null;
  } | null;
  pixel?: {
    frame: "image_pixels" | "video_pixels";
    x: number;
    y: number;
  } | null;
  depth_m?: number | null;
  depth_reference?: string | null;
  uncertainty?: {
    value: number;
    kind: "standard_deviation" | "standard_error" | "bound";
    method?: string | null;
  } | null;
  qc?: ScientificQc;
  qc_flags?: string[];
  provenance: {
    source: string;
    source_url?: string | null;
    dataset_id?: string | null;
    acquired_at: string;
    method?: string | null;
    model_version?: string | null;
    processing_parameters?: Record<string, unknown>;
    source_metadata?: Record<string, unknown>;
    spatial_resolution_m?: number | null;
    temporal_resolution_s?: number | null;
  };
}

export interface ScientificRecord extends ScientificRecordCreate {
  id: string;
  project_id: string;
  normalized_value: number;
  normalized_unit: string;
  normalized_uncertainty: number | null;
  calibration_snapshot?: Record<string, unknown> | null;
  calibration_sha256?: string | null;
  calibration_current?: boolean | null;
  environmental_cache_key?: string | null;
  environmental_snapshot_current?: boolean | null;
  content_sha256: string;
}

export interface ScientificRecordPage {
  items: ScientificRecord[];
  total: number;
}

export interface ScientificRecordFilters {
  limit: number;
  offset: number;
  variable?: string;
  sourceKind?: ScientificSourceKind | "";
}

export interface NOAAImportRequest {
  station_id: string;
  day: string;
  offline: boolean;
  subject?: ScientificSubject;
}

export interface NOAAImportResult {
  items: ScientificRecord[];
  cache_status: "downloaded" | "fresh" | "stale_offline";
  fetched_at: string;
  expires_at: string;
  source_url: string;
  skipped_missing: number;
}

function detailMessage(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((issue: unknown) => {
        if (!issue || typeof issue !== "object") return detailMessage(issue);
        const value = issue as { loc?: unknown; msg?: unknown };
        if (typeof value.msg !== "string") return null;
        const field = Array.isArray(value.loc)
          ? value.loc
              .filter((part) => part !== "body" && part !== "query")
              .join(".")
          : "";
        return field ? `${field}: ${value.msg}` : value.msg;
      })
      .filter(Boolean);
    return messages.length ? messages.join("; ") : null;
  }
  if (detail && typeof detail === "object") {
    const value = detail as { reason?: unknown; message?: unknown };
    if (typeof value.reason === "string") return value.reason;
    if (typeof value.message === "string") return value.message;
  }
  return null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${getApiBaseUrl()}${path}`, {
      ...init,
      headers: {
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch (error) {
    if (init?.signal?.aborted) throw error;
    throw new Error(
      "Could not reach the local ReefVision API. Retry the request.",
    );
  }
  if (!response.ok) {
    let message = `Environmental Context request failed with HTTP ${response.status}.`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      message = detailMessage(payload.detail) ?? message;
    } catch {
      // Preserve the HTTP status when a response body is not JSON.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export function getScientificRecords(
  projectId: string,
  filters: ScientificRecordFilters,
  signal?: AbortSignal,
): Promise<ScientificRecordPage> {
  const query = new URLSearchParams({
    limit: String(filters.limit),
    offset: String(filters.offset),
  });
  if (filters.variable) query.set("variable", filters.variable);
  if (filters.sourceKind) query.set("source_kind", filters.sourceKind);
  return request(
    `/projects/${encodeURIComponent(projectId)}/scientific-records?${query}`,
    { signal },
  );
}

export function importScientificRecords(
  projectId: string,
  batch: { records: ScientificRecordCreate[] },
): Promise<ScientificRecordPage> {
  return request(
    `/projects/${encodeURIComponent(projectId)}/scientific-records`,
    {
      method: "POST",
      body: JSON.stringify(batch),
    },
  );
}

export function importNOAARecords(
  projectId: string,
  payload: NOAAImportRequest,
): Promise<NOAAImportResult> {
  return request(
    `/projects/${encodeURIComponent(projectId)}/environment/noaa`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export interface EnvironmentalMatch {
  record: ScientificRecord;
  distance_m: number;
  time_delta_s: number;
  depth_delta_m: number | null;
  cache_fetched_at: string | null;
  cache_expires_at: string | null;
  cache_age_s: number | null;
  offline_available: boolean;
}
export interface EnvironmentalSubjectContext {
  status: "available" | "unavailable" | "ambiguous";
  reason: string | null;
  positions: ScientificRecord[];
  position: ScientificRecord | null;
  matches: Record<string, EnvironmentalMatch[]>;
}
export function getSubjectEnvironment(
  projectId: string,
  payload: {
    subject: ScientificSubject;
    position_record_id?: string;
    max_distance_m: number;
    max_time_delta_s: number;
    max_depth_delta_m: number;
  },
  signal?: AbortSignal,
): Promise<EnvironmentalSubjectContext> {
  return request(
    `/projects/${encodeURIComponent(projectId)}/environment/subject-context`,
    {
      method: "POST",
      body: JSON.stringify(payload),
      signal,
    },
  );
}

export interface CopernicusRequest {
  dataset_id: string;
  dataset_version: string;
  variables: ("uo" | "vo" | "thetao" | "so")[];
  minimum_longitude: number;
  maximum_longitude: number;
  minimum_latitude: number;
  maximum_latitude: number;
  minimum_depth: number;
  maximum_depth: number;
  start_datetime: string;
  end_datetime: string;
  offline: boolean;
  refresh: boolean;
}
export interface EnvironmentalDatasetSummary {
  cache_key: string;
  provider: string;
  source_url: string;
  record_count: number;
  fetched_at: string;
  expires_at: string;
}
export function getEnvironmentalDatasets(
  projectId: string,
  offset: number,
  signal?: AbortSignal,
): Promise<{ items: EnvironmentalDatasetSummary[]; total: number }> {
  return request(
    `/projects/${encodeURIComponent(projectId)}/environment/datasets?limit=100&offset=${offset}`,
    { signal },
  );
}
export function getCachedDataset(
  projectId: string,
  cacheKey: string,
  signal?: AbortSignal,
): Promise<NOAAImportResult> {
  return request(
    `/projects/${encodeURIComponent(projectId)}/environment/datasets/${encodeURIComponent(cacheKey)}`,
    { signal },
  );
}
export function importCopernicus(
  projectId: string,
  payload: CopernicusRequest,
): Promise<NOAAImportResult> {
  return request(
    `/projects/${encodeURIComponent(projectId)}/environment/copernicus`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}
