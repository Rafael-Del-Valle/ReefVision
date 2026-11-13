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
  const limit = Number.isFinite(requestedLimit)
    ? Math.max(0, Math.floor(requestedLimit))
    : 0;
  const selectedAnnotations = new Set(selectedAnnotationIds);
  const selectedMasks = new Set(selectedMaskIds);
  const rows: DenseObjectListRow<A, M>[] = [];

  annotations.forEach((item, position) => {
    if (position < limit || selectedAnnotations.has(item.id)) {
      rows.push({ kind: "annotation", item, position });
    }
  });
  masks.forEach((item, index) => {
    const position = annotations.length + index;
    if (position < limit || selectedMasks.has(item.id)) {
      rows.push({ kind: "mask", item, position });
    }
  });
  return rows;
}
