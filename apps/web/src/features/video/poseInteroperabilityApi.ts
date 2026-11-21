import { request } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";

export type PoseInteroperabilityFormat =
  "nwb" | "coco" | "dlc_csv" | "ultralytics_pose";

interface PoseInteroperabilityRuntime {
  available: boolean;
  required_version: string;
  installed_version: string | null;
  reason: string | null;
}

export function getPoseInteroperabilityRuntime(signal?: AbortSignal) {
  return request<PoseInteroperabilityRuntime>(
    "/pose-interoperability/runtime",
    {
      signal,
    },
  );
}

export function poseInteroperabilityExportUrl(
  videoId: string,
  format: PoseInteroperabilityFormat,
  includeUnreviewed = false,
): string {
  const query = new URLSearchParams({ format });
  if (includeUnreviewed) query.set("include_unreviewed", "true");
  return `${getApiBaseUrl()}/videos/${encodeURIComponent(
    videoId,
  )}/pose-interoperability/export?${query.toString()}`;
}

export interface PoseInteroperabilityImportResponse {
  schema_version: "pose-interoperability-import-0001";
  video_id: string;
  format: PoseInteroperabilityFormat;
  created_track_ids: string[];
  track_count: number;
  keyframe_count: number;
  pose_schema_id: string;
  pose_schema_revision: number;
  used_reefvision_provenance: boolean;
  warnings: string[];
}

export async function importPoseInteroperability(
  videoId: string,
  format: PoseInteroperabilityFormat,
  file: File,
  labelClassId: string,
  confirmFrameMapping: boolean,
): Promise<PoseInteroperabilityImportResponse> {
  const query = new URLSearchParams({
    format,
    label_class_id: labelClassId,
    confirm_frame_mapping: confirmFrameMapping ? "true" : "false",
  });
  const body = new FormData();
  body.append("file", file);
  const response = await fetch(
    `${getApiBaseUrl()}/videos/${encodeURIComponent(
      videoId,
    )}/pose-interoperability/import?${query.toString()}`,
    {
      method: "POST",
      body,
    },
  );
  if (!response.ok) {
    let message = `Pose interoperability import failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string") message = payload.detail;
    } catch {
      // Keep the HTTP fallback.
    }
    throw new Error(message);
  }
  return (await response.json()) as PoseInteroperabilityImportResponse;
}
