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

/** Delete boxes and masks in linear time for dense biological images.
 * Missing/stale IDs must never create a false scientific revision.
 * Persisted-mask tombstones remain the responsibility of the existing
 * mask deletion operation; unsaved masks never acquire tombstones.
 */
export function deleteSelectedAnnotations(
  document: AnnotationDocument,
  annotationIds: readonly string[],
  maskIds: readonly string[],
): AnnotationDocument {
  if (annotationIds.length === 0 && maskIds.length === 0) {
    return document;
  }
  const selectedBoxes = new Set(annotationIds);
  const annotations =
    selectedBoxes.size > 0
      ? document.annotations.filter((item) => !selectedBoxes.has(item.id))
      : document.annotations;
  const selectedMasks = new Set(maskIds);
  const hasMatchingMask =
    selectedMasks.size > 0 &&
    document.maskAnnotations.some((mask) => selectedMasks.has(mask.id));
  if (annotations.length === document.annotations.length && !hasMatchingMask) {
    return document;
  }
  const nextDocument = { ...document, annotations };
  return hasMatchingMask
    ? deleteMaskAnnotations(nextDocument, [...selectedMasks])
    : nextDocument;
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
      selected.has(mask.id) && mask.geometry_kind === "polygon"
        ? {
            ...mask,
            label_class_id: labelClassId,
          }
        : mask,
    ),
  };
}
