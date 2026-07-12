import type { AnnotationRecord, AnnotationStatus } from "../../api/client";

export type EditorTool = "select" | "box";

export interface EditorAnnotation {
  id: string;
  label_class_id: string;
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
}

export interface AnnotationDocument {
  annotation_status: AnnotationStatus;
  annotations: EditorAnnotation[];
}

export interface AnnotationEditorState {
  baseRevision: number;
  documentVersion: number;
  lastCommittedVersion: number;
  document: AnnotationDocument;
  history: AnnotationDocument[];
  future: AnnotationDocument[];
  selectedIds: string[];
  activeClassId: string | null;
  hiddenClassIds: string[];
  tool: EditorTool;
  saveState: "idle" | "dirty" | "saving" | "saved" | "error" | "conflict";
  saveMessage: string | null;
}

export interface Point {
  x: number;
  y: number;
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
