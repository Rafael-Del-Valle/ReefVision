import { getApiBaseUrl } from "../../runtime";

export type HeatmapKind =
  "reviewed_boxes" | "verified_masks" | "pending_predictions";

export interface HeatmapLayer {
  kind: HeatmapKind;
  counting_method: "bounding_rectangle_centroid";
  object_count: number;
  max_cell_count: number;
  counts: number[][];
  normalized: number[][];
}

export interface ScientificHeatmap {
  schema_version: "1.1.0";
  algorithm: "reefvision-centroid-grid-1";
  project_id: string;
  image_id: string;
  image_sha256: string;
  annotation_revision: number;
  annotation_status: string;
  width_px: number;
  height_px: number;
  columns: number;
  rows: number;
  label_class_id: string | null;
  layers: HeatmapLayer[];
  source_sha256: string;
  content_sha256: string;
  methodological_notes: string[];
}

export async function getScientificHeatmap(
  projectId: string,
  imageId: string,
  columns: number,
  rows: number,
  labelClassId: string,
  signal?: AbortSignal,
): Promise<ScientificHeatmap> {
  const endpoint =
    `${getApiBaseUrl()}/projects/${encodeURIComponent(projectId)}` +
    `/images/${encodeURIComponent(imageId)}/scientific-heatmaps`;

  const params = new URLSearchParams({
    columns: String(columns),
    rows: String(rows),
  });

  if (labelClassId) {
    params.set("label_class_id", labelClassId);
  }

  let response: Response;
  try {
    response = await fetch(`${endpoint}?${params}`, { signal });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error("Could not reach the ReefVision heatmap API.");
  }

  if (!response.ok) {
    let message = `Heatmap request failed: HTTP ${response.status}`;
    try {
      const body: unknown = await response.json();
      if (
        body !== null &&
        typeof body === "object" &&
        "detail" in body &&
        typeof body.detail === "string"
      ) {
        message = body.detail;
      }
    } catch {
      // Keep the HTTP error for non-JSON responses.
    }
    throw new Error(message);
  }

  return (await response.json()) as ScientificHeatmap;
}
