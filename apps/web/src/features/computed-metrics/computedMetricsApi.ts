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

export type AggregateSourceKind = "verified_annotations" | "verified_masks";
export type AggregateGroupingLevel = "image" | "image_group_key";

export interface ComputedAggregateDefinitionCreate {
  name: string;
  source_kind: AggregateSourceKind;
  grouping_level: AggregateGroupingLevel;
  label_class_ids: string[];
}

export interface ComputedAggregateDefinition extends ComputedAggregateDefinitionCreate {
  id: string;
  project_id: string;
  definition_kind: "annotation_aggregate";
  expression: string;
  operation: "count";
  output_unit: "count";
  formula_version: "reefvision.annotation-aggregate.v1";
  schema_version: "1.1.0";
  required_review_state: "reviewed";
  independence_contract: "one_unit_per_image" | "one_unit_per_image_group_key";
  definition_sha256: string;
  created_at: string;
}

export interface AggregateClassCount {
  label_class_id: string | null;
  label_name: string;
  count: number;
}

export interface AggregateGroup {
  unit_key: string;
  image_ids: string[];
  observation_count: number;
  counts_by_class: AggregateClassCount[];
}

export interface ComputedAggregatePreview {
  schema_version: "1.1.0";
  definition_id: string;
  definition_sha256: string;
  source_kind: AggregateSourceKind;
  grouping_level: AggregateGroupingLevel;
  operation: "count";
  required_review_state: "reviewed";
  image_count: number;
  independent_unit_count: number;
  observation_count: number;
  mean_per_independent_unit: number;
  counts_by_class: AggregateClassCount[];
  groups: AggregateGroup[];
  excluded_proposals_by_status: Record<string, number>;
  image_snapshot: Array<Record<string, unknown>>;
  observation_snapshot: Array<Record<string, unknown>>;
  evidence_sha256: string;
}

export interface ComputedAggregateResult extends ComputedAggregatePreview {
  id: string;
  project_id: string;
  result_kind: "annotation_aggregate";
  definition_name: string;
  expression: string;
  formula_version: "reefvision.annotation-aggregate.v1";
  output_unit: "count";
  observed_at: string;
  provenance: Record<string, unknown>;
  content_sha256: string;
  workflow_run_id: string | null;
  workflow_node_run_id: string | null;
  created_at: string;
}

export interface ComputedAggregateValidation {
  result_id: string;
  current: boolean;
  saved_evidence_sha256: string;
  current_evidence_sha256: string;
  reasons: string[];
}

export interface ComputedAggregateDefinitionPage {
  items: ComputedAggregateDefinition[];
  total: number;
}

export interface ComputedAggregateResultPage {
  items: ComputedAggregateResult[];
  total: number;
}

export function getComputedAggregateDefinitions(
  projectId: string,
  signal?: AbortSignal,
  offset = 0,
): Promise<ComputedAggregateDefinitionPage> {
  return request(
    `/projects/${encodeURIComponent(projectId)}/computed-aggregate-definitions?limit=500&offset=${offset}`,
    { signal },
  );
}

export function createComputedAggregateDefinition(
  projectId: string,
  payload: ComputedAggregateDefinitionCreate,
): Promise<ComputedAggregateDefinition> {
  return request(
    `/projects/${encodeURIComponent(projectId)}/computed-aggregate-definitions`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function previewComputedAggregate(
  projectId: string,
  definitionId: string,
  imageIds: string[],
): Promise<ComputedAggregatePreview> {
  return request(
    `/projects/${encodeURIComponent(projectId)}/computed-aggregate-definitions/${encodeURIComponent(definitionId)}/preview`,
    { method: "POST", body: JSON.stringify({ image_ids: imageIds }) },
  );
}

export function calculateComputedAggregate(
  projectId: string,
  definitionId: string,
  imageIds: string[],
): Promise<ComputedAggregateResult> {
  return request(
    `/projects/${encodeURIComponent(projectId)}/computed-aggregate-definitions/${encodeURIComponent(definitionId)}/calculate`,
    { method: "POST", body: JSON.stringify({ image_ids: imageIds }) },
  );
}

export function getComputedAggregateResults(
  projectId: string,
  signal?: AbortSignal,
  offset = 0,
): Promise<ComputedAggregateResultPage> {
  return request(
    `/projects/${encodeURIComponent(projectId)}/computed-aggregate-results?limit=500&offset=${offset}`,
    { signal },
  );
}

export function validateComputedAggregateResult(
  projectId: string,
  resultId: string,
  signal?: AbortSignal,
): Promise<ComputedAggregateValidation> {
  return request(
    `/projects/${encodeURIComponent(projectId)}/computed-aggregate-results/${encodeURIComponent(resultId)}/validation`,
    { signal },
  );
}

export function computedAggregateCsvUrl(projectId: string): string {
  return `${getApiBaseUrl()}/projects/${encodeURIComponent(projectId)}/computed-aggregate-results.csv`;
}
