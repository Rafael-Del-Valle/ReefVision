import { getApiBaseUrl } from "../../runtime";
import { request } from "../../api/client";

export type OrganismKind = "colony" | "fragment" | "individual";

export interface IdentityFields {
  kind: OrganismKind;
  parent_colony_key: string | null;
  experimental_unit_type: string | null;
  experimental_unit_id: string | null;
  reason: string;
}
export interface Identity extends IdentityFields {
  id: string;
  organism_key: string;
  revision: number;
  created_at: string;
}
export interface ImageLink {
  id: string;
  organism_key: string;
  identity_revision: number;
  image_id: string;
  image_sha256: string;
  source_metadata_sha256: string | null;
  reason: string;
}
export interface AnnotationLink {
  id: string;
  image_evidence_id: string;
  annotation_kind: "box" | "mask";
  annotation_id: string;
  annotation_revision: number;
  annotation_sha256: string;
}
export interface CalibrationLink {
  id: string;
  annotation_evidence_id: string;
  calibration_sha256: string;
}
export interface Registry {
  identities: Identity[];
  identity_history: Identity[];
  image_evidence_links: ImageLink[];
  annotation_evidence_links: AnnotationLink[];
  calibration_evidence_links: CalibrationLink[];
  snapshot_sha256: string;
  design_change_count: number;
}
export type Metric = "box_width" | "box_height" | "mask_projected_area";
export interface EndpointChange {
  organism_key: string;
  identity_revision: number;
  metric: Metric;
  baseline_capture_timestamp_utc: string;
  final_capture_timestamp_utc: string;
  baseline_value: number;
  final_value: number;
  absolute_change: number;
  unit: string;
  elapsed_days: number;
}
export interface Candidates {
  candidate_count: number;
  projected_endpoint_changes: EndpointChange[];
  exclusions: { calibration_evidence_id: string; reason: string }[];
  input_sha256: string;
}

type EvidenceWrites =
  | {
      action: "image-evidence";
      image_id: string;
      expected_identity_revision: number;
      reason: string;
    }
  | {
      action: "annotation-evidence";
      image_evidence_id: string;
      annotation_kind: "box" | "mask";
      annotation_id: string;
      expected_annotation_revision: number;
      reason: string;
    }
  | {
      action: "calibration-evidence";
      annotation_evidence_id: string;
      expected_annotation_sha256: string;
      confirm_source_calibration: true;
      reason: string;
    };

function base(projectId: string) {
  return `/projects/${encodeURIComponent(projectId)}/ecology`;
}
export const getRegistry = (projectId: string, signal?: AbortSignal) =>
  request<Registry>(`${base(projectId)}/identity-registry`, { signal });
export const getCandidates = (projectId: string, signal?: AbortSignal) =>
  request<Candidates>(`${base(projectId)}/calibrated-measurement-candidates`, {
    signal,
  });
export const ecologyCsv = (projectId: string, path: string) =>
  `${getApiBaseUrl()}${base(projectId)}/${path}`;
export function saveOrganism(
  projectId: string,
  key: string,
  fields: IdentityFields,
  existing?: Identity,
) {
  return request<Identity>(
    existing
      ? `${base(projectId)}/organisms/${encodeURIComponent(key)}/revisions`
      : `${base(projectId)}/organisms`,
    {
      method: "POST",
      body: JSON.stringify(
        existing
          ? { ...fields, expected_revision: existing.revision }
          : { ...fields, organism_key: key },
      ),
    },
  );
}
export function linkEvidence(
  projectId: string,
  key: string,
  { action, ...payload }: EvidenceWrites,
) {
  return request<ImageLink | AnnotationLink | CalibrationLink>(
    `${base(projectId)}/organisms/${encodeURIComponent(key)}/${action}`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}
