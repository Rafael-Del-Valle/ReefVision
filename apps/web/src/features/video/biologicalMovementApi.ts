import { getApiBaseUrl } from "../../runtime";

export interface AnalysisJob {
  id: string;
  status: string;
  progress_current: number;
  progress_total: number;
  result_json: { run_id?: string; stage?: string } | null;
  error_message: string | null;
}

export interface MeasurementRun {
  id: string;
  project_id: string;
  video_id: string;
  source_identity_run_id: string;
  source_identity_run_revision: number;
  source_job_id: string | null;
  definitions_json: MeasurementDefinition[];
  configuration_json: Record<string, unknown>;
  status: string;
  progress_json: Record<string, unknown>;
  verification_state: string;
  result_sha256: string | null;
}

export interface MeasurementDefinition {
  id: string;
  name: string;
  kind: "distance" | "angle";
  landmark_ids: string[];
}

export interface MeasurementSeries {
  id: string;
  measurement_run_id: string;
  animal_identity_id: string;
  definition_id: string;
  measurement_kind: string;
  display_name: string;
  pixel_unit: string;
  physical_unit: string | null;
  summary_json: Record<string, number | null>;
}

export interface MeasurementSample {
  frame_index: number;
  time_s: number;
  pixel_value: number | null;
  physical_value: number | null;
  confidence: number | null;
  valid: boolean;
  quality_flags_json: string[];
}

export interface EventRun {
  id: string;
  measurement_run_id: string;
  source_job_id: string | null;
  configuration_json: Record<string, unknown>;
  status: string;
  progress_json: Record<string, unknown>;
  result_sha256: string | null;
}

export interface BiologicalEvent {
  id: string;
  event_series_id: string;
  revision: number;
  measurement_series_id: string;
  animal_identity_id: string;
  start_frame: number;
  peak_frame: number | null;
  end_frame: number | null;
  amplitude: number | null;
  duration_s: number | null;
  confidence: number | null;
  cycle_state: string;
  review_state: string;
  detection_source: string;
  is_current: boolean;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, init);
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) message = payload.detail;
    } catch {
      // Preserve the status fallback for non-JSON errors.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export const listMeasurementRuns = (projectId: string, signal?: AbortSignal) =>
  requestJson<MeasurementRun[]>(
    `/projects/${projectId}/pose-measurement-runs`,
    { signal },
  );

export const createMeasurementRun = (
  projectId: string,
  payload: {
    video_id: string;
    source_identity_run_id: string;
    source_identity_run_revision: number;
    identity_ids: string[];
    definitions: MeasurementDefinition[];
    maximum_gap_s: number;
    verification_mode: "exploratory" | "scientific";
  },
) =>
  requestJson<AnalysisJob>(`/projects/${projectId}/pose-measurement-runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

export const listMeasurementSeries = (runId: string, signal?: AbortSignal) =>
  requestJson<MeasurementSeries[]>(`/pose-measurement-runs/${runId}/series`, {
    signal,
  });

export const listMeasurementSamples = (
  seriesId: string,
  signal?: AbortSignal,
) =>
  requestJson<MeasurementSample[]>(
    `/pose-measurement-series/${seriesId}/samples`,
    { signal },
  );

export const listEventRuns = (projectId: string, signal?: AbortSignal) =>
  requestJson<EventRun[]>(`/projects/${projectId}/pose-event-runs`, { signal });

export const createEventRun = (
  projectId: string,
  payload: {
    measurement_run_id: string;
    cycles: Array<Record<string, string | number>>;
  },
) =>
  requestJson<AnalysisJob>(`/projects/${projectId}/pose-event-runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

export const listBiologicalEvents = (
  runId: string,
  includeHistory = false,
  signal?: AbortSignal,
) =>
  requestJson<BiologicalEvent[]>(
    `/pose-event-runs/${runId}/events?include_history=${includeHistory}`,
    { signal },
  );

export const correctBiologicalEvent = (
  eventId: string,
  payload: {
    action: "confirm" | "reject" | "adjust_boundaries" | "remove";
    start_frame?: number;
    end_frame?: number;
    reason: string;
    actor: string;
  },
) =>
  requestJson<BiologicalEvent>(
    `/pose-biological-events/${eventId}/corrections`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );

export const biologicalMovementExportUrl = (
  runId: string,
  format: "json" | "csv",
) => `${getApiBaseUrl()}/pose-event-runs/${runId}/export?format=${format}`;
