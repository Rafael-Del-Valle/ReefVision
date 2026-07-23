import { getApiBaseUrl } from "../../runtime";

export interface Sam3SidecarRegistrationPayload {
  display_name: string;
  endpoint: string;
  concept_prompt: string;
  label_class_id: string;
  score_threshold: number;
  token_env: string;
  notes?: string | null;
}

export interface Sam3SidecarModel {
  id: string;
  project_id: string;
  purpose: string;
  display_name: string;
  managed_path: string;
  sha256: string;
  framework: string;
  task: string;
  provider_name: string;
  provider_version: string;
  class_map_json: Record<string, unknown>;
  metadata_json: Record<string, unknown>;
}

export async function registerSam3SidecarModel(
  projectId: string,
  payload: Sam3SidecarRegistrationPayload,
): Promise<Sam3SidecarModel> {
  const response = await fetch(
    `${getApiBaseUrl()}/projects/${projectId}/sam3-sidecar-models`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    let message = `SAM 3 registration failed with HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      // Preserve the status fallback for non-JSON responses.
    }
    throw new Error(message);
  }
  return (await response.json()) as Sam3SidecarModel;
}
