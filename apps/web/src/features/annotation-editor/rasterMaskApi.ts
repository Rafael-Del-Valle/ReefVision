import type { ProjectImage } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";
import type { MaskAnnotationRecord, Point } from "./types";

export type RasterEditMode = "paint" | "erase";

export interface RasterMaskEditPayload {
  base_revision: number;
  mask_annotation_id?: string | null;
  label_class_id: string;
  mode: RasterEditMode;
  brush_radius: number;
  strokes: Array<{ points: Point[] }>;
  auto_mask_enabled?: boolean;
  auto_mask_color_tolerance?: number;
  auto_mask_luminance_tolerance?: number;
  auto_mask_edge_sensitivity?: number;
  auto_mask_contiguous?: boolean;
  auto_mask_sample_radius?: number;
}

export interface RasterMaskCleanupPayload {
  base_revision: number;
  mask_annotation_id: string;
  remove_small_components: boolean;
  minimum_component_area: number;
  keep_largest_component: boolean;
  fill_holes: boolean;
  connectivity: 4 | 8;
}

export interface RasterMaskEditResponse {
  image: ProjectImage;
  mask_annotation: MaskAnnotationRecord;
}

export interface RasterMaskContentReference {
  id: string;
  revision?: number;
}

async function postRasterOperation(
  path: string,
  payload: RasterMaskEditPayload | RasterMaskCleanupPayload,
): Promise<RasterMaskEditResponse> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    let message = `Raster mask operation failed with HTTP ${response.status}`;
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

export function editRasterMask(
  imageId: string,
  payload: RasterMaskEditPayload,
): Promise<RasterMaskEditResponse> {
  return postRasterOperation(`/images/${imageId}/raster-mask-edits`, payload);
}

export function cleanupRasterMask(
  imageId: string,
  payload: RasterMaskCleanupPayload,
): Promise<RasterMaskEditResponse> {
  return postRasterOperation(`/images/${imageId}/raster-mask-cleanup`, payload);
}

export function rasterMaskContentUrl(mask: RasterMaskContentReference): string {
  const revision = mask.revision ?? 0;
  return `${getApiBaseUrl()}/mask-annotations/${encodeURIComponent(mask.id)}/content?revision=${revision}`;
}
