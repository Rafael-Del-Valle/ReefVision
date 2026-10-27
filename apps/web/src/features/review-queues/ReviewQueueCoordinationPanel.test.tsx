import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { addReviewQueueEvent, getReviewQueueEvents } from "../../api/client";
import { ReviewQueueCoordinationPanel } from "./ReviewQueueCoordinationPanel";

vi.mock("../../api/client", () => ({
  addReviewQueueEvent: vi.fn(),
  getReviewQueueEvents: vi.fn(),
}));

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ReviewQueueCoordinationPanel
        queueId="queue-1"
        itemId="item-1"
        onClose={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

describe("ReviewQueueCoordinationPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getReviewQueueEvents).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 50,
      current_assignee: null,
      requires_researcher_review: true,
    });
    vi.mocked(addReviewQueueEvent).mockImplementation(
      async (_, __, payload) => ({
        id: "event-1",
        review_queue_id: "queue-1",
        review_queue_item_id: "item-1",
        project_id: "project-1",
        client_request_id: payload.client_request_id,
        event_type: payload.event_type,
        actor: payload.actor,
        comment: payload.comment ?? null,
        assignee: payload.assignee ?? null,
        created_at: "2026-10-18T20:00:00Z",
      }),
    );
  });

  it("posts a comment with trimmed actor and UUID without approving data", async () => {
    mount();
    await screen.findByText("Assigned reviewer: Unassigned");
    fireEvent.change(screen.getByLabelText("Your local reviewer label"), {
      target: { value: "  scientist  " },
    });
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "  Inspect tentacle outline  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
    await waitFor(() => {
      expect(addReviewQueueEvent).toHaveBeenCalledWith(
        "queue-1",
        "item-1",
        expect.objectContaining({
          event_type: "comment",
          actor: "scientist",
          comment: "Inspect tentacle outline",
          client_request_id: expect.any(String),
        }),
      );
    });
    expect(
      vi.mocked(addReviewQueueEvent).mock.calls[0][2].client_request_id,
    ).toMatch(/^[0-9a-f-]{36}$/i);
    expect(
      screen.queryByRole("button", { name: /approve|verify/i }),
    ).toBeNull();
  });

  it("retries an uncertain assignment with exactly the same request UUID", async () => {
    vi.mocked(addReviewQueueEvent)
      .mockRejectedValueOnce(new Error("Connection interrupted"))
      .mockResolvedValueOnce({
        id: "event-1",
        review_queue_id: "queue-1",
        review_queue_item_id: "item-1",
        project_id: "project-1",
        client_request_id: "same-id",
        event_type: "assign",
        actor: "scientist",
        comment: null,
        assignee: "reviewer-two",
        created_at: "2026-10-18T20:00:00Z",
      });
    mount();
    await screen.findByText("Assigned reviewer: Unassigned");
    fireEvent.change(screen.getByLabelText("Your local reviewer label"), {
      target: { value: "scientist" },
    });
    fireEvent.change(screen.getByLabelText("Reviewer to assign"), {
      target: { value: "reviewer-two" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Assign reviewer" }));
    await screen.findByRole("button", { name: "Retry event" });
    fireEvent.click(screen.getByRole("button", { name: "Retry event" }));
    await waitFor(() => expect(addReviewQueueEvent).toHaveBeenCalledTimes(2));
    const calls = vi.mocked(addReviewQueueEvent).mock.calls;
    expect(calls[1][2].client_request_id).toBe(calls[0][2].client_request_id);
    expect(calls[1][2].event_type).toBe("assign");
  });
});
