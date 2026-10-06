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
