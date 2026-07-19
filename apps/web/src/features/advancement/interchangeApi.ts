import { getApiBaseUrl } from "../../runtime";

export type InterchangeFormat =
  | "coco_detection"
  | "coco_instance"
  | "coco_panoptic"
  | "cvat"
  | "labelme"
  | "roboflow_coco"
  | "roboflow_yolo";

export type ClassConflictPolicy = "error" | "skip" | "merge";
export type ExistingAnnotationPolicy =
  | "append"
  | "skip_image"
  | "replace_imported"
  | "error";

export interface InterchangeRequest {
  format: InterchangeFormat;
  document: Record<string, unknown>;
  class_mapping: Record<string, string>;
  create_missing_classes: boolean;
  class_conflict_policy: ClassConflictPolicy;
  existing_annotation_policy: ExistingAnnotationPolicy;
  source_name?: string | null;
}

export interface InterchangeMapping {
  source_key: string;
  source_name: string;
  target_class_id: string | null;
  target_class_name: string | null;
  resolution:
    | "matched"
    | "explicit"
    | "create"
    | "skip"
    | "conflict"
    | "unmapped";
  message: string | null;
}

export interface InterchangeImageMatch {
  source_key: string;
  source_filename: string;
  target_image_id: string | null;
  target_filename: string | null;
  status: "matched" | "missing" | "ambiguous" | "dimension_mismatch";
  annotation_count: number;
  message: string | null;
}

export interface InterchangePreview {
  project_id: string;
  format: InterchangeFormat;
  preview_checksum: string;
  valid: boolean;
  source_category_count: number;
  matched_category_count: number;
  created_category_count: number;
  skipped_category_count: number;
  source_image_count: number;
  matched_image_count: number;
  missing_image_count: number;
  source_annotation_count: number;
  importable_box_count: number;
  importable_mask_count: number;
  mappings: InterchangeMapping[];
  images: InterchangeImageMatch[];
  warnings: string[];
  blockers: string[];
}

export interface InterchangeApplyResult {
  project_id: string;
  format: InterchangeFormat;
  preview_checksum: string;
  created_class_ids: string[];
  created_annotation_ids: string[];
  created_mask_annotation_ids: string[];
  skipped_annotation_count: number;
  affected_image_ids: string[];
  warnings: string[];
}

export interface InterchangeExportResult {
  project_id: string;
  export_id: string;
  format: InterchangeFormat;
  archive_path: string;
  manifest_path: string;
  archive_sha256: string;
  archive_size_bytes: number;
  image_count: number;
  box_annotation_count: number;
  mask_annotation_count: number;
  warnings: string[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${getApiBaseUrl()}${path}`, { ...init, headers });
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string") message = payload.detail;
    } catch {
      // Keep the HTTP fallback for non-JSON errors.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function previewInterchange(
  projectId: string,
  payload: InterchangeRequest,
): Promise<InterchangePreview> {
  return request<InterchangePreview>(
    `/projects/${projectId}/interchange/preview`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function applyInterchange(
  projectId: string,
  payload: InterchangeRequest & { preview_checksum: string },
): Promise<InterchangeApplyResult> {
  return request<InterchangeApplyResult>(
    `/projects/${projectId}/interchange/apply`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function exportInterchange(
  projectId: string,
  payload: {
    format: InterchangeFormat;
    image_ids: string[];
    include_images: boolean;
    include_boxes: boolean;
    include_masks: boolean;
    include_archived_classes: boolean;
  },
): Promise<InterchangeExportResult> {
  return request<InterchangeExportResult>(
    `/projects/${projectId}/interchange/export`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}
