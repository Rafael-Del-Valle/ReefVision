import { getApiBaseUrl } from "../../runtime";

export interface ProjectRepairAction {
  action_id: string;
  action_kind: "create_project_root" | "quarantine_orphan_file";
  managed_path: string;
  reason: string;
  safe_automatic: boolean;
  size_bytes: number | null;
  modified_at: string | null;
}

export interface ProjectRepairPlan {
  project_id: string;
  generated_at: string;
  minimum_orphan_age_seconds: number;
  referenced_path_count: number;
  orphan_file_count: number;
  orphan_file_bytes: number;
  actions: ProjectRepairAction[];
  warnings: string[];
}

export interface ProjectRepairResult {
  project_id: string;
  applied_at: string;
  applied_action_ids: string[];
  skipped_action_ids: string[];
  quarantined_paths: string[];
  created_paths: string[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) message = payload.detail;
    } catch {
      // Keep the HTTP fallback for non-JSON errors.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function previewProjectRepairs(
  projectId: string,
  minimumOrphanAgeSeconds: number,
) {
  const search = new URLSearchParams({
    minimum_orphan_age_seconds: String(minimumOrphanAgeSeconds),
  });
  return request<ProjectRepairPlan>(
    `/projects/${projectId}/integrity/repair-plan?${search}`,
  );
}

export function applyProjectRepairs(
  projectId: string,
  actionIds: string[],
  minimumOrphanAgeSeconds: number,
) {
  return request<ProjectRepairResult>(
    `/projects/${projectId}/integrity/repairs`,
    {
      method: "POST",
      body: JSON.stringify({
        action_ids: actionIds,
        minimum_orphan_age_seconds: minimumOrphanAgeSeconds,
      }),
    },
  );
}
