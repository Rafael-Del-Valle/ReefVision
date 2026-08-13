import { getApiBaseUrl } from "../../runtime";

export type VideoTrackExchangeFormat =
  | "reefvision_json"
  | "reefvision_csv"
  | "mot_csv";

export interface VideoTrackImportResult {
  schema_version: "video-track-import-0001";
  video_id: string;
  format: VideoTrackExchangeFormat;
  created_track_ids: string[];
  track_count: number;
  observation_count: number;
  warnings: string[];
}

export function videoTrackExportUrl(
  videoId: string,
  format: VideoTrackExchangeFormat,
): string {
  const query = new URLSearchParams({ format });
  return `${getApiBaseUrl()}/videos/${encodeURIComponent(videoId)}/tracks/export?${query.toString()}`;
}

export async function importVideoTracks(
  videoId: string,
  format: VideoTrackExchangeFormat,
  file: File,
  motLabelClassId?: string,
): Promise<VideoTrackImportResult> {
  const query = new URLSearchParams({ format });
  if (format === "mot_csv" && motLabelClassId) {
    query.set("mot_label_class_id", motLabelClassId);
  }
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(
    `${getApiBaseUrl()}/videos/${encodeURIComponent(videoId)}/tracks/import?${query.toString()}`,
    { method: "POST", body: form },
  );
  if (!response.ok) {
    let message = `Track import failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string") message = payload.detail;
    } catch {
      // Keep the HTTP fallback.
    }
    throw new Error(message);
  }
  return (await response.json()) as VideoTrackImportResult;
}
