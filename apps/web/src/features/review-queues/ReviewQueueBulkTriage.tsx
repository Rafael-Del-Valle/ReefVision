import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  bulkTriageReviewQueueItems,
  type ReviewQueueBulkAction,
  type ReviewQueueItem,
} from "../../api/client";

interface Props {
  queueId: string;
  items: ReviewQueueItem[];
}

type BulkRequest = {
  item_ids: string[];
  action: ReviewQueueBulkAction;
  reason?: string;
};

function eligible(
  item: ReviewQueueItem,
  action: ReviewQueueBulkAction,
): boolean {
  if (action === "start") return item.review_state === "pending";
  if (action === "skip") {
    return (
      item.review_state === "pending" || item.review_state === "in_progress"
    );
  }
  return item.review_state === "skipped";
}

export function ReviewQueueBulkTriage({ queueId, items }: Props) {
  const queryClient = useQueryClient();
  const [action, setAction] = useState<ReviewQueueBulkAction>("start");
  const [selected, setSelected] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const [uncertainRequest, setUncertainRequest] = useState<BulkRequest | null>(
    null,
  );
  const available = items.filter((item) => eligible(item, action));
  const selectedIds = selected.filter((id) =>
    available.some((item) => item.id === id),
  );
  const mutation = useMutation({
    mutationFn: (payload: BulkRequest) =>
      bulkTriageReviewQueueItems(queueId, payload),
    onSuccess: async (result) => {
      setSelected([]);
      setConfirmed(false);
      setUncertainRequest(null);
      setLastResult(
        `${result.changed_count} items updated; scientific review remains required.`,
      );
      await queryClient.invalidateQueries({
        queryKey: ["review_queue_items", queueId],
      });
    },
    onError: (_, payload) => {
      // A lost response may follow a committed transaction.
      setUncertainRequest(payload);
    },
  });
  const locked = mutation.isPending || uncertainRequest !== null;
  const ready =
    selectedIds.length > 0 &&
    selectedIds.length <= 100 &&
    confirmed &&
    (action !== "skip" || reason.trim().length > 0);

  function submit() {
    if (!ready || locked) return;
    mutation.mutate({
      item_ids: selectedIds,
      action,
      ...(action === "skip" ? { reason: reason.trim() } : {}),
    });
  }

  return (
    <section className="dashboard-card" aria-label="Bulk QC triage">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Manual queue management</p>
          <h4>Bulk QC triage</h4>
        </div>
        <span>{selectedIds.length} selected on this page</span>
      </div>
      <p className="annotation-helper">
        Only visible eligible items can be selected. These actions never approve
        model predictions or verify scientific observations.
      </p>
      <label>
        Triage action
        <select
          aria-label="Triage action"
          value={action}
          disabled={locked}
          onChange={(event) => {
            setAction(event.target.value as ReviewQueueBulkAction);
            setSelected([]);
            setConfirmed(false);
            setLastResult(null);
          }}
        >
          <option value="start">Start review</option>
          <option value="skip">Skip with reason</option>
          <option value="return">Return skipped items</option>
        </select>
      </label>
      <div className="version-actions">
        <button
          type="button"
          className="secondary"
          disabled={locked || available.length === 0}
          onClick={() => {
            setSelected(available.slice(0, 100).map((item) => item.id));
            setConfirmed(false);
          }}
        >
          Select eligible on page ({available.length})
        </button>
        <button
          type="button"
          className="secondary"
          disabled={locked || selected.length === 0}
          onClick={() => {
            setSelected([]);
            setConfirmed(false);
          }}
        >
          Clear selection
        </button>
      </div>
      <div role="group" aria-label="Eligible review items">
        {available.map((item) => (
          <label key={item.id}>
            <input
              type="checkbox"
              disabled={locked}
              checked={selectedIds.includes(item.id)}
              onChange={(event) => {
                setSelected((current) =>
                  event.target.checked
                    ? [...current, item.id]
                    : current.filter((id) => id !== item.id),
                );
                setConfirmed(false);
              }}
            />
            Rank {item.rank_position} — image {item.image_id} (
            {item.review_state})
          </label>
        ))}
      </div>
      {action === "skip" && (
        <label>
          Bulk skip reason
          <textarea
            aria-label="Bulk skip reason"
            maxLength={500}
            disabled={locked}
            value={reason}
            onChange={(event) => {
              setReason(event.target.value);
              setConfirmed(false);
            }}
          />
        </label>
      )}
      <label>
        <input
          type="checkbox"
          aria-label="Confirm manual triage"
          disabled={locked || selectedIds.length === 0}
          checked={confirmed}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        I confirm this queue-only action; biological verification remains
        manual.
      </label>
      <button type="button" disabled={!ready || locked} onClick={submit}>
        {mutation.isPending
          ? "Applying..."
          : `Apply ${action} to ${selectedIds.length} items`}
      </button>
      {lastResult && <p role="status">{lastResult}</p>}
      {mutation.error && <p role="alert">{mutation.error.message}</p>}
      {uncertainRequest && (
        <div role="group" aria-label="Uncertain bulk triage outcome">
          <p>
            The outcome may be uncertain. Retry the identical request or discard
            and refresh the queue before choosing another action.
          </p>
          <button
            type="button"
            disabled={mutation.isPending}
            onClick={() => mutation.mutate(uncertainRequest)}
          >
            Retry identical bulk action
          </button>
          <button
            type="button"
            className="secondary"
            disabled={mutation.isPending}
            onClick={() => {
              setUncertainRequest(null);
              setSelected([]);
              setConfirmed(false);
              mutation.reset();
              void queryClient.invalidateQueries({
                queryKey: ["review_queue_items", queueId],
              });
            }}
          >
            Discard and refresh
          </button>
        </div>
      )}
    </section>
  );
}
