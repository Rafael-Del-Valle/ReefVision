import { getApiBaseUrl } from "../../runtime";

export interface TrainingRunForReport {
  id: string;
  project_id: string;
  run_name: string;
  task: string;
  provider_id: string;
  architecture: string;
  status: string;
  stage: string;
  metrics_json: Record<string, number>;
  metrics_history_json: Record<string, number[]>;
  training_config_json: Record<string, unknown>;
  tuning_config_json: Record<string, unknown>;
  evaluation_config_json: Record<string, unknown>;
  artifact_manifest_json: Record<string, unknown>;
  created_at: string;
  completed_at: string | null;
}

export interface TrainingReportPayload {
  title?: string;
  subtitle?: string;
  font_family: string;
  base_font_size_pt: number;
  heading_font_size_pt: number;
  table_font_size_pt: number;
  figure_label_font_size_pt: number;
  include_training_history: boolean;
  include_per_class_metrics: boolean;
  include_confusion_matrix: boolean;
  include_ultralytics_plots: boolean;
  include_tuning_analysis: boolean;
  include_provenance: boolean;
}

export interface TrainingReportResult {
  report_id: string;
  training_run_id: string;
  title: string;
  created_at: string;
  font_family: string;
  html_path: string;
  json_path: string;
  download_url: string;
  included_sections: string[];
  warnings: string[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, init);
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) message = payload.detail;
    } catch {
      // Keep the HTTP fallback for non-JSON errors.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function listReportTrainingRuns(
  projectId: string,
  signal?: AbortSignal,
) {
  return request<TrainingRunForReport[]>(
    `/projects/${projectId}/training-runs`,
    {
      signal,
    },
  );
}

export function createTrainingReport(
  runId: string,
  payload: TrainingReportPayload,
) {
  return request<TrainingReportResult>(`/training-runs/${runId}/reports`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function trainingReportDownloadUrl(result: TrainingReportResult) {
  return `${getApiBaseUrl()}${result.download_url}`;
}
