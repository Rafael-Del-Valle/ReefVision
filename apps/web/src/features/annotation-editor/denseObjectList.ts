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

/** Pin at most 200 distinct selected rows that actually match this filtered
 * browser, not simply 200 selected IDs. Class filtering, deletion and repeated
 * selection IDs can leave the most recent selection tail absent from the
 * visible document. Resume earlier IDs only when a candidate batch missed.
 *
 * Memory stays bounded to the page, 200 candidates and 200 pinned rows; the
 * common case still examines only the latest 200 distinct off-page IDs.
 */
function recentMatchingSelectionRows<T extends { id: string }>(
  items: readonly T[],
  selectedIds: readonly string[],
  visibleIds: ReadonlySet<string>,
  windowStart: number,
  windowEnd: number,
  offset: number,
): Array<{ item: T; position: number }> {
  const rows: Array<{ item: T; position: number }> = [];
  const pinnedIds = new Set<string>();
  let nextIndex = selectedIds.length - 1;
  while (nextIndex >= 0 && pinnedIds.size < 200) {
    const candidates = new Set<string>();
    const remaining = 200 - pinnedIds.size;
    while (nextIndex >= 0 && candidates.size < remaining) {
      const id = selectedIds[nextIndex];
      nextIndex -= 1;
      if (!visibleIds.has(id) && !pinnedIds.has(id)) {
        candidates.add(id);
      }
    }
    if (candidates.size === 0) {
      break;
    }

    const scan = (from: number, to: number) => {
      for (let index = from; index < to && candidates.size > 0; index += 1) {
        const item = items[index];
        if (candidates.delete(item.id)) {
          pinnedIds.add(item.id);
          rows.push({ item, position: offset + index });
        }
      }
    };
    scan(0, windowStart);
    scan(windowEnd, items.length);
  }
  return rows;
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

  // Only selected IDs matching the filtered document consume the 200-row
  // off-page budget. Deleted or other-class selections cannot hide valid pins.
  for (const pinned of recentMatchingSelectionRows(
    annotations,
    selectedAnnotationIds,
    visibleAnnotationIds,
    annotationStart,
    annotationEnd,
    0,
  )) {
    rows.push({ kind: "annotation", ...pinned });
  }
  for (const pinned of recentMatchingSelectionRows(
    masks,
    selectedMaskIds,
    visibleMaskIds,
    maskStart,
    maskEnd,
    annotations.length,
  )) {
    rows.push({ kind: "mask", ...pinned });
  }

  // Selected rows before the window must precede the window in the
  // accessible list; position always refers to the full filtered document.
  rows.sort((left, right) => left.position - right.position);
  return rows;
}

/** Resolve selected mounted rows with bounded memory and linear selection scans.
 * Dense range selections must not trigger an Array.includes scan per DOM row.
 */
export function selectedDenseObjectRowIds<
  A extends { id: string },
  M extends { id: string },
>(
  rows: readonly DenseObjectListRow<A, M>[],
  selectedAnnotationIds: readonly string[],
  selectedMaskIds: readonly string[],
): { annotationIds: ReadonlySet<string>; maskIds: ReadonlySet<string> } {
  const candidateAnnotations = new Set<string>();
  const candidateMasks = new Set<string>();
  for (const row of rows) {
    if (row.kind === "annotation") {
      candidateAnnotations.add(row.item.id);
    } else {
      candidateMasks.add(row.item.id);
    }
  }
  const annotationIds = new Set<string>();
  const maskIds = new Set<string>();
  if (candidateAnnotations.size > 0) {
    for (const id of selectedAnnotationIds) {
      if (candidateAnnotations.has(id)) annotationIds.add(id);
      if (annotationIds.size === candidateAnnotations.size) break;
    }
  }
  if (candidateMasks.size > 0) {
    for (const id of selectedMaskIds) {
      if (candidateMasks.has(id)) maskIds.add(id);
      if (maskIds.size === candidateMasks.size) break;
    }
  }
  return { annotationIds, maskIds };
}
