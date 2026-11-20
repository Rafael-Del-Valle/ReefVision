import { request } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";

export interface FieldClock {
  state: "known_offset" | "unknown";
  wall_time: string | null;
  utc_offset_minutes: number | null;
  evidence: string;
}

export interface FieldMetadata {
  observer: string;
  clock: FieldClock;
  observation_key: string | null;
  site: string | null;
  subject: string | null;
  source_label: string | null;
  position: { latitude: number; longitude: number; evidence: string } | null;
  notes: string | null;
}

export interface FieldSourceEvidence {
  source_observation_id: string;
  filename: string;
  kind: "image" | "video";
  sha256: string;
  size_bytes: number;
  metadata: FieldMetadata;
}

export interface FieldObservation extends FieldSourceEvidence {
  id: string;
  captured_at_utc: string | null;
}

export interface FieldBatchSummary {
  id: string;
  project_id: string;
  origin_project_id: string;
  origin_batch_id: string;
  label: string;
  manifest_sha256: string | null;
  created_at: string;
}

export interface FieldBatch extends FieldBatchSummary {
  observations: FieldObservation[];
}

export interface FieldConflict {
  against_observation_id: string;
  against_batch_id: string;
  reason:
    | "source_identity_changed"
    | "declared_observation_changed"
    | "media_metadata_changed";
  against: FieldSourceEvidence;
}

export interface FieldReconciliationRow {
  observation_id: string;
  source_observation_id: string;
  kind: "image" | "video";
  sha256: string;
  asset_id: string;
  outcome: "imported" | "duplicate_media" | "conflict";
  conflicts: FieldConflict[];
}

export interface FieldReconciliation {
  project_id: string;
  batch_id: string;
  manifest_sha256: string;
  rows: FieldReconciliationRow[];
  report_sha256: string;
}

export type FieldDecision =
  "retain_both" | "prefer_existing" | "prefer_incoming";

export interface FieldReviewInput {
  observation_id: string;
  against_observation_id: string;
  reviewer: string;
  decision: FieldDecision;
  notes: string;
}

export interface FieldReview extends FieldReviewInput {
  id: string;
  created_at: string;
}

const copyingTimeout = 30 * 60 * 1000;
const root = (projectId: string) =>
  `/projects/${encodeURIComponent(projectId)}/field-capture`;
const batchPath = (projectId: string, batchId: string) =>
  `${root(projectId)}/batches/${encodeURIComponent(batchId)}`;

export function listFieldBatches(
  projectId: string,
  page: number,
  signal?: AbortSignal,
) {
  return request<{
    items: FieldBatchSummary[];
    page: number;
    page_size: number;
    total: number;
  }>(`${root(projectId)}/batches?page=${page}`, { signal });
}

export function createFieldBatch(projectId: string, label: string) {
  return request<FieldBatch>(`${root(projectId)}/batches`, {
    method: "POST",
    body: JSON.stringify({ label }),
  });
}

export function getFieldBatch(
  projectId: string,
  batchId: string,
  signal?: AbortSignal,
) {
  return request<FieldBatch>(batchPath(projectId, batchId), { signal });
}

export function captureFieldObservation(
  projectId: string,
  batchId: string,
  file: File,
  metadata: FieldMetadata,
) {
  const form = new FormData();
  form.set("file", file);
  form.set("metadata", JSON.stringify(metadata));
  return request<FieldObservation>(
    `${batchPath(projectId, batchId)}/observations`,
    { method: "POST", body: form },
    copyingTimeout,
  );
}

export function sealFieldBatch(projectId: string, batchId: string) {
  return request<FieldBatch>(
    `${batchPath(projectId, batchId)}/seal`,
    { method: "POST" },
    copyingTimeout,
  );
}

export function importFieldBatch(projectId: string, file: File) {
  const form = new FormData();
  form.set("file", file);
  return request<{ batch: FieldBatch; duplicate: boolean }>(
    `${root(projectId)}/imports`,
    { method: "POST", body: form },
    copyingTimeout,
  );
}

export function fieldBatchDownload(projectId: string, batchId: string) {
  return `${getApiBaseUrl()}${batchPath(projectId, batchId)}/archive`;
}

export function fieldOriginalDownload(
  projectId: string,
  batchId: string,
  observationId: string,
) {
  return `${getApiBaseUrl()}${batchPath(projectId, batchId)}/observations/${encodeURIComponent(observationId)}/content`;
}

export function reconcileFieldBatch(
  projectId: string,
  batchId: string,
  manifestSha256: string,
) {
  return request<FieldReconciliation>(
    `${batchPath(projectId, batchId)}/reconcile`,
    {
      method: "POST",
      body: JSON.stringify({ manifest_sha256: manifestSha256 }),
    },
    copyingTimeout,
  );
}

export async function getFieldReconciliation(
  projectId: string,
  batchId: string,
  signal?: AbortSignal,
) {
  const response = await fetch(
    `${getApiBaseUrl()}${batchPath(projectId, batchId)}/reconciliation`,
    { signal },
  );
  if (response.status === 404) return null;
  if (!response.ok)
    throw new Error(
      `Field reconciliation could not be read (HTTP ${response.status}).`,
    );
  return (await response.json()) as FieldReconciliation;
}

export function listFieldReviews(
  projectId: string,
  batchId: string,
  signal?: AbortSignal,
) {
  return request<FieldReview[]>(`${batchPath(projectId, batchId)}/reviews`, {
    signal,
  });
}

export function recordFieldReview(
  projectId: string,
  batchId: string,
  review: FieldReviewInput,
) {
  return request<FieldReview>(`${batchPath(projectId, batchId)}/reviews`, {
    method: "POST",
    body: JSON.stringify(review),
  });
}

export function downloadFieldReconciliation(report: object, digest: string) {
  const url = URL.createObjectURL(
    new Blob([`${JSON.stringify(report, null, 2)}\n`], {
      type: "application/json",
    }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = `field-reconciliation-${digest}.json`;
  link.click();
  URL.revokeObjectURL(url);
}
