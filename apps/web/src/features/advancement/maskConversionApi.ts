import { getApiBaseUrl } from "../../runtime";

export interface GeometryPoint {
  x: number;
  y: number;
}

export interface PolygonGeometry {
  outer: GeometryPoint[];
  holes: GeometryPoint[][];
}

export interface MaskRle {
  width: number;
  height: number;
  counts: number[];
  order: "row_major" | "coco_fortran";
}

export interface MaskConversionQuality {
  foreground_pixels: number;
  component_count: number;
  hole_count: number;
  touches_boundary: boolean;
  bounds: [number, number, number, number] | null;
}

export interface RasterToPolygonResult {
  polygons: PolygonGeometry[];
  cleaned_raster: MaskRle;
  quality: MaskConversionQuality;
  round_trip_iou: number;
  preview_png_base64: string;
  warnings: string[];
}

export interface PolygonToRasterResult {
  raster: MaskRle;
  quality: MaskConversionQuality;
  preview_png_base64: string;
  warnings: string[];
}

export interface PolygonRepairResult {
  polygons: PolygonGeometry[];
  original_self_intersection_count: number;
  repaired_self_intersection_count: number;
  quality: MaskConversionQuality;
  round_trip_iou: number;
  preview_png_base64: string;
  warnings: string[];
}

async function request<T>(path: string, payload: object): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      // Keep the HTTP fallback for non-JSON responses.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function rasterToPolygons(payload: object) {
  return request<RasterToPolygonResult>(
    "/geometry/masks/raster-to-polygons",
    payload,
  );
}

export function polygonsToRaster(payload: object) {
  return request<PolygonToRasterResult>(
    "/geometry/masks/polygons-to-raster",
    payload,
  );
}

export function repairPolygons(payload: object) {
  return request<PolygonRepairResult>(
    "/geometry/polygons/repair-rasterized",
    payload,
  );
}
