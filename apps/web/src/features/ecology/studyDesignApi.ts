import { request } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";
import type {
  EcologyStudyAssignment,
  Metric,
  OrganismKind,
} from "./ecologyApi";
import type {
  PairedGrowthDesign,
  PairedGrowthReport,
} from "./pairedGrowthContrastApi";

export interface StudyTreatment {
  code: string;
  label: string;
}

export interface StudyDesignDeclaration {
  title: string;
  timing: "prospective" | "retrospective";
  reviewed_by: string;
  review_note: string;
  confirm_review: true;
  contrast: PairedGrowthDesign;
  metric: Metric;
  method: "paired_growth_contrast";
  nesting: "parent_colony_within_unit";
  exclusion_policy: "reviewed_source_exclusions" | "no_source_exclusions";
  exclusion_rule: string;
  organism_keys: string[];
  treatments: StudyTreatment[];
}

export interface StudyDesignSource {
  growth_analysis_id: string;
  growth_source_sha256: string;
}

export interface StudyDesignCreate extends Partial<StudyDesignSource> {
  declaration: StudyDesignDeclaration;
  supersedes_revision_id?: string;
  supersedes_sha256?: string;
}

export interface StudyDesignRosterMember {
  identity_id: string;
  organism_key: string;
  identity_revision: number;
  kind: OrganismKind;
  parent_colony_key: string | null;
  experimental_unit_type: string;
  experimental_unit_id: string;
  assignment: EcologyStudyAssignment;
}

export interface StudyDesignSnapshot {
  schema_version: "1.5";
  project_id: string;
  design_id: string;
  revision_id: string;
  supersedes_revision_id: string | null;
  revision: number;
  created_at: string;
  declared_at: string;
  declaration: StudyDesignDeclaration;
  roster: StudyDesignRosterMember[];
  binding: {
    analysis_id: string;
    source_sha256: string;
    paired_report: PairedGrowthReport;
  } | null;
}

export interface StudyDesignRecord {
  id: string;
  project_id: string;
  design_id: string;
  supersedes_revision_id: string | null;
  revision: number;
  created_at: string;
  growth_analysis_id: string | null;
  growth_source_sha256: string | null;
  source_id_map: Record<string, string>;
  content_sha256: string;
  snapshot: StudyDesignSnapshot;
}

interface StudyDesignPage {
  items: StudyDesignRecord[];
  total: number;
}

export function studyDesignKey(projectId: string) {
  return ["study-designs", projectId];
}

function base(projectId: string) {
  return `/projects/${encodeURIComponent(projectId)}/ecology/study-designs`;
}

export function listStudyDesigns(
  projectId: string,
  page: number,
  signal?: AbortSignal,
) {
  return request<StudyDesignPage>(
    `${base(projectId)}?page=${page}&page_size=20`,
    { signal },
  );
}

export function getStudyDesign(
  projectId: string,
  revisionId: string,
  signal?: AbortSignal,
) {
  return request<StudyDesignRecord>(
    `${base(projectId)}/${encodeURIComponent(revisionId)}`,
    { signal },
  );
}

export function saveStudyDesign(projectId: string, payload: StudyDesignCreate) {
  return request<StudyDesignRecord>(base(projectId), {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function bindStudyDesign(
  projectId: string,
  revisionId: string,
  payload: StudyDesignSource & { design_sha256: string },
) {
  return request<StudyDesignRecord>(
    `${base(projectId)}/${encodeURIComponent(revisionId)}/bind`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function studyDesignExport(projectId: string, revisionId: string) {
  return `${getApiBaseUrl()}${base(projectId)}/${encodeURIComponent(revisionId)}/design.json`;
}
