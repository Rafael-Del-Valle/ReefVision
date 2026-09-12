import { getApiBaseUrl } from "../../runtime";
import type { ProjectImage } from "../../api/client";
import type { MaskAnnotationRecord, Point } from "./types";

export type RasterEditMode = "paint" | "erase" | "fill";

export interface RasterMaskEditPayload {
  base_revision: number;
  mask_annotation_id?: string | null;
  label_class_id: string;
  mode: RasterEditMode;
  brush_radius: number;
  fill_tolerance?: number;
  strokes: Array<{ points: Point[] }>;
}

export interface RasterMaskEditResponse {
  image: ProjectImage;
  mask_annotation: MaskAnnotationRecord;
}

export interface RasterMaskContentReference {
  id: string;
  revision?: number;
}

export async function generatePolygonFill(
  imageId: string,
  payload: { seed: Point; tolerance: number },
  signal?: AbortSignal,
): Promise<{ points: Point[] }> {
  const response = await fetch(
    `${getApiBaseUrl()}/images/${encodeURIComponent(imageId)}/polygon-fill`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    },
  );
  if (!response.ok) {
    let message = `Polygon Fill failed with HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      /* Preserve the HTTP error for non-JSON failures. */
    }
    throw new Error(message);
  }
  return (await response.json()) as { points: Point[] };
}

export async function editRasterMask(
  imageId: string,
  payload: RasterMaskEditPayload,
): Promise<RasterMaskEditResponse> {
  const response = await fetch(
    `${getApiBaseUrl()}/images/${imageId}/raster-mask-edits`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    let message = `Raster mask edit failed with HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      // Keep the HTTP fallback for non-JSON failures.
    }
    throw new Error(message);
  }
  return (await response.json()) as RasterMaskEditResponse;
}

export function rasterMaskContentUrl(mask: RasterMaskContentReference): string {
  const revision = mask.revision ?? 0;
  return `${getApiBaseUrl()}/mask-annotations/${encodeURIComponent(mask.id)}/content?revision=${revision}`;
}
