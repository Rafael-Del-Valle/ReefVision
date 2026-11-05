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

export interface AnnotationClassComparison {
  count_a: number;
  count_b: number;
  signed_count_difference_b_minus_a: number;
  absolute_count_difference: number;
  reference_relative_percent_difference: number | null;
  reference_relative_percent_reason: string | null;
  matched_count: number;
  mean_matched_iou: number | null;
  unmatched_a_ids: string[];
  unmatched_b_ids: string[];
  false_positive_ids: string[] | null;
  false_negative_ids: string[] | null;
}
export interface AnnotationComparisonPreview {
  result_id?: string;
  algorithm: "reefvision.class-aware-box-comparison.v1";
  source_a_sha256: string;
  source_b_sha256: string;
  content_sha256: string;
  per_class: Record<string, AnnotationClassComparison>;
  methodological_notes: string[];
}
export async function previewAnnotationComparison(
  projectId: string,
  imageId: string,
  predictionJobId: string,
  referenceSide: "a" | "b" | null,
): Promise<AnnotationComparisonPreview> {
  const endpoint =
    `${getApiBaseUrl()}/projects/${encodeURIComponent(projectId)}` +
    "/annotation-comparisons/calculate";
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: `Annotation comparison ${new Date().toISOString()}`,
      image_id: imageId,
      source_a: { kind: "reviewed_boxes" },
      source_b: {
        kind: "prediction_job",
        prediction_job_id: predictionJobId,
      },
      reference_side: referenceSide,
      iou_threshold: 0.5,
    }),
  });
  if (!response.ok) {
    let message = `Comparison request failed: HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      // Preserve HTTP status for non-JSON responses.
    }
    throw new Error(message);
  }
  const saved = (await response.json()) as {
    result_id: string;
    comparison: AnnotationComparisonPreview;
  };
  return { ...saved.comparison, result_id: saved.result_id };
}
