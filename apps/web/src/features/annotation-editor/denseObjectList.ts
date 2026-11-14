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
  requestedStart = 0,
): DenseObjectListRow<A, M>[] {
  const total = annotations.length + masks.length;
  const limit = Number.isFinite(requestedLimit)
    ? Math.min(total, Math.max(0, Math.floor(requestedLimit)))
    : 0;
  const start = Number.isFinite(requestedStart)
    ? Math.min(Math.max(0, total - 1), Math.max(0, Math.floor(requestedStart)))
    : 0;
  const end = Math.min(total, start + limit);
  const annotationStart = Math.min(start, annotations.length);
  const annotationEnd = Math.min(end, annotations.length);
  const maskStart = Math.max(0, start - annotations.length);
  const maskEnd = Math.max(0, end - annotations.length);
  const rows: DenseObjectListRow<A, M>[] = [];
  const pendingAnnotationIds = new Set(selectedAnnotationIds);
  const pendingMaskIds = new Set(selectedMaskIds);

  // Show only the requested source-order window. Jumping to a distant
  // biological observation must not first mount thousands of React options.
  for (let index = annotationStart; index < annotationEnd; index += 1) {
    const item = annotations[index];
    rows.push({ kind: "annotation", item, position: index });
    pendingAnnotationIds.delete(item.id);
  }
  for (let index = maskStart; index < maskEnd; index += 1) {
    const item = masks[index];
    rows.push({ kind: "mask", item, position: annotations.length + index });
    pendingMaskIds.delete(item.id);
  }

  // Large selections do not override the bounded DOM. Selected records
  // outside this window remain intact; pin at most the latest 200 per type.
  const maxPinnedPerType = 200;
  const pinnedAnnotations = new Set(
    selectedAnnotationIds
      .filter((id) => pendingAnnotationIds.has(id))
      .slice(-maxPinnedPerType),
  );
  const pinnedMasks = new Set(
    selectedMaskIds
      .filter((id) => pendingMaskIds.has(id))
      .slice(-maxPinnedPerType),
  );

  // Scan only regions outside the displayed window. A saved annotation
  // selected before a jumped-to window must still be accessible, and no
  // unrelated mask geometry is read after all pinned IDs have been found.
  const appendPinnedAnnotations = (from: number, to: number) => {
    for (let index = from; index < to && pinnedAnnotations.size > 0; index += 1) {
      const item = annotations[index];
      if (pinnedAnnotations.delete(item.id)) {
        rows.push({ kind: "annotation", item, position: index });
      }
    }
  };
  appendPinnedAnnotations(0, annotationStart);
  appendPinnedAnnotations(annotationEnd, annotations.length);

  const appendPinnedMasks = (from: number, to: number) => {
    for (let index = from; index < to && pinnedMasks.size > 0; index += 1) {
      const item = masks[index];
      if (pinnedMasks.delete(item.id)) {
        rows.push({
          kind: "mask",
          item,
          position: annotations.length + index,
        });
      }
    }
  };
  appendPinnedMasks(0, maskStart);
  appendPinnedMasks(maskEnd, masks.length);

  // Selected rows before the window must precede the window in the
  // accessible list; position always refers to the full filtered document.
  rows.sort((left, right) => left.position - right.position);
  return rows;
}
