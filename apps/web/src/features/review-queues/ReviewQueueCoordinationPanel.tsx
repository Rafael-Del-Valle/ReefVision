import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  addReviewQueueEvent,
  getReviewQueueEvents,
  type ReviewQueueEventCreate,
} from "../../api/client";

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
  const [actor, setActor] = useState("");
  const [assignee, setAssignee] = useState("");
  const [comment, setComment] = useState("");
  const [page, setPage] = useState(1);
  const [failedRequest, setFailedRequest] =
    useState<ReviewQueueEventCreate | null>(null);
  const events = useQuery({
    queryKey: ["review_queue_events", queueId, itemId, page],
    queryFn: ({ signal }) =>
      getReviewQueueEvents(queueId, itemId, page, signal),
  });
  const mutation = useMutation({
    mutationFn: (payload: ReviewQueueEventCreate) =>
      addReviewQueueEvent(queueId, itemId, payload),
    onSuccess: async (_, payload) => {
      setFailedRequest(null);
      if (payload.event_type === "comment") setComment("");
      if (payload.event_type === "assign") setAssignee("");
      await queryClient.invalidateQueries({
        queryKey: ["review_queue_events", queueId, itemId],
      });
    },
    onError: (_, payload) => setFailedRequest(payload),
  });

  function submit(eventType: ReviewQueueEventCreate["event_type"]) {
    const name = actor.trim();
    const text = comment.trim();
    const reviewer = assignee.trim();
    if (!name || failedRequest || mutation.isPending) return;
    if (eventType === "comment" && !text) return;
    if (eventType === "assign" && !reviewer) return;
    const payload: ReviewQueueEventCreate = {
      client_request_id: newRequestId(),
      event_type: eventType,
      actor: name,
      ...(eventType === "comment" ? { comment: text } : {}),
      ...(eventType === "assign" ? { assignee: reviewer } : {}),
    };
    mutation.mutate(payload);
  }

  const locked = mutation.isPending || failedRequest !== null;
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
          onChange={(event) => setActor(event.target.value)}
        />
      </label>
      <p>Assigned reviewer: {events.data?.current_assignee ?? "Unassigned"}</p>
      <label>
        Reviewer to assign
        <input
          aria-label="Reviewer to assign"
          maxLength={100}
          value={assignee}
          onChange={(event) => setAssignee(event.target.value)}
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
          onChange={(event) => setComment(event.target.value)}
        />
      </label>
      <button
        type="button"
        disabled={locked || !actor.trim() || !comment.trim()}
        onClick={() => submit("comment")}
      >
        Add comment
      </button>
      {mutation.error && <p role="alert">{mutation.error.message}</p>}
      {failedRequest && (
        <div role="group" aria-label="Failed review event">
          <p>
            The outcome may be uncertain. Retry with the same request ID or
            discard.
          </p>
          <button
            type="button"
            disabled={mutation.isPending}
            onClick={() => mutation.mutate(failedRequest)}
          >
            Retry event
          </button>
          <button
            type="button"
            className="secondary"
            disabled={mutation.isPending}
            onClick={() => {
              setFailedRequest(null);
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
            onClick={() => setPage((current) => current - 1)}
          >
            Previous events
          </button>
          <span>Page {page}</span>
          <button
            type="button"
            className="secondary"
            disabled={page * 50 >= events.data.total}
            onClick={() => setPage((current) => current + 1)}
          >
            Next events
          </button>
        </nav>
      )}
    </section>
  );
}
