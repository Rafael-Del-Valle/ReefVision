import { request } from "../../api/client";

export type MonitoringKind = "environmental" | "biological";
export type MonitoringSourceKind =
  "observed" | "remotely_sensed" | "modeled" | "derived";
export type SourceStatus = "current" | "stale";
export type ReviewDecision = "confirmed" | "dismissed";

interface Thresholds {
  lower_limit?: number;
  upper_limit?: number;
}

export type MonitoringRuleCreate = {
  label: string;
  protocol: string;
  metric: string;
  unit: string;
} & (
  | {
      kind: "environmental";
      parameters: Thresholds & {
        cadence_seconds: number;
        max_drift?: number;
        max_delay_seconds?: number;
        source_kind?: MonitoringSourceKind;
        source?: string;
      };
    }
  | {
      kind: "biological";
      parameters: Thresholds & {
        summary_ids: string[];
        minimum_effort_seconds: number;
      };
    }
);

export type MonitoringRule = MonitoringRuleCreate & {
  id: string;
  project_id: string;
  rule_sha256: string;
  created_at: string;
};

export interface MonitoringAssessmentCreate {
  rule_id: string;
  rule_sha256: string;
  window_start: string;
  window_end: string;
}

export interface MonitoringFinding {
  kind: string;
  finding_key: string;
  detail: string;
  observed_at?: string | null;
  value?: number | null;
  threshold?: number | null;
  source_ids?: string[];
}

export interface MonitoringSourceReference {
  kind: "scientific_record" | "reviewed_event_summary";
  id: string;
  sha256: string;
  observed_at?: string | null;
  acquired_at?: string | null;
  source?: string | null;
  original_value?: number | null;
  original_unit?: string | null;
  normalized_value?: number | null;
  normalized_unit?: string | null;
  qc?: string | null;
}

export interface MonitoringBiologicalSession {
  summary_id: string;
  link_revision_id: string;
  link_source_sha256: string;
  organism_key: string;
  unit_type: string;
  unit_id: string;
  video_id: string;
  video_sha256: string;
  measurement_sha256: string;
  event_revision_digest: string;
  event_ids: string[];
  observed_at: string | null;
  frame_start: number;
  frame_end: number;
  valid_duration_s: number;
  confirmed_event_count: number;
  unreviewed_count: number;
  partial_count: number;
  excluded_confirmed_count: number;
}

export interface MonitoringAssessment {
  id: string;
  project_id: string;
  rule_id: string;
  window_start: string;
  window_end: string;
  evidence_sha256: string;
  result_sha256: string;
  result: {
    schema_version: "monitoring-assessment-0001";
    kind: MonitoringKind;
    protocol: string;
    metric: string;
    unit: string;
    estimate: number | null;
    effort: Record<string, number | null>;
    source_refs: MonitoringSourceReference[];
    method?: string;
    biological_sessions?: MonitoringBiologicalSession[];
    exclusions: {
      kind: string;
      source_id?: string | null;
      observed_at?: string | null;
      reason: string;
    }[];
    findings: MonitoringFinding[];
  };
  created_at: string;
  source_status: SourceStatus;
  stale_reasons: string[];
}

export interface MonitoringReview {
  id: string;
  project_id: string;
  alert_id: string;
  reviewer: string;
  decision: ReviewDecision;
  reason: string;
  revision: number;
  reviewed_at: string;
}

export interface MonitoringAlert {
  id: string;
  project_id: string;
  assessment_id: string;
  kind: string;
  finding_key: string;
  proposal: MonitoringFinding;
  proposal_sha256: string;
  created_at: string;
  status: "proposed" | ReviewDecision;
  review_revision: number;
  latest_review: MonitoringReview | null;
  source_status: SourceStatus;
}

export interface MonitoringSummarySelection {
  project_id: string;
  assessment_id: string;
}

export interface MonitoringSummaryRow extends MonitoringSummarySelection {
  project_name: string;
  rule_id: string;
  rule_sha256: string;
  protocol: string;
  metric: string;
  unit: string;
  window_start: string;
  window_end: string;
  kind: MonitoringKind;
  status: "included" | "excluded";
  reasons: string[];
  result_sha256: string;
  evidence_sha256: string;
  effort: Record<string, unknown>;
  values: {
    estimate: number | null;
    method: string;
    source_refs: MonitoringSourceReference[];
    independent_units: Array<{
      unit_type: string | null;
      unit_id: string | null;
      organism_key: string;
      video_id: string;
      video_sha256: string;
      link_revision_id: string;
    }>;
    exclusions: MonitoringAssessment["result"]["exclusions"];
    rule_parameters: Record<string, unknown>;
  };
  review: {
    proposed: number;
    confirmed: number;
    dismissed: number;
    alerts: Array<{
      alert_id: string;
      kind: string;
      proposal_sha256: string;
      status: MonitoringAlert["status"];
      review_revision: number;
      latest_review: MonitoringReview | null;
    }>;
  };
}

export interface MonitoringSummary {
  id: string;
  project_id: string;
  created_at: string;
  content_sha256: string;
  snapshot: {
    schema_version: "monitoring-comparison-1.7";
    reference_project_id: string;
    rows: MonitoringSummaryRow[];
  };
}

interface ResultsPage<T> {
  items: T[];
  total: number;
}

interface MonitoringPage<T> extends ResultsPage<T> {
  limit: number;
  offset: number;
}

const scope = (projectId: string) =>
  `/projects/${encodeURIComponent(projectId)}/monitoring`;
const listQuery = (offset: number) => `?limit=50&offset=${offset}`;
const post = (data: unknown): RequestInit => ({
  method: "POST",
  body: JSON.stringify(data),
});

export function listMonitoringRules(
  projectId: string,
  offset: number,
  signal?: AbortSignal,
) {
  return request<MonitoringPage<MonitoringRule>>(
    `${scope(projectId)}/rules${listQuery(offset)}`,
    { signal },
  );
}

export function getMonitoringRule(
  projectId: string,
  ruleId: string,
  signal?: AbortSignal,
) {
  return request<MonitoringRule>(
    `${scope(projectId)}/rules/${encodeURIComponent(ruleId)}`,
    { signal },
  );
}

export function createMonitoringRule(
  projectId: string,
  data: MonitoringRuleCreate,
) {
  return request<MonitoringRule>(`${scope(projectId)}/rules`, post(data));
}

export function listMonitoringAssessments(
  projectId: string,
  offset: number,
  signal?: AbortSignal,
) {
  return request<MonitoringPage<MonitoringAssessment>>(
    `${scope(projectId)}/assessments${listQuery(offset)}`,
    { signal },
  );
}

export function getMonitoringAssessment(
  projectId: string,
  assessmentId: string,
  signal?: AbortSignal,
) {
  return request<MonitoringAssessment>(
    `${scope(projectId)}/assessments/${encodeURIComponent(assessmentId)}`,
    { signal },
  );
}

export function createMonitoringAssessment(
  projectId: string,
  data: MonitoringAssessmentCreate,
) {
  return request<MonitoringAssessment>(
    `${scope(projectId)}/assessments`,
    post(data),
  );
}

export function listMonitoringAlerts(
  projectId: string,
  assessmentId: string,
  offset: number,
  signal?: AbortSignal,
) {
  return request<MonitoringPage<MonitoringAlert>>(
    `${scope(projectId)}/alerts${listQuery(offset)}&assessment_id=${encodeURIComponent(assessmentId)}`,
    { signal },
  );
}

const reviews = (projectId: string, alertId: string) =>
  `${scope(projectId)}/alerts/${encodeURIComponent(alertId)}/reviews`;

export function listMonitoringReviews(
  projectId: string,
  alertId: string,
  offset: number,
  signal?: AbortSignal,
) {
  return request<MonitoringPage<MonitoringReview>>(
    `${reviews(projectId, alertId)}${listQuery(offset)}`,
    { signal },
  );
}

export function reviewMonitoringAlert(
  projectId: string,
  alertId: string,
  expectedRevision: number,
  decision: ReviewDecision,
  reason: string,
) {
  return request<MonitoringReview>(
    reviews(projectId, alertId),
    post({
      expected_revision: expectedRevision,
      decision,
      reason,
    }),
  );
}

const summaries = (projectId: string) => `${scope(projectId)}/summaries`;

export function listMonitoringSummaries(
  projectId: string,
  offset: number,
  signal?: AbortSignal,
) {
  return request<ResultsPage<MonitoringSummary>>(
    `${summaries(projectId)}${listQuery(offset)}`,
    { signal },
  );
}

export function getMonitoringSummary(
  projectId: string,
  summaryId: string,
  signal?: AbortSignal,
) {
  return request<MonitoringSummary>(
    `${summaries(projectId)}/${encodeURIComponent(summaryId)}`,
    { signal },
  );
}

export function createMonitoringSummary(
  projectId: string,
  selections: MonitoringSummarySelection[],
) {
  return request<MonitoringSummary>(summaries(projectId), post({ selections }));
}

export async function downloadMonitoringSummary(
  projectId: string,
  summary: MonitoringSummary,
) {
  const exported = await request<object>(
    `${summaries(projectId)}/${encodeURIComponent(summary.id)}/export`,
  );
  const url = URL.createObjectURL(
    new Blob([`${JSON.stringify(exported, null, 2)}\n`], {
      type: "application/json",
    }),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `monitoring-project-summary-${summary.content_sha256}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}
