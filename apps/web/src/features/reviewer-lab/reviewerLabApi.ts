import { request } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";

export type ReviewRole = "manager" | "reviewer" | "adjudicator";
export type ReviewValue = "usable" | "unusable" | "uncertain";
export const values: ReviewValue[] = ["usable", "unusable", "uncertain"];
export const valueLabels: Record<ReviewValue, string> = {
  usable: "Usable",
  unusable: "Unusable",
  uncertain: "Uncertain",
};

export interface LabRole {
  id: string;
  member_id: string;
  name: string;
  role: ReviewRole;
  revision: number;
  active: boolean;
  previous_revision_id: string | null;
  granted_by_role_revision_id: string | null;
  created_at: string;
}

export interface LabSession {
  actor: LabRole;
  key: string;
}

export interface LabDecision {
  id: string;
  value: ReviewValue;
  reason: string;
  role_revision_id: string;
  created_at: string;
}

export interface LabSource {
  type: "image" | "queue_item";
  id: string;
}

export interface LabSubject {
  id: string;
  image_id: string;
  filename: string;
  source_sha256: string;
  annotation_revision: number;
  queue_item_id?: string;
  own_decision?: LabDecision;
  paired_decisions?: [LabDecision, LabDecision];
  resolution?: LabDecision;
  complete?: boolean;
}

export interface LabRound {
  id: string;
  title: string;
  criterion: string;
  plan_sha256: string;
  report_id?: string;
  subjects: LabSubject[];
}

export interface LabReport {
  id: string;
  round_id: string;
  authority: "local_attribution";
  plan: {
    title: string;
    criterion: string;
  };
  agreement: {
    planned_subjects: number;
    paired_subjects: number;
    agreements: number;
    disagreements: number;
    adjudicated_disagreements: number;
    observed_agreement: number;
    cohens_kappa: number | null;
    matrix: Record<ReviewValue, Record<ReviewValue, number>>;
  };
  role_revisions: LabRole[];
  subjects: Array<{
    source: LabSubject;
    first: LabDecision;
    second: LabDecision;
    resolution: LabDecision | null;
  }>;
  content_sha256: string;
}

export function localRoleKey(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(32)), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

function labPath(projectId: string, path: string): string {
  return "/projects/" + encodeURIComponent(projectId) + "/reviewer-lab" + path;
}

export function labRequest<T>(
  projectId: string,
  path: string,
  options: {
    key?: string;
    newKey?: string;
    body?: unknown;
    signal?: AbortSignal;
  } = {},
): Promise<T> {
  const headers = new Headers();
  if (options.key) headers.set("Authorization", "Bearer " + options.key);
  if (options.newKey) headers.set("X-ReefVision-Role-Key", options.newKey);
  return request<T>(labPath(projectId, path), {
    method: options.body === undefined ? "GET" : "POST",
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    headers,
    signal: options.signal,
    cache: "no-store",
    credentials: "omit",
  });
}

export async function reviewImage(
  projectId: string,
  roundId: string,
  subjectId: string,
  key: string,
  signal: AbortSignal,
): Promise<Blob> {
  const response = await fetch(
    getApiBaseUrl() +
      labPath(
        projectId,
        "/rounds/" + roundId + "/subjects/" + subjectId + "/image",
      ),
    {
      headers: { Authorization: "Bearer " + key },
      signal,
      cache: "no-store",
      credentials: "omit",
    },
  );
  if (!response.ok)
    throw new Error(
      "The pinned source image is unavailable. Reload the round before deciding.",
    );
  return response.blob();
}

export function agreementExportUrl(
  projectId: string,
  reportId: string,
): string {
  return (
    getApiBaseUrl() + labPath(projectId, "/reports/" + reportId + "/export")
  );
}

export function displayError(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Reviewer Lab could not complete the request.";
}
