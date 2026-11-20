import { getApiBaseUrl } from "../../runtime";

export interface ConditionRubric {
  rubric_id: string;
  version: string;
  reference: string;
  observation_unit: string;
  labels: string[];
}

export interface ConditionObservation {
  rubric: ConditionRubric;
  source_sha256: string;
  metadata_revision_id: string | null;
  observation_unit_id: string;
  label: string;
  observer_id: string;
  observed_at_utc: string;
  reference_evidence: string;
  uncertainty: string;
}

export type ConditionDecisionKind =
  "agree" | "disagree" | "inconclusive" | "adjudicated";

export interface ConditionDecision {
  actor_id: string;
  decision: ConditionDecisionKind;
  label: string | null;
  reference_evidence: string;
  decided_at_utc: string;
  uncertainty: string;
}

export interface ConditionRevision {
  id: string;
  observation_id: string;
  previous_revision_id: string | null;
  phase: "observation" | "review" | "adjudication";
  observation: ConditionObservation;
  decision: ConditionDecision | null;
  resolved_label: string | null;
  stale_source_metadata: boolean;
}

function conditionUrl(projectId: string, assetId: string): string {
  return `${getApiBaseUrl()}/projects/${encodeURIComponent(projectId)}/spatial/assets/${encodeURIComponent(assetId)}/condition-observations`;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const error: { detail?: string | { msg?: string }[] } = await response
      .json()
      .catch(() => ({}));
    const detail = Array.isArray(error.detail)
      ? error.detail[0]?.msg
      : error.detail;
    throw new Error(
      detail || `Condition request failed (HTTP ${response.status})`,
    );
  }
  return (await response.json()) as T;
}

function jsonBody(body: ConditionObservation | ConditionDecision): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export const CONDITION_PAGE_SIZE = 50;

export function listConditionRevisions(
  projectId: string,
  assetId: string,
  offset: number,
  signal: AbortSignal,
) {
  return request<ConditionRevision[]>(
    `${conditionUrl(projectId, assetId)}?limit=${CONDITION_PAGE_SIZE}&offset=${offset}&newest_first=true`,
    { signal },
  );
}

export function recordCondition(
  projectId: string,
  assetId: string,
  observation: ConditionObservation,
) {
  return request<ConditionRevision>(
    conditionUrl(projectId, assetId),
    jsonBody(observation),
  );
}

export function decideCondition(
  projectId: string,
  assetId: string,
  revisionId: string,
  decision: ConditionDecision,
) {
  return request<ConditionRevision>(
    `${conditionUrl(projectId, assetId)}/${encodeURIComponent(revisionId)}/decisions`,
    jsonBody(decision),
  );
}

export function conditionReportUrl(
  projectId: string,
  assetId: string,
  revisionId: string,
) {
  return `${conditionUrl(projectId, assetId)}/${encodeURIComponent(revisionId)}/report`;
}
