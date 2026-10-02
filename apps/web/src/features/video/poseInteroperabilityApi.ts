import { getApiBaseUrl } from "../../runtime";

export type PoseInteroperabilityFormat =
  | "slp"
  | "nwb"
  | "coco"
  | "dlc_csv"
  | "ultralytics_pose";

export function poseInteroperabilityExportUrl(
  videoId: string,
  format: PoseInteroperabilityFormat,
): string {
  const query = new URLSearchParams({ format });
  return `${getApiBaseUrl()}/videos/${encodeURIComponent(
    videoId,
  )}/pose-interoperability/export?${query.toString()}`;
}
