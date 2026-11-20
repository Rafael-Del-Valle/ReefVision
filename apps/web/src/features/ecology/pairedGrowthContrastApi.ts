import { request } from "../../api/client";

export interface PairedGrowthDesign {
  baseline_date: string;
  followup_date: string;
  experimental_unit_type: string;
  estimand: string;
  missingness_policy: "complete_unit";
}

export interface PairedGrowthRequest extends PairedGrowthDesign {
  source_sha256: string;
}

interface PairedUnit {
  experimental_unit_id: string;
  status: "included" | "excluded";
  reason: string | null;
  difference: number | null;
  organisms: {
    organism_id: string;
    baseline_source_record_id: string | null;
    followup_source_record_id: string | null;
    difference: number | null;
    reason: string | null;
  }[];
}

export interface PairedGrowthReport {
  analysis_id: string;
  source_sha256: string;
  design: PairedGrowthDesign;
  method_version: string;
  metric: string;
  unit: string | null;
  units: PairedUnit[];
  planned_unit_count: number;
  included_unit_count: number;
  mean_difference: number | null;
  standard_error: number | null;
  degrees_of_freedom: number | null;
  interval_status:
    | "available"
    | "insufficient_complete_units"
    | "zero_between_unit_variation"
    | "statistics_runtime_unavailable"
    | "precision_unavailable";
  confidence_interval_95: [number, number] | null;
  source_exclusions: { source: string; reason: string }[];
  assumptions: string[];
  method_reference: string;
  report_sha256: string;
}

export function calculatePairedContrast(
  projectId: string,
  analysisId: string,
  declaration: PairedGrowthRequest,
  signal?: AbortSignal,
) {
  const base = `/projects/${encodeURIComponent(projectId)}/ecology/verified-analyses`;
  return request<PairedGrowthReport>(
    `${base}/${encodeURIComponent(analysisId)}/paired-contrast`,
    { method: "POST", body: JSON.stringify(declaration), signal },
  );
}

export function downloadPairedReport(report: object, digest: string) {
  const objectUrl = URL.createObjectURL(
    new Blob([JSON.stringify(report, null, 2) + "\n"], {
      type: "application/json",
    }),
  );
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = `paired-growth-${digest}.json`;
  anchor.click();
  URL.revokeObjectURL(objectUrl);
}
