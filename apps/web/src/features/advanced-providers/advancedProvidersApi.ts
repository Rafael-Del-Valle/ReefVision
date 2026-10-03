import { getApiBaseUrl } from "../../runtime";

export interface AdvancedProviderManifest {
  provider_id: string;
  display_name: string;
  maturity: string;
  execution_supported: boolean;
  execution_surface: "provider_lab" | "existing_workflow" | "blocked";
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
  execution_surface: "provider_lab" | "existing_workflow" | "blocked";
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
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

export function preflightAdvancedProvider(
  projectId: string,
  providerId: string,
  payload: {
    task: string;
    device: string;
    model_id?: string | null;
    allow_model_download?: boolean;
    prompt_fields: Record<string, unknown>;
  },
): Promise<AdvancedProviderPreflight> {
  return request<AdvancedProviderPreflight>(
    `/projects/${encodeURIComponent(projectId)}/advanced-providers/${encodeURIComponent(providerId)}/preflight`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export interface AdvancedProviderExecution {
  provider_id: string;
  task: string;
  status: string;
  model_id: string | null;
  model_revision: string | null;
  result: Record<string, unknown>;
  warnings: string[];
}

export interface AdvancedProviderImageOption {
  id: string;
  original_filename: string;
  width_px: number;
  height_px: number;
}

export async function listAdvancedProviderImages(
  projectId: string,
  signal?: AbortSignal,
): Promise<AdvancedProviderImageOption[]> {
  const page = await request<{
    items: AdvancedProviderImageOption[];
  }>(`/projects/${encodeURIComponent(projectId)}/images?page=1&page_size=100`, {
    signal,
  });
  return page.items;
}

export function executeAdvancedProvider(
  projectId: string,
  providerId: string,
  payload: {
    task: string;
    device: string;
    allow_model_download: boolean;
    prompt_fields: Record<string, unknown>;
  },
): Promise<AdvancedProviderExecution> {
  return request<AdvancedProviderExecution>(
    `/projects/${encodeURIComponent(projectId)}/advanced-providers/${encodeURIComponent(providerId)}/execute`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}
