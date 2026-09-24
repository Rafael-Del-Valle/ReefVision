import { getApiBaseUrl } from "../../runtime";

export type GeographicExportFormat = "geojson" | "csv";

export function videoGeographicExportUrl(
  videoId: string,
  format: GeographicExportFormat,
  trackId?: string | null,
): string {
  const query = new URLSearchParams({ format });

  const normalizedTrackId = trackId?.trim();

  if (normalizedTrackId) {
    query.set("track_id", normalizedTrackId);
  }

  return `${getApiBaseUrl()}/videos/${encodeURIComponent(
    videoId,
  )}/geographic-export?${query.toString()}`;
}
