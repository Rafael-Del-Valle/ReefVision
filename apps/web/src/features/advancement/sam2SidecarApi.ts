import { getApiBaseUrl } from "../../runtime";

export interface Sam2SidecarConnectionPayload {
  endpoint: string;
  token_env: string;
  timeout_seconds: number;
}

export interface Sam2SidecarRegistration
  extends Sam2SidecarConnectionPayload {
  display_name: string;
  notes?: string | null;
}

export interface Sam2SidecarHealth {
  status: string;
  provider: string;
  model_version: string | null;
  device: string;
  endpoint: string;
  token_configured: boolean;
}

export interface Sam2SidecarModel {
  id: string;
  project_id: string;
  purpose: string;
  display_name: string;
  framework: string;
  task: string;
  provider_name: string;
  provider_version: string;
  managed_path: string;
  sha256: string;
}

async function request<T>(path: string, payload: Record<string, unknown>) {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    let message = `SAM 2 sidecar request failed with HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      // Keep the HTTP fallback for non-JSON errors.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function checkSam2SidecarHealth(
  payload: Sam2SidecarConnectionPayload,
): Promise<Sam2SidecarHealth> {
  return request<Sam2SidecarHealth>("/sam2-sidecar/health", payload);
}

export function registerSam2SidecarModel(
  projectId: string,
  payload: Sam2SidecarRegistration,
): Promise<Sam2SidecarModel> {
  return request<Sam2SidecarModel>(
    `/projects/${projectId}/sam2-sidecar-models`,
    payload,
  );
}
