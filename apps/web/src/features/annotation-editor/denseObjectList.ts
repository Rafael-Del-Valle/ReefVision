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

/** Keep pinning bounded in memory as well as in DOM nodes.
 * Work backwards through the selection without copying a potentially huge
 * selected-ID array into a Set or a filtered intermediate array. Counting
 * repeated off-window entries preserves the last-200-entry behavior.
 */
function mostRecentOffWindowSelectionIds(
  selectedIds: readonly string[],
  visibleIds: ReadonlySet<string>,
): Set<string> {
  const pinned = new Set<string>();
  let remaining = 200;
  let index = selectedIds.length - 1;
  while (index >= 0 && remaining > 0) {
    const id = selectedIds[index];
    index -= 1;
    if (visibleIds.has(id)) {
      continue;
    }
    pinned.add(id);
    remaining -= 1;
  }
  return pinned;
}

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
  // A saved deep-list window may outlive deletions or a new filtered result.
  // Recover a full final window rather than rendering only the last record;
  // keep valid in-range jumps anchored at their requested source position.
  const normalizedStart = Number.isFinite(requestedStart)
    ? Math.max(0, Math.floor(requestedStart))
    : 0;
  const start =
    normalizedStart >= total ? Math.max(0, total - limit) : normalizedStart;
  const end = Math.min(total, start + limit);
  const annotationStart = Math.min(start, annotations.length);
  const annotationEnd = Math.min(end, annotations.length);
  const maskStart = Math.max(0, start - annotations.length);
  const maskEnd = Math.max(0, end - annotations.length);
  const rows: DenseObjectListRow<A, M>[] = [];
  const visibleAnnotationIds = new Set<string>();
  const visibleMaskIds = new Set<string>();

  // Show only the requested source-order window. Jumping to a distant
  // biological observation must not first mount thousands of React options.
  for (let index = annotationStart; index < annotationEnd; index += 1) {
    const item = annotations[index];
    rows.push({ kind: "annotation", item, position: index });
    visibleAnnotationIds.add(item.id);
  }
  for (let index = maskStart; index < maskEnd; index += 1) {
    const item = masks[index];
    rows.push({ kind: "mask", item, position: annotations.length + index });
    visibleMaskIds.add(item.id);
  }

  // Large selections do not override the bounded DOM or require a second
  // full-size selection copy. Pin the latest 200 off-window entries per type.
  const pinnedAnnotations = mostRecentOffWindowSelectionIds(
    selectedAnnotationIds,
    visibleAnnotationIds,
  );
  const pinnedMasks = mostRecentOffWindowSelectionIds(
    selectedMaskIds,
    visibleMaskIds,
  );

  // Scan only regions outside the displayed window. A saved annotation
  // selected before a jumped-to window must still be accessible, and no
  // unrelated mask geometry is read after all pinned IDs have been found.
  const appendPinnedAnnotations = (from: number, to: number) => {
    for (
      let index = from;
      index < to && pinnedAnnotations.size > 0;
      index += 1
    ) {
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
