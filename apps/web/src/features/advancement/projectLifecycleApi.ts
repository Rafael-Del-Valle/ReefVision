import { getApiBaseUrl } from "../../runtime";
import type { JobRecord, Project } from "../../api/client";

export interface ProjectArchiveVerification {
  archive_path: string;
  valid: boolean;
  format_version: string | null;
  application_version: string | null;
  source_schema_revision: string | null;
  source_project_id: string | null;
  source_project_name: string | null;
  table_count: number;
  record_count: number;
  file_count: number;
  total_file_bytes: number;
  missing_tables: string[];
  incompatible_columns: string[];
  checksum_failures: string[];
  warnings: string[];
  blockers: string[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers,
  });
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string") message = payload.detail;
    } catch {
      // Preserve the HTTP fallback.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function updateProjectLifecycle(
  projectId: string,
  payload: { name?: string; slug?: string; description?: string | null },
) {
  return request<Project>(`/projects/${projectId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function queueProjectArchive(projectId: string, notes?: string) {
  return request<{ job: JobRecord }>(`/projects/${projectId}/archive-export`, {
    method: "POST",
    body: JSON.stringify({
      include_archived_records: true,
      notes: notes || null,
    }),
  });
}

export function queueProjectDuplicate(
  projectId: string,
  payload: { name: string; slug?: string },
) {
  return request<{ job: JobRecord }>(`/projects/${projectId}/duplicate`, {
    method: "POST",
    body: JSON.stringify({ ...payload, include_archived_records: true }),
  });
}

export function queueProjectStorageMigration(
  projectId: string,
  payload: { destination_relative_path: string; mode: "move" | "copy" },
) {
  return request<{ job: JobRecord }>(
    `/projects/${projectId}/storage-migration`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function verifyProjectArchive(archivePath: string) {
  const search = new URLSearchParams({ archive_path: archivePath });
  return request<ProjectArchiveVerification>(
    `/project-archives/verify?${search}`,
  );
}

export function queueProjectArchiveImport(payload: {
  archive_path: string;
  name?: string;
  slug?: string;
  restore_as_active: boolean;
}) {
  return request<{ job: JobRecord }>("/project-archives/import", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function restoreArchivedProject(projectId: string) {
  return request<{ project: Project }>(`/projects/${projectId}/restore`, {
    method: "POST",
  });
}

export function getLifecycleJob(jobId: string) {
  return request<JobRecord>(`/jobs/${jobId}`);
}
