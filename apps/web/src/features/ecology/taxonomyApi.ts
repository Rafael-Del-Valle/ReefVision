import { request, type ProjectImage } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";
import type { ReviewRole } from "../reviewer-lab/reviewerLabApi";
import type { VideoAssetRecord } from "../video/videoApi";

export type TaxonRank =
  "species" | "genus" | "family" | "order" | "class" | "phylum" | "unranked";
export type TaxonDecision = "confirmed" | "dismissed" | "unresolved";
export type VisitOutcome =
  "detected" | "not_detected" | "unknown" | "unobserved";

export interface TaxonomySource {
  kind: "image" | "video";
  id: string;
  sha256: string;
}

interface LocalAttribution {
  name: string;
  member_id: string;
  role_revision_id: string;
  role: ReviewRole;
}

interface IdentityPin {
  id: string;
  organism_key: string;
  revision: number;
  experimental_unit_type: string | null;
  experimental_unit_id: string | null;
  sha256: string;
}

export interface TaxonProposal {
  id: string;
  project_id: string;
  state: "proposed" | TaxonDecision;
  review_revision: number;
  proposal_sha256: string;
  proposal: {
    scientific_name: string;
    rank: TaxonRank;
    identity: IdentityPin;
    source: TaxonomySource;
    author: LocalAttribution;
    reason: string;
  };
}

export interface TaxonReview {
  id: string;
  revision: number;
  review_sha256: string;
  review: {
    reviewer: LocalAttribution;
    decision: TaxonDecision;
    reason: string;
    reviewed_at: string;
    source?: TaxonomySource | null;
  };
}

export interface VisitSnapshot {
  proposal_id: string;
  identity: IdentityPin;
  observer: LocalAttribution;
  protocol: string;
  started_at: string;
  effort_seconds: number;
  outcome: VisitOutcome;
  source: TaxonomySource | null;
  notes: string;
}

export interface DetectabilityVisit {
  id: string;
  project_id: string;
  visit_sha256: string;
  presence_revision: number;
  presence_status: "pending" | TaxonDecision;
  visit: VisitSnapshot;
}

export interface DetectabilityAssessment {
  id: string;
  project_id: string;
  result_sha256: string;
  result: {
    request: {
      scientific_name: string;
      rank: TaxonRank;
      protocol: string;
      unit_type: string;
      minimum_effort_seconds: number;
      window_start: string;
      window_end: string;
    };
    status: "estimated" | "withheld";
    withhold_reason: string | null;
    estimate: number | null;
    confidence_interval: { level: number; lower: number; upper: number } | null;
    independent_groups: number;
    total_recorded_visits: number;
    eligible_visits: number;
    observed_detections: number;
    observed_nondetections: number;
    included_effort_seconds: number;
    evidence_sha256: string;
    assumptions: string[];
    groups: Array<{
      unit_id: string;
      eligible_visits: number;
      detections: number;
      nondetections: number;
      effort_seconds: number;
      detection_fraction: number;
    }>;
    visits: Array<{
      id: string;
      visit: VisitSnapshot;
      visit_sha256: string;
      proposal: TaxonProposal;
      taxonomy_review: TaxonReview | null;
      presence_review: TaxonReview | null;
      exclusion: string | null;
    }>;
  };
}

export interface TaxonomyPage<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

function route(projectId: string, resource: string) {
  return `/projects/${encodeURIComponent(projectId)}/taxonomy/${resource}`;
}

export function taxonomyPage<T>(
  projectId: string,
  resource: string,
  offset: number,
  signal: AbortSignal,
) {
  return request<TaxonomyPage<T>>(
    route(projectId, resource) + `?limit=25&offset=${offset}`,
    { signal },
  );
}

export function recordTaxonomy<T>(
  projectId: string,
  resource: string,
  body: unknown,
  key?: string,
) {
  return request<T>(route(projectId, resource), {
    method: "POST",
    headers: key ? { Authorization: "Bearer " + key } : {},
    body: JSON.stringify(body),
    credentials: "omit",
    cache: "no-store",
  });
}

export async function pinTaxonomySource(
  projectId: string,
  selection: string,
): Promise<TaxonomySource | null> {
  if (!selection) return null;
  const [kind, id] = selection.split(":");
  if ((kind !== "image" && kind !== "video") || !id)
    throw new Error("Choose a project source.");
  const resource = kind === "image" ? "images" : "videos";
  const source = await request<ProjectImage | VideoAssetRecord>(
    `/${resource}/${encodeURIComponent(id)}`,
  );
  if (source.project_id !== projectId)
    throw new Error("Choose an original in this project.");
  return { kind, id, sha256: source.sha256 };
}

export function detectabilityExportUrl(projectId: string, id: string) {
  return (
    getApiBaseUrl() +
    route(projectId, `assessments/${encodeURIComponent(id)}/export`)
  );
}

export function taxonomyOriginalUrl(projectId: string, source: TaxonomySource) {
  return (
    getApiBaseUrl() +
    route(
      projectId,
      `source/${source.kind}/${encodeURIComponent(source.id)}?sha256=${source.sha256}`,
    )
  );
}
