import { useQuery } from "@tanstack/react-query";

import {
  getReviewQueueItems,
  getReviewQueues,
  type ReviewQueueItem,
  type ReviewQueueRecord,
} from "../../api/client";
import {
  reviewQueueItemsQueryKey,
  reviewQueuesQueryKey,
} from "../../features/review-queues/reviewQueueState";

function queueSummary(queue: ReviewQueueRecord): string {
  if (queue.dataset_version_id) {
    return "Dataset-version review";
  }

  return "Project review";
}

function stateLabel(value: string): string {
  return value.replaceAll("_", " ");
}

export function ProjectReviewInspector({
  projectId,
  selectedQueueId,
  onOpenItem,
}: {
  projectId: string;
  selectedQueueId: string | null;
  onOpenItem: (item: ReviewQueueItem) => void;
}) {
  const queues = useQuery({
    queryKey: reviewQueuesQueryKey(projectId, "project", ""),
    queryFn: ({ signal }) => getReviewQueues(projectId, signal),
  });

  const selectedQueue =
    queues.data?.find((queue) => queue.id === selectedQueueId) ??
    queues.data?.[0] ??
    null;

  const queueId = selectedQueue?.id ?? "";

  const items = useQuery({
    queryKey: reviewQueueItemsQueryKey(queueId, 1, "", "", "", "", ""),
    queryFn: ({ signal }) =>
      getReviewQueueItems(
        queueId,
        {
          page: 1,
          pageSize: 25,
        },
        signal,
      ),
    enabled: queueId.length > 0,
  });

  const visibleItems = (items.data?.items ?? []).slice(0, 5);

  const pendingCount =
    items.data?.items.filter((item) => item.review_state === "pending")
      .length ?? 0;

  const inProgressCount =
    items.data?.items.filter((item) => item.review_state === "in_progress")
      .length ?? 0;

  return (
    <section
      className="rv-inspector-card rv-review-inspector"
      aria-label="Annotation and review list"
    >
      <div className="rv-inspector-card-heading">
        <strong>Annotation & review</strong>
        <span className="review-required">Scientist decision required</span>
      </div>

      <p>
        Ranked items identify where scientist attention is most useful. Opening
        an item enters the canonical annotation editor; this list does not
        accept, reject, or alter scientific annotations itself.
      </p>

      {queues.isPending && (
        <p className="annotation-helper">Loading review queues…</p>
      )}

      {queues.error && (
        <p className="form-error" role="alert">
          Review queues could not be loaded: {queues.error.message}
        </p>
      )}

      {!queues.isPending &&
        !queues.error &&
        (queues.data?.length ?? 0) === 0 && (
          <div className="rv-inspector-empty-control">
            <strong>No review queue generated</strong>
            <p>
              Generate a ranked queue in the main Review Queue workspace after
              running QC or producing model proposals.
            </p>
          </div>
        )}

      {selectedQueue && (
        <>
          <div className="rv-review-queue-summary">
            <div>
              <span>Queue</span>
              <strong>{queueSummary(selectedQueue)}</strong>
            </div>

            <div>
              <span>Status</span>
              <strong>{stateLabel(selectedQueue.status)}</strong>
            </div>

            <div>
              <span>Ranked images</span>
              <strong>{selectedQueue.item_count}</strong>
            </div>

            <div>
              <span>Formula</span>
              <strong>{selectedQueue.formula_id}</strong>
            </div>
          </div>

          {items.isPending && (
            <p className="annotation-helper">Loading ranked review items…</p>
          )}

          {items.error && (
            <p className="form-error" role="alert">
              Review items could not be loaded: {items.error.message}
            </p>
          )}

          {items.data && (
            <div className="rv-review-counts" aria-label="Review state summary">
              <span>{items.data.total} total</span>
              <span>{pendingCount} pending on page</span>
              <span>{inProgressCount} in progress on page</span>
            </div>
          )}

          {!items.isPending &&
            !items.error &&
            items.data &&
            visibleItems.length === 0 && (
              <div className="rv-inspector-empty-control">
                <strong>No items in this queue</strong>
                <p>This queue currently has no ranked image items to review.</p>
              </div>
            )}

          {visibleItems.length > 0 && (
            <div className="rv-review-list">
              {visibleItems.map((item) => {
                const primarySignal = item.score_breakdown_json[0] ?? null;

                return (
                  <article
                    key={item.id}
                    className="rv-review-list-item"
                    data-review-state={item.review_state}
                  >
                    <div className="rv-review-list-heading">
                      <div>
                        <strong>Rank #{item.rank_position}</strong>
                        <small>Score {item.score.toFixed(2)}</small>
                      </div>

                      <span>{stateLabel(item.review_state)}</span>
                    </div>

                    {item.highest_qc_severity && (
                      <span
                        className="rv-review-severity"
                        data-severity={item.highest_qc_severity}
                      >
                        QC {item.highest_qc_severity}
                      </span>
                    )}

                    <p>
                      {item.reason_summary ||
                        "Ranked for explicit scientist review."}
                    </p>

                    {primarySignal && (
                      <div className="rv-review-primary-signal">
                        <span>{primarySignal.label}</span>
                        <strong>
                          +{primarySignal.contribution.toFixed(2)}
                        </strong>
                      </div>
                    )}

                    <div className="rv-review-item-meta">
                      <span>
                        Image <code>{item.image_id.slice(0, 12)}</code>
                      </span>
                      {item.split && <span>{item.split}</span>}
                    </div>

                    <button type="button" onClick={() => onOpenItem(item)}>
                      Open in annotation editor
                    </button>
                  </article>
                );
              })}
            </div>
          )}

          {items.data && items.data.total > visibleItems.length && (
            <p className="annotation-helper">
              Showing the next {visibleItems.length} ranked items here. Use the
              main Review Queue workspace for the complete list, filtering,
              queue-state actions, and pagination.
            </p>
          )}
        </>
      )}

      <div className="rv-inference-boundary">
        <strong>Review boundary</strong>
        <p>
          Ranking scores and QC findings determine review priority only.
          Annotation acceptance, correction, rejection, and verification remain
          explicit scientist actions in canonical review tools.
        </p>
      </div>
    </section>
  );
}
