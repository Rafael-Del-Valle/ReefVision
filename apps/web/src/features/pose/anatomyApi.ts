import { getApiBaseUrl } from "../../runtime";

export interface AnatomyLandmarkDefinition {
  id: string;
  name: string;
  description?: string | null;
  group?: string | null;
  repeat_group?: string | null;
  repeat_index?: number | null;
  symmetric_with?: string | null;
  required: boolean;
}

export interface AnatomySkeletonEdge {
  from_id: string;
  to_id: string;
}

export interface AnatomyRevisionPayload {
  landmarks: AnatomyLandmarkDefinition[];
  edges: AnatomySkeletonEdge[];
}

export interface AnatomySchemaRevision extends AnatomyRevisionPayload {
  id: string;
  name: string;
  revision: number;
  schema_version: string;
  groups: Array<{ name: string; count: number }>;
  expanded_labels: string[];
  keypoint_count: number;
  allows_repeated_labels: boolean;
  content_hash: string;
  legacy_projection: boolean;
  created_at: string;
}

async function anatomyRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let detail = `Request failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      detail = payload.detail ?? detail;
    } catch {
      // Keep the HTTP fallback when the server did not return JSON.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export function listAnatomySchemas(
  projectId: string,
  signal?: AbortSignal,
): Promise<AnatomySchemaRevision[]> {
  return anatomyRequest(
    `/projects/${encodeURIComponent(projectId)}/pose-schemas`,
    { signal },
  );
}

export function createAnatomySchema(
  projectId: string,
  payload: AnatomyRevisionPayload & { name: string },
): Promise<AnatomySchemaRevision> {
  return anatomyRequest(
    `/projects/${encodeURIComponent(projectId)}/pose-schemas`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function createAnatomyRevision(
  schemaId: string,
  payload: AnatomyRevisionPayload,
): Promise<AnatomySchemaRevision> {
  return anatomyRequest(
    `/pose-schemas/${encodeURIComponent(schemaId)}/revisions`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}
