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
    prompt_fields: Record<string, unknown>;
  },
): Promise<AdvancedProviderPreflight> {
  return request<AdvancedProviderPreflight>(
    `/projects/${encodeURIComponent(projectId)}/advanced-providers/${encodeURIComponent(providerId)}/preflight`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}
