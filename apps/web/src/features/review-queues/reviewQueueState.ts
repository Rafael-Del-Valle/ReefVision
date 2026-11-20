export type ReviewQueueScopeType = "project" | "dataset_version";

export function reviewQueuesQueryKey(
  projectId: string,
  scopeType: ReviewQueueScopeType,
  datasetVersionId: string,
) {
  return ["review_queues", projectId, scopeType, datasetVersionId] as const;
}

export function reviewQueueItemsQueryKey(
  queueId: string,
  page: number,
  labelClassId: string,
  split: string,
  qcSeverity: string,
  reviewState: string,
  modelId: string,
) {
  return [
    "review_queue_items",
    queueId,
    page,
    labelClassId,
    split,
    qcSeverity,
    reviewState,
    modelId,
  ] as const;
}

/**
 * Never fetch or expose review items for a queue outside the currently loaded
 * project/dataset-version scope. A stale selected ID can survive project or
 * scope navigation while React Query resolves the new queue list.
 */
export function scopedReviewQueueId(
  selectedId: string,
  queues: readonly { id: string }[] | undefined,
): string {
  return selectedId && queues?.some((queue) => queue.id === selectedId)
    ? selectedId
    : "";
}
