import type { AnnotationDocument, EditorMaskAnnotation } from "./types";

export function addMaskAnnotation(
  document: AnnotationDocument,
  mask: EditorMaskAnnotation,
): AnnotationDocument {
  return {
    ...document,
    maskAnnotations: [...document.maskAnnotations, mask],
    deletedMaskAnnotationIds: document.deletedMaskAnnotationIds.filter(
      (id) => id !== mask.id,
    ),
  };
}

export function updateMaskAnnotation(
  document: AnnotationDocument,
  mask: EditorMaskAnnotation,
): AnnotationDocument {
  const exists = document.maskAnnotations.some((item) => item.id === mask.id);
  if (!exists) {
    return addMaskAnnotation(document, mask);
  }
  return {
    ...document,
    maskAnnotations: document.maskAnnotations.map((item) =>
      item.id === mask.id ? mask : item,
    ),
  };
}

export function deleteMaskAnnotations(
  document: AnnotationDocument,
  maskIds: string[],
): AnnotationDocument {
  const idsToDelete = new Set(maskIds);
  const persistedIds = document.maskAnnotations
    .filter((mask) => idsToDelete.has(mask.id) && mask.persisted)
    .map((mask) => mask.id);
  return {
    ...document,
    maskAnnotations: document.maskAnnotations.filter(
      (mask) => !idsToDelete.has(mask.id),
    ),
    deletedMaskAnnotationIds: Array.from(
      new Set([...document.deletedMaskAnnotationIds, ...persistedIds]),
    ),
  };
}

export function changeMaskAnnotationClass(
  document: AnnotationDocument,
  maskIds: string[],
  labelClassId: string,
): AnnotationDocument {
  const selected = new Set(maskIds);
  return {
    ...document,
    maskAnnotations: document.maskAnnotations.map((mask) =>
      selected.has(mask.id) &&
      (mask.geometry_kind === "polygon" || mask.geometry_kind === "rotated_box")
        ? {
            ...mask,
            label_class_id: labelClassId,
          }
        : mask,
    ),
  };
}
