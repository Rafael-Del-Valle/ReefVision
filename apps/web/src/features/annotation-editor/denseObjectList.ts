/** Display-only bounded list for densely annotated research images.
 * All records remain in the document, dataset, saved workflows, and QC views.
 * Selected matching records outside the window stay reachable.
 */
export type DenseObjectListRow<
  A extends { id: string },
  M extends { id: string },
> =
  | { kind: "annotation"; item: A; position: number }
  | { kind: "mask"; item: M; position: number };

export function boundedDenseObjectRows<
  A extends { id: string },
  M extends { id: string },
>(
  annotations: readonly A[],
  masks: readonly M[],
  requestedLimit: number,
  selectedAnnotationIds: readonly string[],
  selectedMaskIds: readonly string[],
): DenseObjectListRow<A, M>[] {
  const total = annotations.length + masks.length;
  const limit = Number.isFinite(requestedLimit)
    ? Math.min(total, Math.max(0, Math.floor(requestedLimit)))
    : 0;
  const rows: DenseObjectListRow<A, M>[] = [];
  const pendingAnnotationIds = new Set(selectedAnnotationIds);
  const pendingMaskIds = new Set(selectedMaskIds);
  const visibleAnnotationCount = Math.min(limit, annotations.length);
  const visibleMaskCount = limit - visibleAnnotationCount;

  // A bounded DOM does not help if every selection rerender traverses the
  // entire scientific document. Read only the prefix we actually display.
  for (let index = 0; index < visibleAnnotationCount; index += 1) {
    const item = annotations[index];
    rows.push({ kind: "annotation", item, position: index });
    pendingAnnotationIds.delete(item.id);
  }
  for (let index = 0; index < visibleMaskCount; index += 1) {
    const item = masks[index];
    rows.push({ kind: "mask", item, position: annotations.length + index });
    pendingMaskIds.delete(item.id);
  }

  // Distant selected objects remain available in original positional order.
  // Only scan the relevant suffix and stop at the final selected match.
  let annotationIndex = visibleAnnotationCount;
  while (
    pendingAnnotationIds.size > 0 &&
    annotationIndex < annotations.length
  ) {
    const item = annotations[annotationIndex];
    if (pendingAnnotationIds.delete(item.id)) {
      rows.push({ kind: "annotation", item, position: annotationIndex });
    }
    annotationIndex += 1;
  }
  let maskIndex = visibleMaskCount;
  while (pendingMaskIds.size > 0 && maskIndex < masks.length) {
    const item = masks[maskIndex];
    if (pendingMaskIds.delete(item.id)) {
      rows.push({
        kind: "mask",
        item,
        position: annotations.length + maskIndex,
      });
    }
    maskIndex += 1;
  }
  return rows;
}
