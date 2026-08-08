import { getApiBaseUrl } from "../../runtime";

export interface AdvancedProviderManifest {
  provider_id: string;
  display_name: string;
  maturity: string;
  execution_supported: boolean;
  supported_tasks: string[];
  prompt_fields_by_task: Record<string, string[]>;
  output_contracts_by_task: Record<string, string[]>;
  required_model_extensions: string[];
  required_packages: string[];
  recommended_devices: string[];
  known_limitations: string[];
  integration_notes: string[];
}

export interface AdvancedProviderPreflight {
  provider_id: string;
  task: string;
  ready: boolean;
  execution_supported: boolean;
  availability_status: string;
  blockers: string[];
  warnings: string[];
  required_prompt_fields: string[];
  provided_prompt_fields: string[];
  missing_prompt_fields: string[];
  output_contract: string[];
  selected_model_id: string | null;
  selected_device: string;
}

export interface AdvancedProviderModel {
  id: string;
  project_id: string;
  purpose: string;
  display_name: string;
  source_filename: string;
  sha256: string;
  provider_name: string;
  provider_version: string;
  framework: string;
  task: string;
  metadata_json: Record<string, unknown>;
}

export interface AdvancedProviderImage {
  id: string;
  original_filename: string;
  width_px: number;
  height_px: number;
  annotation_status: string;
}

export interface AdvancedProviderJob {
  id: string;
  project_id: string | null;
  job_type: string;
  status: string;
  progress_current: number;
  progress_total: number;
  request_json: Record<string, unknown>;
  result_json: Record<string, unknown>;
  error_message: string | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData;
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers: {
      ...(init?.body && !isFormData ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = `Provider request failed with HTTP ${response.status}`;
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

export function getAdvancedProviderManifests(
  signal?: AbortSignal,
): Promise<AdvancedProviderManifest[]> {
  return request<AdvancedProviderManifest[]>("/advanced-providers/manifests", {
    signal,
  });
}

export function getAdvancedProviderModels(
  projectId: string,
  signal?: AbortSignal,
): Promise<AdvancedProviderModel[]> {
  return request<AdvancedProviderModel[]>(
    `/projects/${encodeURIComponent(projectId)}/models`,
    { signal },
  );
}

export async function getAdvancedProviderImages(
  projectId: string,
  signal?: AbortSignal,
): Promise<AdvancedProviderImage[]> {
  const page = await request<{
    items: AdvancedProviderImage[];
    pages: number;
  }>(`/projects/${encodeURIComponent(projectId)}/images?page=1&page_size=100`, {
    signal,
  });
  return page.items;
}

export function registerAdvancedProviderBundle(
  projectId: string,
  providerId: "sam2" | "depth_anything_v2",
  file: File,
  displayName?: string,
): Promise<AdvancedProviderModel> {
  const form = new FormData();
  form.append("file", file);
  form.append("purpose", providerId === "sam2" ? "assist" : "depth");
  form.append("provider_name", providerId);
  if (displayName?.trim()) form.append("display_name", displayName.trim());
  return request<AdvancedProviderModel>(
    `/projects/${encodeURIComponent(projectId)}/models/register`,
    { method: "POST", body: form },
  );
}

export function preflightAdvancedProvider(
  projectId: string,
  providerId: string,
  payload: {
    task: string;
    device: string;
    model_id?: string | null;
    prompt_fields: Record<string, unknown>;
  },
): Promise<AdvancedProviderPreflight> {
  return request<AdvancedProviderPreflight>(
    `/projects/${encodeURIComponent(projectId)}/advanced-providers/${encodeURIComponent(providerId)}/preflight`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function createDepthAnythingJob(
  projectId: string,
  payload: { model_id: string; image_ids: string[]; device: string },
): Promise<AdvancedProviderJob> {
  return request<AdvancedProviderJob>(
    `/projects/${encodeURIComponent(projectId)}/advanced-providers/depth-anything-v2/jobs`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function getAdvancedProviderJob(
  jobId: string,
  signal?: AbortSignal,
): Promise<AdvancedProviderJob> {
  return request<AdvancedProviderJob>(`/jobs/${encodeURIComponent(jobId)}`, {
    signal,
  });
}

export function cancelAdvancedProviderJob(
  jobId: string,
): Promise<AdvancedProviderJob> {
  return request<AdvancedProviderJob>(`/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
}
