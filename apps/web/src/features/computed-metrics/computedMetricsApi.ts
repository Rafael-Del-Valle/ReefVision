import { getApiBaseUrl } from "../../runtime";

export type MetricDimension =
  | "dimensionless"
  | "length"
  | "area"
  | "time"
  | "speed"
  | "temperature"
  | "practical_salinity"
  | "mass_salinity"
  | "count"
  | "count_density"
  | "count_rate"
  | "angle"
  | "pixel_length"
  | "pixel_area";

export interface ComputedMetricInputSpec {
  symbol: string;
  dimension: MetricDimension;
}

export interface ComputedMetricDefinitionCreate {
  name: string;
  expression: string;
  inputs: ComputedMetricInputSpec[];
  output_unit: string;
}

export interface ComputedMetricDefinition extends ComputedMetricDefinitionCreate {
  id: string;
  project_id: string;
  formula_version: string;
  definition_sha256: string;
  created_at: string;
}

export interface ComputedMetricDefinitionPage {
  items: ComputedMetricDefinition[];
  total: number;
}

export interface ComputedMetricResult {
  schema_version: "1.1.0";
  id: string;
  project_id: string;
  definition_id: string;
  definition_name: string;
  expression: string;
  formula_version: string;
  definition_sha256: string;
  value: number;
  unit: string;
  normalized_value: number;
  normalized_unit: string;
  uncertainty: number | null;
  normalized_uncertainty: number | null;
  dimension: Record<string, number>;
  observed_at: string;
  subject: Record<string, unknown>;
  input_record_ids: Record<string, string>;
  input_snapshot: Record<string, Record<string, unknown>>;
  provenance: Record<string, unknown>;
  content_sha256: string;
  workflow_run_id: string | null;
  workflow_node_run_id: string | null;
  created_at: string;
}

export interface ComputedMetricResultPage {
  items: ComputedMetricResult[];
  total: number;
}

function detailMessage(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return null;
  const messages = detail
    .map((issue: unknown) => {
      if (!issue || typeof issue !== "object") return null;
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
    let message = `Computed Metrics request failed with HTTP ${response.status}.`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      message = detailMessage(payload.detail) ?? message;
    } catch {
      // Keep the status-based message when the response is not JSON.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export function getComputedMetricDefinitions(
  projectId: string,
  signal?: AbortSignal,
  offset = 0,
): Promise<ComputedMetricDefinitionPage> {
  return request(
    `/projects/${encodeURIComponent(projectId)}/computed-metric-definitions?limit=500&offset=${offset}`,
    { signal },
  );
}

export function createComputedMetricDefinition(
  projectId: string,
  payload: ComputedMetricDefinitionCreate,
): Promise<ComputedMetricDefinition> {
  return request(
    `/projects/${encodeURIComponent(projectId)}/computed-metric-definitions`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function calculateComputedMetric(
  projectId: string,
  definitionId: string,
  inputs: Record<string, string>,
): Promise<ComputedMetricResult> {
  return request(
    `/projects/${encodeURIComponent(projectId)}/computed-metric-definitions/${encodeURIComponent(definitionId)}/calculate`,
    { method: "POST", body: JSON.stringify({ inputs }) },
  );
}

export function getComputedMetricResults(
  projectId: string,
  signal?: AbortSignal,
  offset = 0,
): Promise<ComputedMetricResultPage> {
  return request(
    `/projects/${encodeURIComponent(projectId)}/computed-metric-results?limit=500&offset=${offset}`,
    { signal },
  );
}

export function computedMetricCsvUrl(projectId: string): string {
  return `${getApiBaseUrl()}/projects/${encodeURIComponent(projectId)}/computed-metric-results.csv`;
}
