import { getApiBaseUrl } from "../../runtime";

export interface MeasurementPoint {
  x: number;
  y: number;
}

export interface MeasurementCalibration {
  image_id: string;
  calibrated: boolean;
  distance_per_pixel: number;
  unit: string;
  source: string;
  reference_length: number | null;
  reference_pixel_length: number | null;
  default_depth: number | null;
  notes: string | null;
}

export interface MeasurementCalibrationUpdate {
  distance_per_pixel: number;
  unit: string;
  source: string;
  reference_length?: number | null;
  reference_pixel_length?: number | null;
  default_depth?: number | null;
  notes?: string | null;
}

export type SurfaceModelKind = "none" | "extruded" | "cylindrical_centerline";

export interface MaskMeasurementProfile {
  mask_annotation_id: string;
  image_id: string;
  revision: number;
  centerline_points: MeasurementPoint[];
  centerline_length_pixels: number;
  surface_model: SurfaceModelKind;
  depth_value: number | null;
  diameter_value: number | null;
  notes: string | null;
}

export interface MaskMeasurementProfileUpdate {
  base_revision: number;
  centerline_points: MeasurementPoint[];
  surface_model: SurfaceModelKind;
  depth_value?: number | null;
  diameter_value?: number | null;
  notes?: string | null;
}

export interface MeasurementFilters {
  label_class_ids?: string[];
  scientific_names?: string[];
  state_names?: string[];
}

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
  filters: {
    label_class_ids: string[];
    scientific_names: string[];
    state_names: string[];
  };
  calibrated: boolean;
  physical_unit: string | null;
  distance_per_pixel: number | null;
  area_physical: number | null;
  perimeter_physical: number | null;
  centroid_x_physical: number | null;
  centroid_y_physical: number | null;
  contained_box_density_per_square_unit: number | null;
  centerline_points: MeasurementPoint[];
  total_linear_extension_pixels: number;
  total_linear_extension_physical: number | null;
  surface_area_model: SurfaceModelKind;
  surface_area_physical: number | null;
  surface_area_assumptions: string[];
}

async function apiError(response: Response, fallback: string): Promise<Error> {
  let message = `${fallback} with HTTP ${response.status}`;
  try {
    const body = (await response.json()) as { detail?: string };
    if (body.detail) message = body.detail;
  } catch {
    // Keep the HTTP fallback for non-JSON failures.
  }
  return new Error(message);
}

export async function getMaskMeasurements(
  maskAnnotationId: string,
  filters: MeasurementFilters = {},
  signal?: AbortSignal,
): Promise<MaskMeasurementResponse> {
  const query = new URLSearchParams();
  for (const value of filters.label_class_ids ?? []) {
    query.append("label_class_id", value);
  }
  for (const value of filters.scientific_names ?? []) {
    query.append("scientific_name", value);
  }
  for (const value of filters.state_names ?? []) {
    query.append("state_name", value);
  }
  const encodedQuery = query.toString();
  const suffix = encodedQuery ? `?${encodedQuery}` : "";
  const response = await fetch(
    `${getApiBaseUrl()}/mask-annotations/${encodeURIComponent(maskAnnotationId)}/measurements${suffix}`,
    { signal },
  );
  if (!response.ok) {
    throw await apiError(response, "Mask measurement request failed");
  }
  return (await response.json()) as MaskMeasurementResponse;
}

export async function getMeasurementCalibration(
  imageId: string,
  signal?: AbortSignal,
): Promise<MeasurementCalibration | null> {
  const response = await fetch(
    `${getApiBaseUrl()}/images/${encodeURIComponent(imageId)}/measurement-calibration`,
    { signal },
  );
  if (!response.ok) {
    throw await apiError(response, "Calibration request failed");
  }
  return (await response.json()) as MeasurementCalibration | null;
}

export async function updateMeasurementCalibration(
  imageId: string,
  payload: MeasurementCalibrationUpdate,
): Promise<MeasurementCalibration> {
  const response = await fetch(
    `${getApiBaseUrl()}/images/${encodeURIComponent(imageId)}/measurement-calibration`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    throw await apiError(response, "Calibration update failed");
  }
  return (await response.json()) as MeasurementCalibration;
}

export async function clearMeasurementCalibration(
  imageId: string,
): Promise<void> {
  const response = await fetch(
    `${getApiBaseUrl()}/images/${encodeURIComponent(imageId)}/measurement-calibration`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    throw await apiError(response, "Calibration removal failed");
  }
}

export async function getMaskMeasurementProfile(
  maskAnnotationId: string,
  signal?: AbortSignal,
): Promise<MaskMeasurementProfile> {
  const response = await fetch(
    `${getApiBaseUrl()}/mask-annotations/${encodeURIComponent(maskAnnotationId)}/measurement-profile`,
    { signal },
  );
  if (!response.ok) {
    throw await apiError(response, "Measurement profile request failed");
  }
  return (await response.json()) as MaskMeasurementProfile;
}

export async function updateMaskMeasurementProfile(
  maskAnnotationId: string,
  payload: MaskMeasurementProfileUpdate,
): Promise<MaskMeasurementProfile> {
  const response = await fetch(
    `${getApiBaseUrl()}/mask-annotations/${encodeURIComponent(maskAnnotationId)}/measurement-profile`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    throw await apiError(response, "Measurement profile update failed");
  }
  return (await response.json()) as MaskMeasurementProfile;
}

export function measurementExportUrl(
  projectId: string,
  format: "csv" | "numpy",
): string {
  return `${getApiBaseUrl()}/projects/${encodeURIComponent(projectId)}/measurement-export?format=${format}`;
}
