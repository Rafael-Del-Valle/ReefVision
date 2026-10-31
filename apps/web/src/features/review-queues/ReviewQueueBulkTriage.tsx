import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

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
  actor: string;
  review_confirmed?: boolean;
  client_request_id: string;
};

type ScopedBulkRequest = {
  queueId: string;
  scopeEpoch: number;
  payload: BulkRequest;
};

type UncertainBulkRequest = {
  request: ScopedBulkRequest;
  errorMessage: string;
};

function newBulkRequestId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  // Some older desktop WebView2 environments expose getRandomValues but
  // not randomUUID. Keep the idempotency key cryptographically random.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20),
  ].join("-");
}

function eligible(
  item: ReviewQueueItem,
  action: ReviewQueueBulkAction,
): boolean {
  if (action === "start") return item.review_state === "pending";
  if (action === "complete") return item.review_state === "in_progress";
  if (action === "skip") {
    return (
      item.review_state === "pending" || item.review_state === "in_progress"
    );
  }
  return item.review_state === "skipped";
}

export function ReviewQueueBulkTriage({ queueId, items }: Props) {
  const queryClient = useQueryClient();
  // A mounted dashboard can reuse this panel for a different review queue.
  // Capture the queue and visit at submission, not when a response arrives.
  const currentScope = useRef({ queueId, epoch: 0 });
  if (currentScope.current.queueId !== queueId) {
    currentScope.current = {
      queueId,
      epoch: currentScope.current.epoch + 1,
    };
  }
  const [action, setAction] = useState<ReviewQueueBulkAction>("start");
  const [selected, setSelected] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [actor, setActor] = useState("");
  const [confirmedSelectionKey, setConfirmedSelectionKey] = useState<
    string | null
  >(null);
  const [reviewedSelectionKey, setReviewedSelectionKey] = useState<
    string | null
  >(null);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const [uncertainRequests, setUncertainRequests] = useState<
    Record<string, UncertainBulkRequest>
  >({});
  const uncertainRequest = uncertainRequests[queueId] ?? null;
  useEffect(() => {
    // Never carry selected image IDs, evidence approvals or a prior queue's
    // success banner into another queue. Preserve unresolved UUIDs per queue.
    setSelected([]);
    setReason("");
    setConfirmedSelectionKey(null);
    setReviewedSelectionKey(null);
    setLastResult(null);
  }, [queueId]);
  const available = items.filter((item) => eligible(item, action));
  const selectedIds = selected.filter((id) =>
    available.some((item) => item.id === id),
  );
  // A background refetch can change eligibility after manual confirmation.
  // Bind both confirmations to the visible review scope and source-evidence\n  // fingerprint. A refreshed score, checksum, severity, or item update must\n  // invalidate confirmation even when the same IDs remain eligible.
  const selectionKey = JSON.stringify({
    queueId,
    action,
    items: selectedIds.map((id) => {
      const item = available.find((candidate) => candidate.id === id);
      return [
        id,
        item?.image_id,
        item?.rank_position,
        item?.review_state,
        item?.input_checksum,
        item?.score,
        item?.highest_qc_severity,
        item?.updated_at,
      ];
    }),
  });
  const confirmed = confirmedSelectionKey === selectionKey;
  const reviewedConfirmed = reviewedSelectionKey === selectionKey;
  useEffect(() => {
    // Prevent stale confirmations from reactivating if a state changes back.
    setConfirmedSelectionKey(null);
    setReviewedSelectionKey(null);
  }, [selectionKey]);
  const mutation = useMutation({
    mutationFn: (request: ScopedBulkRequest) =>
      bulkTriageReviewQueueItems(request.queueId, request.payload),
    onSuccess: async (result, request) => {
      // A delayed success cannot erase a different queue's uncertain retry.
      setUncertainRequests((current) => {
        if (
          current[request.queueId]?.request.payload.client_request_id !==
          request.payload.client_request_id
        ) {
          return current;
        }
        const next = { ...current };
        delete next[request.queueId];
        return next;
      });
      if (
        currentScope.current.queueId === request.queueId &&
        currentScope.current.epoch === request.scopeEpoch
      ) {
        setSelected([]);
        setConfirmedSelectionKey(null);
        setReviewedSelectionKey(null);
        setLastResult(
          `${result.changed_count} items updated; scientific review remains required.`,
        );
      }
      await queryClient.invalidateQueries({
        queryKey: ["review_queue_items", request.queueId],
      });
      await queryClient.invalidateQueries({
        queryKey: ["review_queue_events", request.queueId],
      });
    },
    onError: (error, request) => {
      // A lost response may follow a committed transaction. Keep its original
      // queue and UUID even if the researcher navigated elsewhere.
      setUncertainRequests((current) => ({
        ...current,
        [request.queueId]: {
          request,
          errorMessage: error instanceof Error ? error.message : String(error),
        },
      }));
    },
  });
  const locked = mutation.isPending || uncertainRequest !== null;
  const ready =
    selectedIds.length > 0 &&
    selectedIds.length <= 100 &&
    actor.trim().length > 0 &&
    confirmed &&
    (action !== "skip" || reason.trim().length > 0) &&
    (action !== "complete" || reviewedConfirmed);

  function submit() {
    if (!ready || locked) return;
    mutation.mutate({
      queueId,
      scopeEpoch: currentScope.current.epoch,
      payload: {
        item_ids: selectedIds,
        action,
        actor: actor.trim(),
        // Stable across an uncertain-response retry; never reapply a stale
        // triage action after another researcher changes the queue state.
        client_request_id: newBulkRequestId(),
        ...(action === "skip" ? { reason: reason.trim() } : {}),
        ...(action === "complete" ? { review_confirmed: true } : {}),
      },
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
        Local reviewer label (self-reported, not an authenticated account)
        <input
          aria-label="Bulk triage reviewer label"
          maxLength={100}
          disabled={locked}
          value={actor}
          onChange={(event) => {
            setActor(event.target.value);
            setConfirmedSelectionKey(null);
            setReviewedSelectionKey(null);
          }}
        />
      </label>
      <label>
        Triage action
        <select
          aria-label="Triage action"
          value={action}
          disabled={locked}
          onChange={(event) => {
            setAction(event.target.value as ReviewQueueBulkAction);
            setSelected([]);
            setConfirmedSelectionKey(null);
            setReviewedSelectionKey(null);
            setLastResult(null);
          }}
        >
          <option value="start">Start review</option>
          <option value="skip">Skip with reason</option>
          <option value="return">Return skipped items</option>
          <option value="complete">Complete manually reviewed items</option>
        </select>
      </label>
      <div className="version-actions">
        <button
          type="button"
          className="secondary"
          disabled={locked || available.length === 0}
          onClick={() => {
            setSelected(available.slice(0, 100).map((item) => item.id));
            setConfirmedSelectionKey(null);
            setReviewedSelectionKey(null);
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
            setConfirmedSelectionKey(null);
            setReviewedSelectionKey(null);
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
                setConfirmedSelectionKey(null);
                setReviewedSelectionKey(null);
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
              setConfirmedSelectionKey(null);
            }}
          />
        </label>
      )}
      {action === "complete" && (
        <label>
          <input
            type="checkbox"
            aria-label="Confirm each item was manually reviewed"
            disabled={locked || selectedIds.length === 0}
            checked={reviewedConfirmed}
            onChange={(event) =>
              setReviewedSelectionKey(
                event.target.checked ? selectionKey : null,
              )
            }
          />
          I personally inspected every selected item. Completion is queue
          bookkeeping, not acceptance of model predictions or annotations.
        </label>
      )}
      <label>
        <input
          type="checkbox"
          aria-label="Confirm manual triage"
          disabled={locked || selectedIds.length === 0}
          checked={confirmed}
          onChange={(event) =>
            setConfirmedSelectionKey(event.target.checked ? selectionKey : null)
          }
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
      {uncertainRequest && (
        <p role="alert">{uncertainRequest.errorMessage}</p>
      )}
      {uncertainRequest && (
        <div role="group" aria-label="Uncertain bulk triage outcome">
          <p>
            The outcome may be uncertain. Retry the identical request or discard
            and refresh the queue before choosing another action.
          </p>
          <button
            type="button"
            disabled={mutation.isPending}
            onClick={() => mutation.mutate(uncertainRequest.request)}
          >
            Retry identical bulk action
          </button>
          <button
            type="button"
            className="secondary"
            disabled={mutation.isPending}
            onClick={() => {
              setUncertainRequests((current) => {
                if (
                  current[queueId]?.request.payload.client_request_id !==
                  uncertainRequest.request.payload.client_request_id
                ) {
                  return current;
                }
                const next = { ...current };
                delete next[queueId];
                return next;
              });
              setSelected([]);
              setConfirmedSelectionKey(null);
              setReviewedSelectionKey(null);
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
