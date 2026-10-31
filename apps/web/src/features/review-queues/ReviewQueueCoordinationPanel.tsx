import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import {
  addReviewQueueEvent,
  getReviewQueueEvents,
  type ReviewQueueEventCreate,
} from "../../api/client";

type EventMutationRequest = {
  queueId: string;
  itemId: string;
  scopeEpoch: number;
  payload: ReviewQueueEventCreate;
  commentRevision: number;
  assigneeRevision: number;
  actorRevision: number;
  draftKey: string;
};

type CoordinationDraft = {
  actor: string;
  assignee: string;
  comment: string;
  page: number;
};

const emptyDraft: CoordinationDraft = {
  actor: "",
  assignee: "",
  comment: "",
  page: 1,
};

interface Props {
  queueId: string;
  itemId: string;
  onClose: () => void;
}

function newRequestId(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function ReviewQueueCoordinationPanel({
  queueId,
  itemId,
  onClose,
}: Props) {
  const queryClient = useQueryClient();
  // Bind each request to the queue/item and navigation epoch at submission.
  // This also protects direct consumers that reuse the panel without a React key.
  const currentScope = useRef({ queueId, itemId, epoch: 0 });
  if (
    currentScope.current.queueId !== queueId ||
    currentScope.current.itemId !== itemId
  ) {
    currentScope.current = {
      queueId,
      itemId,
      epoch: currentScope.current.epoch + 1,
    };
  }
  // The panel can be reused for another review item. Keep unsent research
  // notes, reviewer attribution and history pagination isolated by item.
  // A -> B -> A restores A's unsent work without copying it onto B.
  const draftKey = JSON.stringify([queueId, itemId]);
  const [drafts, setDrafts] = useState<Record<string, CoordinationDraft>>({});
  const { actor, assignee, comment, page } = drafts[draftKey] ?? emptyDraft;
  const updateDraft = (patch: Partial<CoordinationDraft>) => {
    setDrafts((current) => ({
      ...current,
      [draftKey]: { ...(current[draftKey] ?? emptyDraft), ...patch },
    }));
  };
  // A response may arrive after the researcher has begun a different draft.
  // Retain the exact request for idempotent retries without erasing new work.
  // A changed reviewer label also makes a draft a distinct researcher's work.
  const commentRevision = useRef(0);
  const assigneeRevision = useRef(0);
  const actorRevision = useRef(0);
  const [failedRequests, setFailedRequests] = useState<
    Record<string, { request: EventMutationRequest; errorMessage: string }>
  >({});
  const events = useQuery({
    queryKey: ["review_queue_events", queueId, itemId, page],
    queryFn: ({ signal }) =>
      getReviewQueueEvents(queueId, itemId, page, signal),
  });
  const isCurrentRequest = (request: EventMutationRequest) =>
    currentScope.current.queueId === request.queueId &&
    currentScope.current.itemId === request.itemId &&
    currentScope.current.epoch === request.scopeEpoch;
  const mutation = useMutation({
    mutationFn: (request: EventMutationRequest) =>
      addReviewQueueEvent(request.queueId, request.itemId, request.payload),
    onSuccess: async (_, request) => {
      // Clear only the matching item and request UUID, even if navigation
      // changed while the event was in flight. Other uncertain events survive.
      setFailedRequests((current) => {
        if (
          current[request.draftKey]?.request.payload.client_request_id !==
          request.payload.client_request_id
        ) {
          return current;
        }
        const next = { ...current };
        delete next[request.draftKey];
        return next;
      });
      if (
        isCurrentRequest(request) &&
        request.payload.event_type === "comment" &&
        commentRevision.current === request.commentRevision &&
        actorRevision.current === request.actorRevision
      ) {
        setDrafts((current) => ({
          ...current,
          [request.draftKey]: {
            ...(current[request.draftKey] ?? emptyDraft),
            comment: "",
          },
        }));
      }
      if (
        isCurrentRequest(request) &&
        request.payload.event_type === "assign" &&
        assigneeRevision.current === request.assigneeRevision &&
        actorRevision.current === request.actorRevision
      ) {
        setDrafts((current) => ({
          ...current,
          [request.draftKey]: {
            ...(current[request.draftKey] ?? emptyDraft),
            assignee: "",
          },
        }));
      }
      await queryClient.invalidateQueries({
        queryKey: ["review_queue_events", request.queueId, request.itemId],
      });
    },
    onError: (error, request) => {
      // A late failure belongs to its original review item. Keep its UUID
      // available for an exact replay when the researcher returns to that item.
      setFailedRequests((current) => ({
        ...current,
        [request.draftKey]: {
          request,
          errorMessage: error instanceof Error ? error.message : String(error),
        },
      }));
    },
  });

  const activeFailure = failedRequests[draftKey];
  const activeFailedRequest = activeFailure?.request ?? null;

  function submit(eventType: ReviewQueueEventCreate["event_type"]) {
    const name = actor.trim();
    const text = comment.trim();
    const reviewer = assignee.trim();
    if (!name || activeFailedRequest || mutation.isPending) return;
    if (eventType === "comment" && !text) return;
    if (eventType === "assign" && !reviewer) return;
    const payload: ReviewQueueEventCreate = {
      client_request_id: newRequestId(),
      event_type: eventType,
      actor: name,
      ...(eventType === "comment" ? { comment: text } : {}),
      ...(eventType === "assign" ? { assignee: reviewer } : {}),
    };
    mutation.mutate({
      queueId,
      itemId,
      scopeEpoch: currentScope.current.epoch,
      payload,
      commentRevision: commentRevision.current,
      assigneeRevision: assigneeRevision.current,
      actorRevision: actorRevision.current,
      draftKey,
    });
  }

  const locked = mutation.isPending || activeFailedRequest !== null;
  return (
    <section aria-label="Review coordination" className="dashboard-card">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Researcher coordination</p>
          <h4>Comments and assignments</h4>
        </div>
        <button type="button" className="secondary" onClick={onClose}>
          Close coordination
        </button>
      </div>
      <p className="annotation-helper">
        Actor labels are self-reported on this local workstation, not verified
        accounts. Coordination does not approve or verify biological
        annotations.
      </p>
      <label>
        Your local reviewer label
        <input
          aria-label="Your local reviewer label"
          maxLength={100}
          value={actor}
          onChange={(event) => {
            actorRevision.current += 1;
            updateDraft({ actor: event.target.value });
          }}
        />
      </label>
      <p>Assigned reviewer: {events.data?.current_assignee ?? "Unassigned"}</p>
      <label>
        Reviewer to assign
        <input
          aria-label="Reviewer to assign"
          maxLength={100}
          value={assignee}
          onChange={(event) => {
            assigneeRevision.current += 1;
            updateDraft({ assignee: event.target.value });
          }}
        />
      </label>
      <div className="version-actions">
        <button
          type="button"
          disabled={locked || !actor.trim() || !assignee.trim()}
          onClick={() => submit("assign")}
        >
          Assign reviewer
        </button>
        <button
          type="button"
          className="secondary"
          disabled={locked || !actor.trim() || !events.data?.current_assignee}
          onClick={() => submit("unassign")}
        >
          Unassign reviewer
        </button>
      </div>
      <label>
        Review comment
        <textarea
          aria-label="Review comment"
          maxLength={2000}
          value={comment}
          onChange={(event) => {
            commentRevision.current += 1;
            updateDraft({ comment: event.target.value });
          }}
        />
      </label>
      <button
        type="button"
        disabled={locked || !actor.trim() || !comment.trim()}
        onClick={() => submit("comment")}
      >
        Add comment
      </button>
      {activeFailure && (
        <p role="alert">{activeFailure.errorMessage}</p>
      )}
      {activeFailedRequest && (
        <div role="group" aria-label="Failed review event">
          <p>
            The outcome may be uncertain. Retry with the same request ID or
            discard.
          </p>
          <button
            type="button"
            disabled={mutation.isPending}
            onClick={() =>
              mutation.mutate({
                ...activeFailedRequest,
                scopeEpoch: currentScope.current.epoch,
              })
            }
          >
            Retry event
          </button>
          <button
            type="button"
            className="secondary"
            disabled={mutation.isPending}
            onClick={() => {
              setFailedRequests((current) => {
                const next = { ...current };
                delete next[draftKey];
                return next;
              });
              mutation.reset();
            }}
          >
            Discard failed action
          </button>
        </div>
      )}
      {events.error && <p role="alert">{events.error.message}</p>}
      {events.isPending && <p role="status">Loading review history...</p>}
      <ol aria-label="Review event history">
        {events.data?.items.map((event) => (
          <li key={event.id}>
            <strong>{event.actor}</strong> — {event.event_type}
            {event.comment ? `: ${event.comment}` : ""}
            {event.assignee ? `: ${event.assignee}` : ""}
            <small> · {new Date(event.created_at).toLocaleString()}</small>
          </li>
        ))}
      </ol>
      {events.data && events.data.total > 50 && (
        <nav aria-label="Review event pages" className="version-actions">
          <button
            type="button"
            className="secondary"
            disabled={page === 1}
            onClick={() => updateDraft({ page: Math.max(1, page - 1) })}
          >
            Previous events
          </button>
          <span>Page {page}</span>
          <button
            type="button"
            className="secondary"
            disabled={page * 50 >= events.data.total}
            onClick={() => updateDraft({ page: page + 1 })}
          >
            Next events
          </button>
        </nav>
      )}
    </section>
  );
}
