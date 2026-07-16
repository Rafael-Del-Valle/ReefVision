import { getApiBaseUrl } from "../../runtime";

export interface MaskMeasurementResponse {
  mask_annotation_id: string;
  image_id: string;
  label_class_id: string | null;
  geometry_kind: string;
  area_pixels: number;
  perimeter_pixels: number;
  centroid_x: number;
  centroid_y: number;
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
  contained_box_count: number;
  contained_box_density_per_1000_pixels: number;
}

export async function getMaskMeasurements(
  maskAnnotationId: string,
  signal?: AbortSignal,
): Promise<MaskMeasurementResponse> {
  const response = await fetch(
    `${getApiBaseUrl()}/mask-annotations/${encodeURIComponent(maskAnnotationId)}/measurements`,
    { signal },
  );
  if (!response.ok) {
    let message = `Mask measurement request failed with HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      // Keep the HTTP fallback for non-JSON failures.
    }
    throw new Error(message);
  }
  return (await response.json()) as MaskMeasurementResponse;
}
