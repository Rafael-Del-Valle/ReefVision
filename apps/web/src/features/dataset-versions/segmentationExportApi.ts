import { getApiBaseUrl } from "../../runtime";
import type { DatasetExportCreateResponse } from "../../api/client";

export type DatasetExportFormat =
  | "yolo_detection"
  | "yolo_segmentation"
  | "semantic_masks";

export async function createFormattedDatasetExport(
  versionId: string,
  format: DatasetExportFormat,
): Promise<DatasetExportCreateResponse> {
  const response = await fetch(
    `${getApiBaseUrl()}/dataset-versions/${versionId}/exports`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ format }),
    },
  );
  if (!response.ok) {
    let message = `Dataset export failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) message = payload.detail;
    } catch {
      // Keep the HTTP fallback for non-JSON failures.
    }
    throw new Error(message);
  }
  return (await response.json()) as DatasetExportCreateResponse;
}
