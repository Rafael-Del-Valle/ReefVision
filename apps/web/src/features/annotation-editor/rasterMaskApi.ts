import { getApiBaseUrl } from "../../runtime";
import type { ProjectImage } from "../../api/client";
import type { MaskAnnotationRecord, Point } from "./types";

export type RasterEditMode = "paint" | "erase";

export interface RasterMaskEditPayload {
  base_revision: number;
  mask_annotation_id?: string | null;
  label_class_id: string;
  mode: RasterEditMode;
  brush_radius: number;
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
