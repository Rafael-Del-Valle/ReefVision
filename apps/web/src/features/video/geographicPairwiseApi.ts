import { getApiBaseUrl } from "../../runtime";

export interface GeographicPairwiseMeasurement {
  content_sha256: string;
  distance_m: number;
  initial_bearing_deg: number | null;
  bearing_unavailable_reason: string | null;
  signed_time_delta_s: number | null;
  time_basis: "utc" | "same_video_frame_time" | "unavailable";
  distance_standard_uncertainty_m: number | null;
  bearing_standard_uncertainty_deg: number | null;
  uncertainty_method: string | null;
  uncertainty_unavailable_reason: string | null;
  methodological_notes: string[];
}

export interface GeographicPairwiseSaved {
  result_id: string;
  definition_id: string;
  result_sha256: string;
  measurement: GeographicPairwiseMeasurement;
}

export async function calculateGeographicPairwise(
  projectId: string,
  startObservationId: string,
  endObservationId: string,
): Promise<GeographicPairwiseSaved> {
  const endpoint =
    `${getApiBaseUrl()}/projects/${encodeURIComponent(projectId)}` +
    "/geographic-pairwise/calculate";
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: `Pairwise geographic measurement ${new Date().toISOString()}`,
      start_observation_id: startObservationId,
      end_observation_id: endObservationId,
    }),
  });
  if (!response.ok) {
    let message = `Pairwise geographic request failed: HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      // Preserve the HTTP status for non-JSON responses.
    }
    throw new Error(message);
  }
  return (await response.json()) as GeographicPairwiseSaved;
}

export function geographicPairwiseCsvUrl(
  projectId: string,
  resultId: string,
): string {
  return (
    `${getApiBaseUrl()}/projects/${encodeURIComponent(projectId)}` +
    `/geographic-pairwise/${encodeURIComponent(resultId)}/export.csv`
  );
}
