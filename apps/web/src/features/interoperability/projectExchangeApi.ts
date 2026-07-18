import { getApiBaseUrl } from "../../runtime";

export interface ProjectExchangePackageRecord {
  id: string;
  project_id: string;
  job_id: string | null;
  direction: string;
  status: string;
  format_version: string;
  manifest_json: Record<string, unknown>;
  manifest_sha256: string;
  archive_path: string;
  options_json: Record<string, unknown>;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface ProjectExchangeInspection {
  compatible: boolean;
  format_name: string | null;
  format_version: string | null;
  application_version: string | null;
  manifest_sha256: string | null;
  project_name: string | null;
  section_counts: Record<string, number>;
  included_media_count: number;
  warnings: string[];
  errors: string[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = `Interoperability request failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string") message = payload.detail;
    } catch {
      // Keep the HTTP fallback.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function projectExchangeDownloadUrl(packageId: string): string {
  return `${getApiBaseUrl()}/exchange-packages/${encodeURIComponent(packageId)}/download`;
}

export function getProjectExchangePackages(
  projectId: string,
  signal?: AbortSignal,
): Promise<ProjectExchangePackageRecord[]> {
  return request<ProjectExchangePackageRecord[]>(
    `/projects/${encodeURIComponent(projectId)}/exchange-packages`,
    { signal },
  );
}

export async function createProjectExchange(
  projectId: string,
  payload: {
    include_media: boolean;
    include_model_weights: boolean;
    include_generated_artifacts: boolean;
    notes?: string;
  },
): Promise<{ package: ProjectExchangePackageRecord; job_id: string }> {
  return request<{ package: ProjectExchangePackageRecord; job_id: string }>(
    `/projects/${encodeURIComponent(projectId)}/exchange-packages`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function inspectProjectExchange(
  file: File,
): Promise<ProjectExchangeInspection> {
  const form = new FormData();
  form.append("file", file);
  return request<ProjectExchangeInspection>("/exchange-packages/inspect", {
    method: "POST",
    body: form,
  });
}
