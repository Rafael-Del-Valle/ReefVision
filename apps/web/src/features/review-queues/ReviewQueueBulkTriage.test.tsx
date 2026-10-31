import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  bulkTriageReviewQueueItems,
  type ReviewQueueBulkAction,
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

function responseItems(
  queueId: string,
  action: ReviewQueueBulkAction,
  ids: string[],
): ReviewQueueItem[] {
  const resultingState: ReviewQueueItem["review_state"] = {
    start: "in_progress",
    skip: "skipped",
    return: "pending",
    complete: "completed",
  }[action];
  return ids.map(
    (id) =>
      ({
        ...(items.find((item) => item.id === id) ?? {
          id,
          image_id: id,
          rank_position: 1,
        }),
        id,
        review_queue_id: queueId,
        review_state: resultingState,
      }) as ReviewQueueItem,
  );
}

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
    vi.mocked(bulkTriageReviewQueueItems).mockImplementation(
      async (queueId, payload) => ({
        queue_id: queueId,
        action: payload.action,
        changed_count: 1,
        items: responseItems(queueId, payload.action, payload.item_ids),
        requires_researcher_review: true,
      }),
    );
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

  it.each(["queue", "action", "gate"] as const)(
    "preserves the exact bulk retry when the server response mismatches %s",
    async (mismatch) => {
      vi.mocked(bulkTriageReviewQueueItems)
        .mockImplementationOnce(async (queueId, payload) => ({
          queue_id: mismatch === "queue" ? "wrong-queue" : queueId,
          action: mismatch === "action" ? "skip" : payload.action,
          changed_count: 1,
          items: responseItems(queueId, payload.action, payload.item_ids),
          requires_researcher_review: mismatch !== "gate",
        }))
        .mockImplementationOnce(async (queueId, payload) => ({
          queue_id: queueId,
          action: payload.action,
          changed_count: 0,
          items: responseItems(queueId, payload.action, payload.item_ids),
          requires_researcher_review: true,
        }));
      const invalidate = mount();
      fireEvent.change(screen.getByLabelText("Bulk triage reviewer label"), {
        target: { value: "lab reviewer" },
      });
      fireEvent.click(
        screen.getByRole("button", { name: /Select eligible on page/ }),
      );
      fireEvent.click(screen.getByLabelText("Confirm manual triage"));
      fireEvent.click(
        screen.getByRole("button", { name: "Apply start to 1 items" }),
      );
      const retry = await screen.findByRole("button", {
        name: "Retry identical bulk action",
      });
      const original = vi.mocked(bulkTriageReviewQueueItems).mock.calls[0];
      expect(screen.getByRole("alert").textContent).toContain(
        "Bulk QC response did not match",
      );
      expect(screen.queryByRole("status")).toBeNull();
      expect(invalidate).not.toHaveBeenCalled();

      fireEvent.click(retry);
      await waitFor(() =>
        expect(bulkTriageReviewQueueItems).toHaveBeenCalledTimes(2),
      );
      expect(vi.mocked(bulkTriageReviewQueueItems).mock.calls[1]).toEqual(
        original,
      );
      await waitFor(() =>
        expect(screen.getByRole("status").textContent).toContain(
          "scientific review remains required",
        ),
      );
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: ["review_queue_events", "queue-1"],
      });
    },
  );

  it.each([
    {
      name: "missing item",
      mutate: (rows: ReviewQueueItem[]) => rows.slice(1),
    },
    {
      name: "foreign item",
      mutate: (rows: ReviewQueueItem[]) => [
        { ...rows[0]!, id: "foreign-review-item" },
      ],
    },
    {
      name: "duplicate item",
      mutate: (rows: ReviewQueueItem[]) => [rows[0]!, rows[0]!],
    },
    {
      name: "foreign queue",
      mutate: (rows: ReviewQueueItem[]) => [
        { ...rows[0]!, review_queue_id: "other-queue" },
      ],
    },
    {
      name: "incorrect resulting review state",
      mutate: (rows: ReviewQueueItem[]) => [
        { ...rows[0]!, review_state: "completed" as const },
      ],
    },
  ])(
    "retains original bulk UUID after response with $name",
    async ({ mutate }) => {
      vi.mocked(bulkTriageReviewQueueItems).mockImplementationOnce(
        async (queueId, payload) => ({
          queue_id: queueId,
          action: payload.action,
          changed_count: 1,
          items: mutate(
            responseItems(queueId, payload.action, payload.item_ids),
          ),
          requires_researcher_review: true,
        }),
      );
      const invalidate = mount();
      fireEvent.change(screen.getByLabelText("Bulk triage reviewer label"), {
        target: { value: "lab reviewer" },
      });
      fireEvent.click(
        screen.getByRole("button", { name: /Select eligible on page/ }),
      );
      fireEvent.click(screen.getByLabelText("Confirm manual triage"));
      fireEvent.click(
        screen.getByRole("button", { name: "Apply start to 1 items" }),
      );
      const retry = await screen.findByRole("button", {
        name: "Retry identical bulk action",
      });
      expect(screen.getByRole("alert").textContent).toContain(
        "response item identities",
      );
      expect(invalidate).not.toHaveBeenCalled();
      const original = vi.mocked(bulkTriageReviewQueueItems).mock.calls[0];
      fireEvent.click(retry);
      await waitFor(() =>
        expect(bulkTriageReviewQueueItems).toHaveBeenCalledTimes(2),
      );
      expect(vi.mocked(bulkTriageReviewQueueItems).mock.calls[1]).toEqual(
        original,
      );
      await waitFor(() =>
        expect(screen.getByRole("status").textContent).toContain(
          "scientific review remains required",
        ),
      );
    },
  );

  it.each([-1, 2, 0.5, Number.NaN])(
    "rejects invalid bulk changed count %s without acknowledging a batch",
    async (changedCount) => {
      vi.mocked(bulkTriageReviewQueueItems).mockImplementationOnce(
        async (queueId, payload) => ({
          queue_id: queueId,
          action: payload.action,
          changed_count: changedCount,
          items: responseItems(queueId, payload.action, payload.item_ids),
          requires_researcher_review: true,
        }),
      );
      const invalidate = mount();
      fireEvent.change(screen.getByLabelText("Bulk triage reviewer label"), {
        target: { value: "lab reviewer" },
      });
      fireEvent.click(
        screen.getByRole("button", { name: /Select eligible on page/ }),
      );
      fireEvent.click(screen.getByLabelText("Confirm manual triage"));
      fireEvent.click(
        screen.getByRole("button", { name: "Apply start to 1 items" }),
      );
      await screen.findByRole("button", {
        name: "Retry identical bulk action",
      });
      expect(invalidate).not.toHaveBeenCalled();
      expect(screen.getByRole("alert").textContent).toContain(
        "changed count",
      );
    },
  );

  it("retries uncertain outcomes using exactly the original payload", async () => {
    vi.mocked(bulkTriageReviewQueueItems)
      .mockRejectedValueOnce(new Error("Connection lost"))
      .mockResolvedValueOnce({
        queue_id: "queue-1",
        action: "return",
        changed_count: 1,
        items: responseItems("queue-1", "return", ["skipped-3"]),
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

  it.each([
    { name: "input checksum", change: { input_checksum: "new-checksum" } },
    { name: "QC score", change: { score: 72 } },
    { name: "QC severity", change: { highest_qc_severity: "warning" } },
    {
      name: "item update timestamp",
      change: { updated_at: "2026-10-30T01:00:00Z" },
    },
  ])("invalidates manual completion after $name changes", ({ change }) => {
    const evidenceItems = items.map((item) =>
      item.id === "active-2"
        ? ({
            ...item,
            input_checksum: "original-checksum",
            score: 45,
            highest_qc_severity: null,
            updated_at: "2026-10-30T00:00:00Z",
          } as ReviewQueueItem)
        : item,
    );
    const rerenderItems = mountChangingItems(evidenceItems);
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
      evidenceItems.map((item) =>
        item.id === "active-2"
          ? ({ ...item, ...change } as ReviewQueueItem)
          : item,
      ),
    );
    expect(confirm.checked).toBe(false);
    expect(reviewed.checked).toBe(false);
    expect(apply.disabled).toBe(true);
    expect(bulkTriageReviewQueueItems).not.toHaveBeenCalled();

    // Returning to the original evidence cannot revive a prior approval.
    rerenderItems(evidenceItems);
    expect(confirm.checked).toBe(false);
    expect(reviewed.checked).toBe(false);
    expect(apply.disabled).toBe(true);
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
  it("keeps uncertain bulk retries attached to their original queue across navigation", async () => {
    vi.mocked(bulkTriageReviewQueueItems)
      .mockRejectedValueOnce(new Error("Response lost for queue A"))
      .mockResolvedValueOnce({
        queue_id: "queue-b",
        action: "start",
        changed_count: 1,
        items: responseItems("queue-b", "start", ["pending-1"]),
        requires_researcher_review: true,
      })
      .mockResolvedValueOnce({
        queue_id: "queue-a",
        action: "start",
        changed_count: 1,
        items: responseItems("queue-a", "start", ["pending-1"]),
        requires_researcher_review: true,
      });
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const view = (id: string) => (
      <QueryClientProvider client={client}>
        <ReviewQueueBulkTriage queueId={id} items={items} />
      </QueryClientProvider>
    );
    const { rerender } = render(view("queue-a"));
    fireEvent.change(screen.getByLabelText("Bulk triage reviewer label"), {
      target: { value: "reviewer-a" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Select eligible on page/ }),
    );
    fireEvent.click(screen.getByLabelText("Confirm manual triage"));
    fireEvent.click(
      screen.getByRole("button", { name: "Apply start to 1 items" }),
    );
    await screen.findByRole("button", { name: "Retry identical bulk action" });
    const original = vi.mocked(bulkTriageReviewQueueItems).mock.calls[0];

    rerender(view("queue-b"));
    expect(
      screen.queryByRole("button", { name: "Retry identical bulk action" }),
    ).toBeNull();
    fireEvent.change(screen.getByLabelText("Bulk triage reviewer label"), {
      target: { value: "reviewer-b" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Select eligible on page/ }),
    );
    fireEvent.click(screen.getByLabelText("Confirm manual triage"));
    fireEvent.click(
      screen.getByRole("button", { name: "Apply start to 1 items" }),
    );
    await waitFor(() =>
      expect(bulkTriageReviewQueueItems).toHaveBeenCalledTimes(2),
    );
    expect(vi.mocked(bulkTriageReviewQueueItems).mock.calls[1][0]).toBe(
      "queue-b",
    );

    rerender(view("queue-a"));
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Retry identical bulk action",
      }),
    );
    await waitFor(() =>
      expect(bulkTriageReviewQueueItems).toHaveBeenCalledTimes(3),
    );
    expect(vi.mocked(bulkTriageReviewQueueItems).mock.calls[2]).toEqual(
      original,
    );
  });

  it("does not display an old queue's delayed success or invalidate the new queue", async () => {
    let finish!: () => void;
    vi.mocked(bulkTriageReviewQueueItems).mockImplementationOnce(async () => {
      await new Promise<void>((resolve) => {
        finish = resolve;
      });
      return {
        queue_id: "queue-a",
        action: "start",
        changed_count: 1,
        items: responseItems("queue-a", "start", ["pending-1"]),
        requires_researcher_review: true,
      };
    });
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const view = (id: string) => (
      <QueryClientProvider client={client}>
        <ReviewQueueBulkTriage queueId={id} items={items} />
      </QueryClientProvider>
    );
    const { rerender } = render(view("queue-a"));
    fireEvent.change(screen.getByLabelText("Bulk triage reviewer label"), {
      target: { value: "reviewer-a" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Select eligible on page/ }),
    );
    fireEvent.click(screen.getByLabelText("Confirm manual triage"));
    fireEvent.click(
      screen.getByRole("button", { name: "Apply start to 1 items" }),
    );
    await waitFor(() =>
      expect(bulkTriageReviewQueueItems).toHaveBeenCalledTimes(1),
    );
    rerender(view("queue-b"));
    finish();
    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: ["review_queue_events", "queue-a"],
      }),
    );
    expect(
      screen.queryByText(/items updated; scientific review remains required/),
    ).toBeNull();
    expect(invalidate).not.toHaveBeenCalledWith({
      queryKey: ["review_queue_items", "queue-b"],
    });
  });
  it("requires explicit risk approval before discarding an uncertain bulk UUID", async () => {
    vi.mocked(bulkTriageReviewQueueItems).mockRejectedValueOnce(
      new Error("Response lost after commit"),
    );
    const invalidate = mount();
    fireEvent.change(screen.getByLabelText("Bulk triage reviewer label"), {
      target: { value: "lab reviewer" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Select eligible on page/ }),
    );
    fireEvent.click(screen.getByLabelText("Confirm manual triage"));
    fireEvent.click(
      screen.getByRole("button", { name: "Apply start to 1 items" }),
    );
    await screen.findByRole("button", { name: "Retry identical bulk action" });
    const original = vi.mocked(bulkTriageReviewQueueItems).mock.calls[0];
    expect(
      screen.queryByRole("button", { name: "Discard and refresh" }),
    ).toBeNull();

    fireEvent.click(
      screen.getByRole("button", { name: "Review discard risk" }),
    );
    expect(screen.getByText(/may already have been committed/i)).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Retry identical bulk action" }),
    ).toBeTruthy();
    expect(vi.mocked(bulkTriageReviewQueueItems).mock.calls[0]).toEqual(
      original,
    );
    expect(bulkTriageReviewQueueItems).toHaveBeenCalledTimes(1);

    fireEvent.click(
      screen.getByRole("button", { name: "Discard and refresh" }),
    );
    expect(
      screen.queryByRole("button", { name: "Retry identical bulk action" }),
    ).toBeNull();
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
    expect(bulkTriageReviewQueueItems).toHaveBeenCalledTimes(1);
  });

  it("invalidates bulk discard approval across A to B to A navigation", async () => {
    vi.mocked(bulkTriageReviewQueueItems)
      .mockRejectedValueOnce(new Error("Response lost for queue A"))
      .mockResolvedValueOnce({
        queue_id: "queue-a",
        action: "start",
        changed_count: 0,
        items: responseItems("queue-a", "start", ["pending-1"]),
        requires_researcher_review: true,
      });
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const view = (id: string) => (
      <QueryClientProvider client={client}>
        <ReviewQueueBulkTriage queueId={id} items={items} />
      </QueryClientProvider>
    );
    const { rerender } = render(view("queue-a"));
    fireEvent.change(screen.getByLabelText("Bulk triage reviewer label"), {
      target: { value: "reviewer-a" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Select eligible on page/ }),
    );
    fireEvent.click(screen.getByLabelText("Confirm manual triage"));
    fireEvent.click(
      screen.getByRole("button", { name: "Apply start to 1 items" }),
    );
    await screen.findByRole("button", { name: "Retry identical bulk action" });
    const original = vi.mocked(bulkTriageReviewQueueItems).mock.calls[0];
    fireEvent.click(
      screen.getByRole("button", { name: "Review discard risk" }),
    );
    expect(
      screen.getByRole("button", { name: "Discard and refresh" }),
    ).toBeTruthy();

    rerender(view("queue-b"));
    expect(
      screen.queryByRole("button", { name: "Discard and refresh" }),
    ).toBeNull();
    rerender(view("queue-a"));
    expect(
      screen.queryByRole("button", { name: "Discard and refresh" }),
    ).toBeNull();
    expect(
      screen.getByRole("button", { name: "Review discard risk" }),
    ).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Retry identical bulk action" }),
    );
    await waitFor(() =>
      expect(bulkTriageReviewQueueItems).toHaveBeenCalledTimes(2),
    );
    expect(vi.mocked(bulkTriageReviewQueueItems).mock.calls[1]).toEqual(
      original,
    );
  });
});
