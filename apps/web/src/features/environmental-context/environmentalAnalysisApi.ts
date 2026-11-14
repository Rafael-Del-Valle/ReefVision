import { getApiBaseUrl } from "../../runtime";
import type { NOAAImportResult } from "./environmentalContextApi";

export type EnvironmentalAnalysisKind =
  | "lunar_context"
  | "tidal_context"
  | "event_window"
  | "observation_environment_join"
  | "lagged_comparison";

export interface EnvironmentalAnalysisDefinition {
  id: string;
  project_id: string;
  analysis_kind: EnvironmentalAnalysisKind;
  name: string;
  configuration: Record<string, unknown>;
  calculation_version: string;
  definition_sha256: string;
  created_at: string;
}

export interface EnvironmentalAnalysisResult {
  id: string;
  project_id: string;
  definition_id: string;
  analysis_kind: EnvironmentalAnalysisKind;
  observed_at: string;
  payload: Record<string, unknown>;
  input_snapshot: Record<string, unknown>;
  source_record_ids: string[];
  source_analysis_result_ids: string[];
  quality_control: Record<string, unknown>;
  uncertainty: Record<string, unknown> | null;
  content_sha256: string;
  workflow_run_id: string | null;
  workflow_node_run_id: string | null;
  created_at: string;
}

export interface EnvironmentalAnalysisSingle {
  definition: EnvironmentalAnalysisDefinition;
  result: EnvironmentalAnalysisResult;
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
    throw new Error("Could not reach the local environmental-analysis API.");
  }
  if (!response.ok) {
    let message = `Environmental analysis failed with HTTP ${response.status}.`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
      if (Array.isArray(body.detail)) {
        message = body.detail
          .map((item) =>
            item && typeof item === "object" && "msg" in item
              ? String(item.msg)
              : String(item),
          )
          .join("; ");
      }
    } catch {
      // Keep the stable HTTP error when the response is not JSON.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

function analysisPath(projectId: string, suffix: string): string {
  return `/projects/${encodeURIComponent(projectId)}/environment/analyses/${suffix}`;
}

export function importNOAATides(
  projectId: string,
  payload: {
    station_id: string;
    day: string;
    product: "predictions" | "water_level";
    datum: string;
    offline: boolean;
  },
): Promise<NOAAImportResult> {
  return request(
    `/projects/${encodeURIComponent(projectId)}/environment/noaa/tides`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export async function createLunarAnalysis(
  projectId: string,
  payload: { name: string; observed_at: string[] },
): Promise<EnvironmentalAnalysisSingle> {
  const response = await request<{
    definition: EnvironmentalAnalysisDefinition;
    results: EnvironmentalAnalysisResult[];
  }>(analysisPath(projectId, "lunar-context"), {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return { definition: response.definition, result: response.results[0] };
}

export function createTidalAnalysis(
  projectId: string,
  payload: Record<string, unknown>,
): Promise<EnvironmentalAnalysisSingle> {
  return request(analysisPath(projectId, "tidal-context"), {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createEventWindowAnalysis(
  projectId: string,
  payload: Record<string, unknown>,
): Promise<EnvironmentalAnalysisSingle> {
  return request(analysisPath(projectId, "event-window"), {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createObservationEnvironmentJoin(
  projectId: string,
  payload: Record<string, unknown>,
): Promise<EnvironmentalAnalysisSingle> {
  return request(analysisPath(projectId, "observation-environment-join"), {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createLaggedComparison(
  projectId: string,
  payload: Record<string, unknown>,
): Promise<EnvironmentalAnalysisSingle> {
  return request(analysisPath(projectId, "lagged-comparison"), {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listEnvironmentalAnalysisResults(
  projectId: string,
): Promise<{ items: EnvironmentalAnalysisResult[]; total: number }> {
  return request(`${analysisPath(projectId, "results")}?limit=100&offset=0`);
}

export function validateEnvironmentalAnalysis(
  projectId: string,
  resultId: string,
): Promise<{
  result_id: string;
  current: boolean;
  result_sha256: string;
  reasons: string[];
}> {
  return request(
    analysisPath(
      projectId,
      `results/${encodeURIComponent(resultId)}/validation`,
    ),
  );
}

export function environmentalAnalysisCsvUrl(
  projectId: string,
  resultId: string,
): string {
  return `${getApiBaseUrl()}${analysisPath(projectId, `results/${encodeURIComponent(resultId)}.csv`)}`;
}
