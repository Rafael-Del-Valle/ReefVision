import { getApiBaseUrl } from "../../runtime";

export type PoseInteroperabilityFormat =
  "slp" | "nwb" | "coco" | "dlc_csv" | "ultralytics_pose";

export function poseInteroperabilityExportUrl(
  videoId: string,
  format: PoseInteroperabilityFormat,
): string {
  const query = new URLSearchParams({ format });
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
