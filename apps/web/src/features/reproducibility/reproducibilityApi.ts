import { request } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";

type Ref = { id: string; content_sha256: string };

export interface ResearchProof {
  schema_version: "reefvision-research-proof-1";
  evidence: { study: Ref; review: Ref; comparison: Ref };
  section_sha256: Record<string, string>;
  proof_sha256: string;
}

export interface ResearchOmission {
  kind: string;
  record_id: string;
  name: string;
  sha256: string;
  requires_relink_for: string[];
}

export interface ResearchManifest {
  proof: ResearchProof;
  exchange_manifest_sha256: string;
  entries: { path: string; size_bytes: number; sha256: string }[];
  omitted_sources: ResearchOmission[];
  included_media_count: number;
}

export interface ResearchPackage {
  id: string;
  project_id: string;
  direction: "export" | "import";
  status: "queued" | "running" | "complete" | "failed";
  job_id: string | null;
  manifest: ResearchManifest | null;
  manifest_sha256: string | null;
  proof_sha256: string | null;
  error_message: string | null;
}

export interface ResearchInspection {
  compatible: boolean;
  project_name: string | null;
  manifest: ResearchManifest | null;
  manifest_sha256: string | null;
  errors: string[];
}

export interface ResearchImport {
  project_id: string;
  project_name: string;
  reproducibility_package_id: string;
  proof_sha256: string;
  omitted_sources: ResearchOmission[];
}

export interface ResearchSelection {
  study_design_id: string;
  reviewer_report_id: string;
  comparison_id: string;
  include_media: boolean;
  include_model_weights: boolean;
}

const research = "/reproducibility-packages";
const projectPath = (projectId: string) =>
  "/projects/" + encodeURIComponent(projectId);

export function listResearchPackages(projectId: string, signal?: AbortSignal) {
  return request<ResearchPackage[]>(projectPath(projectId) + research, {
    signal,
  });
}

export function listResearchProofs(projectId: string, signal?: AbortSignal) {
  return request<ResearchProof[]>(
    projectPath(projectId) + "/reproducibility-proofs",
    { signal },
  );
}

export function createResearchPackage(
  projectId: string,
  selection: ResearchSelection,
) {
  return request<{ package: ResearchPackage; job_id: string }>(
    projectPath(projectId) + research,
    { method: "POST", body: JSON.stringify(selection) },
  );
}

export function downloadResearchPackageUrl(id: string): string {
  return (
    getApiBaseUrl() + research + "/" + encodeURIComponent(id) + "/download"
  );
}

export function inspectResearchPackage(file: File) {
  const body = new FormData();
  body.append("file", file);
  return request<ResearchInspection>(
    research + "/inspect",
    { method: "POST", body },
    900_000,
  );
}

export function importResearchPackage(file: File, name: string) {
  const body = new FormData();
  body.append("file", file);
  if (name.trim()) body.append("project_name", name.trim());
  return request<ResearchImport>(
    research + "/import",
    { method: "POST", body },
    900_000,
  );
}
