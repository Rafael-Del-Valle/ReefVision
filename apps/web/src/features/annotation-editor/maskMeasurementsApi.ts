import { getApiBaseUrl } from "../../runtime";

export interface MeasurementPoint {
  x: number;
  y: number;
}

export interface CalibrationCameraSignature {
  width_px?: number | null;
  height_px?: number | null;
  camera_make?: string | null;
  camera_model?: string | null;
  lens_model?: string | null;
  focal_length_mm?: number | null;
  capture_distance?: number | null;
  setup_notes?: string | null;
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
  confidence: number | null;
  detector: string | null;
  profile_name: string | null;
  profile_source_image_id: string | null;
  camera_signature: CalibrationCameraSignature | null;
  perspective_homography: number[][] | null;
  reference_plane_only: boolean;
}

export interface MeasurementCalibrationUpdate {
  distance_per_pixel: number;
  unit: string;
  source: string;
  reference_length?: number | null;
  reference_pixel_length?: number | null;
  default_depth?: number | null;
  notes?: string | null;
  confidence?: number | null;
  detector?: string | null;
  profile_name?: string | null;
  profile_source_image_id?: string | null;
  camera_signature?: CalibrationCameraSignature | null;
  perspective_homography?: number[][] | null;
  reference_plane_only?: boolean;
}

export interface CalibrationRoi {
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
}

export interface RulerCalibrationDetectRequest {
  roi?: CalibrationRoi | null;
  orientation?: "auto" | "horizontal" | "vertical";
}

export interface RulerCalibrationCandidate {
  image_id: string;
  method: "automatic_ruler";
  orientation: "horizontal" | "vertical";
  roi: CalibrationRoi;
  base_interval_pixels: number;
  major_interval_pixels: number | null;
  tick_positions_pixels: number[];
  interval_count: number;
  interval_coefficient_of_variation: number;
  confidence: number;
  unit_inferred: false;
  reference_length_required: true;
  warnings: string[];
}

export interface ScaleBarCalibrationDetectRequest {
  roi?: CalibrationRoi | null;
  orientation?: "auto" | "horizontal" | "vertical";
}

export interface ScaleBarCalibrationCandidate {
  image_id: string;
  method: "automatic_scale_bar";
  orientation: "horizontal" | "vertical";
  roi: CalibrationRoi;
  bar_start_pixels: [number, number];
  bar_end_pixels: [number, number];
  bar_length_pixels: number;
  bar_thickness_pixels: number;
  polarity: "dark" | "light";
  continuity_score: number;
  contrast_score: number;
  confidence: number;
  label_text: string | null;
  unit_inferred: false;
  reference_length_required: true;
  warnings: string[];
}

export interface MarkerCalibrationDetectRequest {
  kind: "aruco" | "charuco";
  unit: string;
  dictionary?: string;
  marker_length: number;
  marker_id?: number | null;
  charuco_squares_x?: number | null;
  charuco_squares_y?: number | null;
  charuco_square_length?: number | null;
}

export interface MarkerCalibrationCandidate {
  image_id: string;
  method: "aruco" | "charuco";
  marker_id: number | null;
  detected_corner_count: number;
  confidence: number;
  calibration: MeasurementCalibrationUpdate;
  reference_plane_only: true;
  corners_pixels: number[][];
  warnings: string[];
}

export interface CalibrationProfile {
  project_id: string;
  source_image_id: string;
  profile_name: string;
  unit: string;
  distance_per_pixel: number;
  width_px: number;
  height_px: number;
  source: string;
  confidence: number | null;
  camera_signature: CalibrationCameraSignature | null;
  notes: string | null;
}

export interface ApplyCalibrationProfileRequest {
  source_image_id: string;
  confirm_same_setup: boolean;
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
  perspective_corrected: boolean;
  calibration_source: string | null;
  calibration_confidence: number | null;
  calibration_profile_name: string | null;
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

export async function detectRulerCalibration(
  imageId: string,
  payload: RulerCalibrationDetectRequest,
): Promise<RulerCalibrationCandidate> {
  const response = await fetch(
    `${getApiBaseUrl()}/images/${encodeURIComponent(imageId)}/measurement-calibration/ruler-detect`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    throw await apiError(response, "Automatic ruler detection failed");
  }
  return (await response.json()) as RulerCalibrationCandidate;
}

export async function detectScaleBarCalibration(
  imageId: string,
  payload: ScaleBarCalibrationDetectRequest,
): Promise<ScaleBarCalibrationCandidate> {
  const response = await fetch(
    `${getApiBaseUrl()}/images/${encodeURIComponent(imageId)}/measurement-calibration/scale-bar-detect`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    throw await apiError(response, "Automatic scale-bar detection failed");
  }
  return (await response.json()) as ScaleBarCalibrationCandidate;
}

export async function detectMarkerCalibration(
  imageId: string,
  payload: MarkerCalibrationDetectRequest,
): Promise<MarkerCalibrationCandidate> {
  const response = await fetch(
    `${getApiBaseUrl()}/images/${encodeURIComponent(imageId)}/measurement-calibration/marker-detect`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    throw await apiError(response, "Marker calibration detection failed");
  }
  return (await response.json()) as MarkerCalibrationCandidate;
}

export async function getMeasurementCalibrationProfiles(
  projectId: string,
  signal?: AbortSignal,
): Promise<CalibrationProfile[]> {
  const response = await fetch(
    `${getApiBaseUrl()}/projects/${encodeURIComponent(projectId)}/measurement-calibration-profiles`,
    { signal },
  );
  if (!response.ok) {
    throw await apiError(response, "Calibration profile request failed");
  }
  return (await response.json()) as CalibrationProfile[];
}

export async function applyMeasurementCalibrationProfile(
  imageId: string,
  payload: ApplyCalibrationProfileRequest,
): Promise<MeasurementCalibration> {
  const response = await fetch(
    `${getApiBaseUrl()}/images/${encodeURIComponent(imageId)}/measurement-calibration/apply-profile`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    throw await apiError(response, "Calibration profile application failed");
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

export interface ScaleLabelOcrCandidate {
  image_id: string;
  raw_text: string;
  parsed_value: number | null;
  parsed_unit: string | null;
  normalized_unit: string | null;
  roi: { x_min: number; y_min: number; x_max: number; y_max: number };
  confidence: number;
  confidence_kind: string;
  model_id: string;
  model_revision: string;
  warnings: string[];
  requires_researcher_confirmation: boolean;
}

export async function detectScaleLabelOcr(
  imageId: string,
  payload: {
    roi?: { x_min: number; y_min: number; x_max: number; y_max: number } | null;
    allow_model_download?: boolean;
  },
): Promise<ScaleLabelOcrCandidate> {
  const response = await fetch(
    `${getApiBaseUrl()}/images/${encodeURIComponent(imageId)}/scale-label-ocr`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    let message = `Scale label OCR failed with HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      // Preserve the HTTP fallback.
    }
    throw new Error(message);
  }
  return (await response.json()) as ScaleLabelOcrCandidate;
}
