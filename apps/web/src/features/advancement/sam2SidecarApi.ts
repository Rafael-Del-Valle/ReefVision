import { getApiBaseUrl } from "../../runtime";

export interface Sam2SidecarRegistration {
  display_name: string;
  endpoint: string;
  token_env: string;
  timeout_seconds: number;
  notes?: string | null;
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

export async function registerSam2SidecarModel(
  projectId: string,
  payload: Sam2SidecarRegistration,
): Promise<Sam2SidecarModel> {
  const response = await fetch(
    `${getApiBaseUrl()}/projects/${projectId}/sam2-sidecar-models`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      // Keep the HTTP fallback for non-JSON errors.
    }
    throw new Error(message);
  }
  return (await response.json()) as Sam2SidecarModel;
}
