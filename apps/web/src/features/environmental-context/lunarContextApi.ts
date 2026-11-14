import { getApiBaseUrl } from "../../runtime";

export type LunarPhase =
  | "new_moon"
  | "waxing_crescent"
  | "first_quarter"
  | "waxing_gibbous"
  | "full_moon"
  | "waning_gibbous"
  | "last_quarter"
  | "waning_crescent";

export interface LunarContext {
  schema_version: "1.1.0";
  algorithm: "reefvision-low-precision-ecliptic-longitude-1";
  project_id: string;
  observed_at: string;
  phase: LunarPhase;
  phase_fraction: number;
  illuminated_fraction: number;
  approximate_lunar_age_days: number;
  reference_frame: "geocentric_approximate";
  computation: "offline_deterministic";
  content_sha256: string;
  methodological_notes: string[];
}

export async function calculateLunarContext(
  projectId: string,
  observedAt: string,
  signal?: AbortSignal,
): Promise<LunarContext> {
  let response: Response;
  try {
    response = await fetch(
      `${getApiBaseUrl()}/projects/${encodeURIComponent(projectId)}/environment/lunar-context`,
      {
        method: "POST",
        signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ observed_at: observedAt }),
      },
    );
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error("Could not reach the local ReefVision lunar context API.");
  }

  if (!response.ok) {
    let message = `Lunar context request failed (HTTP ${response.status}).`;
    try {
      const body: unknown = await response.json();
      if (
        body &&
        typeof body === "object" &&
        "detail" in body &&
        typeof body.detail === "string"
      ) {
        message = body.detail;
      }
    } catch {
      // Preserve HTTP status when the response is not JSON.
    }
    throw new Error(message);
  }
  return (await response.json()) as LunarContext;
}
