import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  bulkTriageReviewQueueItems,
  type ReviewQueueItem,
} from "../../api/client";
import { ReviewQueueBulkTriage } from "./ReviewQueueBulkTriage";

vi.mock("../../api/client", () => ({
  bulkTriageReviewQueueItems: vi.fn(),
}));

const items = [
  {
    id: "pending-1",
    image_id: "image-1",
    rank_position: 1,
    review_state: "pending",
  },
  {
    id: "active-2",
    image_id: "image-2",
    rank_position: 2,
    review_state: "in_progress",
  },
  {
    id: "skipped-3",
    image_id: "image-3",
    rank_position: 3,
    review_state: "skipped",
  },
] as ReviewQueueItem[];

function mount(visible = items) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <ReviewQueueBulkTriage queueId="queue-1" items={visible} />
    </QueryClientProvider>,
  );
  return invalidate;
}

function mountChangingItems(visible = items) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const panel = (rows: ReviewQueueItem[]) => (
    <QueryClientProvider client={client}>
      <ReviewQueueBulkTriage queueId="queue-1" items={rows} />
    </QueryClientProvider>
  );
  const view = render(panel(visible));
  return (rows: ReviewQueueItem[]) => view.rerender(panel(rows));
}

describe("ReviewQueueBulkTriage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(bulkTriageReviewQueueItems).mockResolvedValue({
      queue_id: "queue-1",
      action: "start",
      changed_count: 1,
      items: [],
      requires_researcher_review: true,
    });
  });

  it("requires explicit confirmation and only sends eligible visible IDs", async () => {
    const invalidate = mount();
    fireEvent.change(screen.getByLabelText("Bulk triage reviewer label"), {
      target: { value: "lab reviewer" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Select eligible on page/ }),
    );
    const apply = screen.getByRole("button", {
      name: "Apply start to 1 items",
    });
    expect((apply as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByLabelText("Confirm manual triage"));
    fireEvent.click(apply);
    await waitFor(() =>
      expect(bulkTriageReviewQueueItems).toHaveBeenCalledWith("queue-1", {
        item_ids: ["pending-1"],
        action: "start",
        actor: "lab reviewer",
        client_request_id: expect.any(String),
      }),
    );
    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: ["review_queue_items", "queue-1"],
      }),
    );
    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: ["review_queue_events", "queue-1"],
      }),
    );
    expect(screen.getByRole("status").textContent).toContain(
      "scientific review remains required",
    );
    expect(
      screen.queryByRole("button", { name: /approve|verify/i }),
    ).toBeNull();
  });

  it("requires a nonempty skip reason and excludes completed items", async () => {
    mount();
    fireEvent.change(screen.getByLabelText("Bulk triage reviewer label"), {
      target: { value: "lab reviewer" },
    });
    fireEvent.change(screen.getByLabelText("Triage action"), {
      target: { value: "skip" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Select eligible on page/ }),
    );
    fireEvent.click(screen.getByLabelText("Confirm manual triage"));
    const apply = screen.getByRole("button", { name: "Apply skip to 2 items" });
    expect((apply as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Bulk skip reason"), {
      target: { value: "  obscured specimen  " },
    });
    fireEvent.click(screen.getByLabelText("Confirm manual triage"));
    fireEvent.click(apply);
    await waitFor(() =>
      expect(bulkTriageReviewQueueItems).toHaveBeenCalledWith("queue-1", {
        item_ids: ["pending-1", "active-2"],
        action: "skip",
        actor: "lab reviewer",
        client_request_id: expect.any(String),
        reason: "obscured specimen",
      }),
    );
  });

  it("retries uncertain outcomes using exactly the original payload", async () => {
    vi.mocked(bulkTriageReviewQueueItems)
      .mockRejectedValueOnce(new Error("Connection lost"))
      .mockResolvedValueOnce({
        queue_id: "queue-1",
        action: "return",
        changed_count: 1,
        items: [],
        requires_researcher_review: true,
      });
    mount();
    fireEvent.change(screen.getByLabelText("Bulk triage reviewer label"), {
      target: { value: "lab reviewer" },
    });
    fireEvent.change(screen.getByLabelText("Triage action"), {
      target: { value: "return" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Select eligible on page/ }),
    );
    fireEvent.click(screen.getByLabelText("Confirm manual triage"));
    fireEvent.click(
      screen.getByRole("button", { name: "Apply return to 1 items" }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Retry identical bulk action",
      }),
    );
    await waitFor(() =>
      expect(bulkTriageReviewQueueItems).toHaveBeenCalledTimes(2),
    );
    expect(vi.mocked(bulkTriageReviewQueueItems).mock.calls[0]).toEqual(
      vi.mocked(bulkTriageReviewQueueItems).mock.calls[1],
    );
  });

  it("bulk-completes only started, manually inspected items with confirmation", async () => {
    mount();
    fireEvent.change(screen.getByLabelText("Bulk triage reviewer label"), {
      target: { value: "lab reviewer" },
    });
    fireEvent.change(screen.getByLabelText("Triage action"), {
      target: { value: "complete" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Select eligible on page/ }),
    );
    const apply = screen.getByRole("button", {
      name: "Apply complete to 1 items",
    });
    fireEvent.click(screen.getByLabelText("Confirm manual triage"));
    expect((apply as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(
      screen.getByLabelText("Confirm each item was manually reviewed"),
    );
    expect((apply as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(apply);
    await waitFor(() =>
      expect(bulkTriageReviewQueueItems).toHaveBeenCalledWith("queue-1", {
        item_ids: ["active-2"],
        action: "complete",
        actor: "lab reviewer",
        client_request_id: expect.any(String),
        review_confirmed: true,
      }),
    );
  });
  it("reconfirms changed eligible items before bulk skip", async () => {
    const rerenderItems = mountChangingItems();
    fireEvent.change(screen.getByLabelText("Bulk triage reviewer label"), {
      target: { value: "lab reviewer" },
    });
    fireEvent.change(screen.getByLabelText("Triage action"), {
      target: { value: "skip" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Select eligible on page/ }),
    );
    fireEvent.change(screen.getByLabelText("Bulk skip reason"), {
      target: { value: "Cannot inspect polyp margins" },
    });
    const confirm = screen.getByLabelText(
      "Confirm manual triage",
    ) as HTMLInputElement;
    fireEvent.click(confirm);
    const apply = screen.getByRole("button", {
      name: "Apply skip to 2 items",
    }) as HTMLButtonElement;
    expect(apply.disabled).toBe(false);

    // IDs and count are unchanged, but the item state changed after approval.
    rerenderItems(
      items.map((item) =>
        item.id === "pending-1"
          ? ({ ...item, review_state: "in_progress" } as ReviewQueueItem)
          : item,
      ),
    );
    expect(confirm.checked).toBe(false);
    expect(apply.disabled).toBe(true);
    expect(bulkTriageReviewQueueItems).not.toHaveBeenCalled();

    fireEvent.click(confirm);
    fireEvent.click(apply);
    await waitFor(() =>
      expect(bulkTriageReviewQueueItems).toHaveBeenCalledWith(
        "queue-1",
        expect.objectContaining({
          item_ids: ["pending-1", "active-2"],
          action: "skip",
          reason: "Cannot inspect polyp margins",
        }),
      ),
    );
  });

  it("does not revive confirmation after eligibility returns", () => {
    const rerenderItems = mountChangingItems();
    fireEvent.change(screen.getByLabelText("Bulk triage reviewer label"), {
      target: { value: "lab reviewer" },
    });
    fireEvent.change(screen.getByLabelText("Triage action"), {
      target: { value: "complete" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Select eligible on page/ }),
    );
    const confirm = screen.getByLabelText(
      "Confirm manual triage",
    ) as HTMLInputElement;
    const reviewed = screen.getByLabelText(
      "Confirm each item was manually reviewed",
    ) as HTMLInputElement;
    fireEvent.click(confirm);
    fireEvent.click(reviewed);
    const apply = screen.getByRole("button", {
      name: "Apply complete to 1 items",
    }) as HTMLButtonElement;
    expect(apply.disabled).toBe(false);

    rerenderItems(
      items.map((item) =>
        item.id === "active-2"
          ? ({ ...item, review_state: "skipped" } as ReviewQueueItem)
          : item,
      ),
    );
    expect(confirm.checked).toBe(false);
    expect(reviewed.checked).toBe(false);
    rerenderItems(items);
    expect(confirm.checked).toBe(false);
    expect(reviewed.checked).toBe(false);
    expect(apply.disabled).toBe(true);
    expect(bulkTriageReviewQueueItems).not.toHaveBeenCalled();
  });
});
