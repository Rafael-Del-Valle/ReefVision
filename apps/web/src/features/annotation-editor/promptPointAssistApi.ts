import { getApiBaseUrl } from "../../runtime";

export class PromptPointAssistApiError extends Error {}

export interface PromptAssistCandidateBox {
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
}

export interface PromptAssistSession {
  session_id: string;
  project_id: string;
  image_id: string;
  model_id: string;
  model_display_name: string;
  provider_name: string;
  provider_version: string;
  created_at: string;
  last_used_at: string;
  expires_at: string;
  add_stroke_count: number;
  subtract_stroke_count: number;
  positive_point_count: number;
  negative_point_count: number;
  brush_radius: number | null;
  source_prediction_id: string | null;
  prompt_type: string | null;
  candidate_box: PromptAssistCandidateBox | null;
  candidate_mask_png_base64: string | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers,
  });
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") message = payload.detail;
      if (
        payload.detail &&
        typeof payload.detail === "object" &&
        ("message" in payload.detail || "reason" in payload.detail)
      ) {
        const detail = payload.detail as {
          message?: unknown;
          reason?: unknown;
        };
        if (typeof detail.message === "string") message = detail.message;
        else if (typeof detail.reason === "string") message = detail.reason;
      }
    } catch {
      // Keep the HTTP fallback for non-JSON failures.
    }
    throw new PromptPointAssistApiError(message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function createPromptAssistSession(
  imageId: string,
  payload: { model_id: string; device: string },
  signal?: AbortSignal,
) {
  return request<PromptAssistSession>(`/images/${imageId}/assist-sessions`, {
    method: "POST",
    body: JSON.stringify(payload),
    signal,
  });
}

export function applyPromptAssistPoints(
  sessionId: string,
  payload: {
    positive_points: Array<{ x: number; y: number }>;
    negative_points: Array<{ x: number; y: number }>;
    context_box?: PromptAssistCandidateBox | null;
  },
  signal?: AbortSignal,
) {
  return request<PromptAssistSession>(`/assist-sessions/${sessionId}/points`, {
    method: "POST",
    body: JSON.stringify(payload),
    signal,
  });
}

export function acceptPromptAssistSession(
  sessionId: string,
  labelClassId: string,
  outputKind: "raster_mask" | "polygon",
) {
  return request<{
    session_id: string;
    annotation: Record<string, unknown>;
    mask_annotation?: Record<string, unknown> | null;
  }>(`/assist-sessions/${sessionId}/accept`, {
    method: "POST",
    body: JSON.stringify({
      label_class_id: labelClassId,
      output_kind: outputKind,
    }),
  });
}

export function deletePromptAssistSession(sessionId: string) {
  return request<void>(`/assist-sessions/${sessionId}`, { method: "DELETE" });
}
