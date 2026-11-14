import { request } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";

import type { Metric } from "./ecologyApi";

export interface GrowthSource {
  calibration_evidence_id: string;
  exclusion_reason?: string;
}

export interface SurveySource {
  image_id?: string;
  sample_id: string;
  experimental_unit_type: string;
  experimental_unit_id: string;
  observed_at: string;
  surveyed_area_m2?: number;
  exclusion_reason?: string;
}

export type AnalysisSelection =
  | { kind: "growth"; metric: Metric; sources: GrowthSource[] }
  | { kind: "abundance"; class_id: string; sources: SurveySource[] };

export interface AnalysisCreate {
  selection: AnalysisSelection;
  reviewed_by: string;
  review_note: string;
  confirm_reviewed_selection: true;
  supersedes_id?: string;
}

interface Exclusion {
  source: string;
  reason: string;
}

export type AnalysisResult =
  | {
      kind: "growth";
      observations: {
        organism_key: string;
        observed_at: string;
        value: number;
        unit: string;
      }[];
      changes: {
        organism_id: string;
        unit: string;
        initial_value: number;
        final_value: number;
        absolute_change: number;
        change_per_day: number;
      }[];
      population_summaries: {
        baseline_date: string;
        final_date: string;
        unit: string;
        independent_unit_count: number;
        mean_unit_absolute_change: number;
      }[];
      exclusions: Exclusion[];
    }
  | {
      kind: "abundance";
      class_name: string;
      visits: {
        sample_id: string;
        observed_at: string;
        experimental_unit_id: string;
        count: number;
        surveyed_area_m2: number | null;
        density_per_m2: number | null;
      }[];
      unit_summaries: {
        observed_on: string;
        experimental_unit_id: string;
        sample_count: number;
        excluded_sample_count: number;
        total_count: number;
        density_per_m2: number | null;
      }[];
      exclusions: Exclusion[];
    };

export interface EcologyAnalysis {
  id: string;
  supersedes_id: string | null;
  created_at: string;
  content_sha256: string;
  stale: boolean;
  stale_reason: string | null;
  source_id_map: Record<string, string>;
  snapshot: {
    selection: AnalysisSelection;
    reviewed_by: string;
    review_note: string;
    method_version: string;
    result: AnalysisResult;
    limitations: string[];
  };
}

function base(projectId: string) {
  return `/projects/${encodeURIComponent(projectId)}/ecology/verified-analyses`;
}

export function listEcologyAnalyses(
  projectId: string,
  page: number,
  signal?: AbortSignal,
) {
  return request<{ items: EcologyAnalysis[]; total: number }>(
    `${base(projectId)}?page=${page}&page_size=20`,
    { signal },
  );
}

export function saveEcologyAnalysis(
  projectId: string,
  payload: AnalysisCreate,
) {
  return request<EcologyAnalysis>(base(projectId), {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function ecologyAnalysisDownload(
  projectId: string,
  id: string,
  format: "csv" | "json",
) {
  const file = format === "csv" ? "results.csv" : "result.json";
  return `${getApiBaseUrl()}${base(projectId)}/${encodeURIComponent(id)}/${file}`;
}
