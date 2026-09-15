import type { AnnotationRecord, AnnotationStatus } from "../../api/client";

export type EditorTool =
  | "select"
  | "pan"
  | "box"
  | "polygon"
  | "rotated_box"
  | "fill"
  | "smart_close";

export interface Point {
  x: number;
  y: number;
}

export interface EditorAnnotation {
  id: string;
  label_class_id: string;
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
}

export interface MaskAnnotationRecord {
  id: string;
  image_id: string;
  label_class_id: string | null;
  geometry_kind: string;
  mask_path: string | null;
  polygon_json: number[][] | null;
  x_min: number | null;
  y_min: number | null;
  x_max: number | null;
  y_max: number | null;
  area_pixels: number | null;
  source_type: string;
  provenance_json: Record<string, unknown> | null;
  status: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  revision: number;
}

export interface EditorMaskAnnotation {
  id: string;
  label_class_id: string | null;
  geometry_kind: "polygon" | "rotated_box" | "raster_mask" | string;
  points: Point[] | null;
  mask_path: string | null;
  x_min: number | null;
  y_min: number | null;
  x_max: number | null;
  y_max: number | null;
  area_pixels: number | null;
  source_type: string;
  persisted: boolean;
  revision?: number;
}

export interface AnnotationDocument {
  annotation_status: AnnotationStatus;
  annotations: EditorAnnotation[];
  maskAnnotations: EditorMaskAnnotation[];
  deletedMaskAnnotationIds: string[];
}

export interface AnnotationEditorState {
  baseRevision: number;
  documentVersion: number;
  lastCommittedVersion: number;
  document: AnnotationDocument;
  history: AnnotationDocument[];
  future: AnnotationDocument[];
  selectedIds: string[];
  selectedMaskIds: string[];
  activeClassId: string | null;
  hiddenClassIds: string[];
  tool: EditorTool;
  saveState: "idle" | "dirty" | "saving" | "saved" | "error" | "conflict";
  saveMessage: string | null;
}

export interface ImageSize {
  width: number;
  height: number;
}

export interface ViewportTransform {
  scale: number;
  offsetX: number;
  offsetY: number;
}

export type ResizeHandle = "nw" | "ne" | "sw" | "se";

export function toEditorAnnotation(
  annotation: AnnotationRecord,
): EditorAnnotation {
  return {
    id: annotation.id,
    label_class_id: annotation.label_class_id,
    x_min: annotation.x_min,
    y_min: annotation.y_min,
    x_max: annotation.x_max,
    y_max: annotation.y_max,
  };
}

export function toEditorMaskAnnotation(
  annotation: MaskAnnotationRecord,
): EditorMaskAnnotation {
  return {
    id: annotation.id,
    label_class_id: annotation.label_class_id,
    geometry_kind: annotation.geometry_kind,
    points: annotation.polygon_json?.map(([x, y]) => ({ x, y })) ?? null,
    mask_path: annotation.mask_path,
    x_min: annotation.x_min,
    y_min: annotation.y_min,
    x_max: annotation.x_max,
    y_max: annotation.y_max,
    area_pixels: annotation.area_pixels,
    source_type: annotation.source_type,
    persisted: true,
    revision: annotation.revision,
  };
}
