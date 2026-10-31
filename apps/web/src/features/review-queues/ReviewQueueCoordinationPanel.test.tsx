import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { addReviewQueueEvent, getReviewQueueEvents } from "../../api/client";
import { ReviewQueueCoordinationPanel } from "./ReviewQueueCoordinationPanel";

vi.mock("../../api/client", () => ({
  addReviewQueueEvent: vi.fn(),
  getReviewQueueEvents: vi.fn(),
}));

function mount(onClose = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={client}>
      <ReviewQueueCoordinationPanel
        queueId="queue-1"
        itemId="item-1"
        onClose={onClose}
      />
    </QueryClientProvider>,
  );
  return onClose;
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

  it("requires explicit confirmation before discarding unsent biological notes", async () => {
    const onClose = mount();
    await screen.findByText("Assigned reviewer: Unassigned");
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Unsubmitted coral condition note" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Close coordination" }));
    expect(onClose).not.toHaveBeenCalled();
    expect(
      screen.getByRole("group", { name: "Discard unsent coordination drafts" }),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Continue editing" }));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Review comment")).toHaveProperty(
      "value",
      "Unsubmitted coral condition note",
    );
    fireEvent.click(screen.getByRole("button", { name: "Close coordination" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Close without saving drafts" }),
    );
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(addReviewQueueEvent).not.toHaveBeenCalled();
  });

  it("keeps an uncertain audit UUID available until the researcher resolves it", async () => {
    vi.mocked(addReviewQueueEvent).mockRejectedValueOnce(
      new Error("Uncertain event delivery"),
    );
    const onClose = mount();
    await screen.findByText("Assigned reviewer: Unassigned");
    fireEvent.change(screen.getByLabelText("Your local reviewer label"), {
      target: { value: "researcher-a" },
    });
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Tentacle condition needs inspection" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
    await screen.findByText("Uncertain event delivery");
    const close = screen.getByRole("button", { name: "Close coordination" });
    expect(close).toHaveProperty("disabled", true);
    fireEvent.click(close);
    expect(onClose).not.toHaveBeenCalled();
    const originalUuid =
      vi.mocked(addReviewQueueEvent).mock.calls[0][2].client_request_id;
    fireEvent.click(screen.getByRole("button", { name: "Retry event" }));
    await waitFor(() => expect(addReviewQueueEvent).toHaveBeenCalledTimes(2));
    expect(
      vi.mocked(addReviewQueueEvent).mock.calls[1][2].client_request_id,
    ).toBe(originalUuid);
    await waitFor(() => expect(close).toHaveProperty("disabled", false));
    fireEvent.click(close);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not carry a draft-discard confirmation onto another review item", async () => {
    const onClose = vi.fn();
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const view = (queueId: string, itemId: string) => (
      <QueryClientProvider client={client}>
        <ReviewQueueCoordinationPanel
          queueId={queueId}
          itemId={itemId}
          onClose={onClose}
        />
      </QueryClientProvider>
    );
    const { rerender } = render(view("queue-a", "item-a"));
    await screen.findByText("Assigned reviewer: Unassigned");
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Unsent A note" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Close coordination" }));
    expect(
      screen.getByRole("group", { name: "Discard unsent coordination drafts" }),
    ).toBeTruthy();

    rerender(view("queue-b", "item-b"));
    expect(
      screen.queryByRole("group", {
        name: "Discard unsent coordination drafts",
      }),
    ).toBeNull();
    rerender(view("queue-a", "item-a"));
    expect(screen.getByLabelText("Review comment")).toHaveProperty(
      "value",
      "Unsent A note",
    );
    expect(
      screen.getByRole("group", { name: "Discard unsent coordination drafts" }),
    ).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
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

  it("preserves a newer comment draft after the prior comment succeeds", async () => {
    let resolveEvent!: (
      value: Awaited<ReturnType<typeof addReviewQueueEvent>>,
    ) => void;
    const pending = new Promise<
      Awaited<ReturnType<typeof addReviewQueueEvent>>
    >((resolve) => {
      resolveEvent = resolve;
    });
    vi.mocked(addReviewQueueEvent).mockReturnValueOnce(pending);
    mount();
    await screen.findByText("Assigned reviewer: Unassigned");
    fireEvent.change(screen.getByLabelText("Your local reviewer label"), {
      target: { value: "scientist" },
    });
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Original observation" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
    await waitFor(() => expect(addReviewQueueEvent).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "New observation draft" },
    });
    await act(async () => {
      resolveEvent({} as Awaited<ReturnType<typeof addReviewQueueEvent>>);
      await pending;
    });
    expect(screen.getByLabelText("Review comment")).toHaveProperty(
      "value",
      "New observation draft",
    );
    expect(addReviewQueueEvent).toHaveBeenCalledTimes(1);
  });

  it("retries an uncertain assignment without deleting a newer assignee draft", async () => {
    vi.mocked(addReviewQueueEvent)
      .mockRejectedValueOnce(new Error("Connection interrupted"))
      .mockResolvedValueOnce(
        {} as Awaited<ReturnType<typeof addReviewQueueEvent>>,
      );
    mount();
    await screen.findByText("Assigned reviewer: Unassigned");
    fireEvent.change(screen.getByLabelText("Your local reviewer label"), {
      target: { value: "scientist" },
    });
    fireEvent.change(screen.getByLabelText("Reviewer to assign"), {
      target: { value: "reviewer-one" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Assign reviewer" }));
    await screen.findByRole("button", { name: "Retry event" });
    fireEvent.change(screen.getByLabelText("Reviewer to assign"), {
      target: { value: "reviewer-two" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Retry event" }));
    await waitFor(() => expect(addReviewQueueEvent).toHaveBeenCalledTimes(2));
    const calls = vi.mocked(addReviewQueueEvent).mock.calls;
    expect(calls[1][2].assignee).toBe("reviewer-one");
    expect(calls[1][2].client_request_id).toBe(calls[0][2].client_request_id);
    await waitFor(() =>
      expect(screen.getByLabelText("Reviewer to assign")).toHaveProperty(
        "value",
        "reviewer-two",
      ),
    );
  });

  it("keeps an edit-and-reverted comment draft after an older response", async () => {
    let resolveEvent!: (
      value: Awaited<ReturnType<typeof addReviewQueueEvent>>,
    ) => void;
    const pending = new Promise<
      Awaited<ReturnType<typeof addReviewQueueEvent>>
    >((resolve) => {
      resolveEvent = resolve;
    });
    vi.mocked(addReviewQueueEvent).mockReturnValueOnce(pending);
    mount();
    await screen.findByText("Assigned reviewer: Unassigned");
    fireEvent.change(screen.getByLabelText("Your local reviewer label"), {
      target: { value: "scientist" },
    });
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Observation A" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
    await waitFor(() => expect(addReviewQueueEvent).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Observation B" },
    });
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Observation A" },
    });
    await act(async () => {
      resolveEvent({} as Awaited<ReturnType<typeof addReviewQueueEvent>>);
      await pending;
    });
    expect(screen.getByLabelText("Review comment")).toHaveProperty(
      "value",
      "Observation A",
    );
  });

  it("keeps comment draft after actor switch", async () => {
    let resolveEvent!: (
      value: Awaited<ReturnType<typeof addReviewQueueEvent>>,
    ) => void;
    const pending = new Promise<
      Awaited<ReturnType<typeof addReviewQueueEvent>>
    >((resolve) => {
      resolveEvent = resolve;
    });
    vi.mocked(addReviewQueueEvent).mockReturnValueOnce(pending);
    mount();
    await screen.findByText("Assigned reviewer: Unassigned");
    fireEvent.change(screen.getByLabelText("Your local reviewer label"), {
      target: { value: "reviewer-one" },
    });
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Unsubmitted observation" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
    await waitFor(() => expect(addReviewQueueEvent).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByLabelText("Your local reviewer label"), {
      target: { value: "reviewer-two" },
    });
    await act(async () => {
      resolveEvent({} as Awaited<ReturnType<typeof addReviewQueueEvent>>);
      await pending;
    });
    expect(vi.mocked(addReviewQueueEvent).mock.calls[0][2].actor).toBe(
      "reviewer-one",
    );
    expect(screen.getByLabelText("Review comment")).toHaveProperty(
      "value",
      "Unsubmitted observation",
    );
  });

  it("keeps assignee draft after actor switch", async () => {
    let resolveEvent!: (
      value: Awaited<ReturnType<typeof addReviewQueueEvent>>,
    ) => void;
    const pending = new Promise<
      Awaited<ReturnType<typeof addReviewQueueEvent>>
    >((resolve) => {
      resolveEvent = resolve;
    });
    vi.mocked(addReviewQueueEvent).mockReturnValueOnce(pending);
    mount();
    await screen.findByText("Assigned reviewer: Unassigned");
    fireEvent.change(screen.getByLabelText("Your local reviewer label"), {
      target: { value: "reviewer-one" },
    });
    fireEvent.change(screen.getByLabelText("Reviewer to assign"), {
      target: { value: "scientist-three" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Assign reviewer" }));
    await waitFor(() => expect(addReviewQueueEvent).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByLabelText("Your local reviewer label"), {
      target: { value: "reviewer-two" },
    });
    await act(async () => {
      resolveEvent({} as Awaited<ReturnType<typeof addReviewQueueEvent>>);
      await pending;
    });
    expect(vi.mocked(addReviewQueueEvent).mock.calls[0][2].actor).toBe(
      "reviewer-one",
    );
    expect(screen.getByLabelText("Reviewer to assign")).toHaveProperty(
      "value",
      "scientist-three",
    );
  });

  it("retries under original actor without clearing new draft", async () => {
    vi.mocked(addReviewQueueEvent)
      .mockRejectedValueOnce(new Error("Connection interrupted"))
      .mockResolvedValueOnce(
        {} as Awaited<ReturnType<typeof addReviewQueueEvent>>,
      );
    mount();
    await screen.findByText("Assigned reviewer: Unassigned");
    fireEvent.change(screen.getByLabelText("Your local reviewer label"), {
      target: { value: "reviewer-one" },
    });
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Original observation" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
    await screen.findByRole("button", { name: "Retry event" });
    fireEvent.change(screen.getByLabelText("Your local reviewer label"), {
      target: { value: "reviewer-two" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Retry event" }));
    await waitFor(() => expect(addReviewQueueEvent).toHaveBeenCalledTimes(2));
    const calls = vi.mocked(addReviewQueueEvent).mock.calls;
    expect(calls[1][2]).toEqual(calls[0][2]);
    expect(calls[1][2].actor).toBe("reviewer-one");
    await waitFor(() =>
      expect(screen.getByLabelText("Review comment")).toHaveProperty(
        "value",
        "Original observation",
      ),
    );
  });

  it("keeps a delayed comment on its original queue after the panel changes items", async () => {
    let resolveOld!: (
      value: Awaited<ReturnType<typeof addReviewQueueEvent>>,
    ) => void;
    const pendingOld = new Promise<
      Awaited<ReturnType<typeof addReviewQueueEvent>>
    >((resolve) => {
      resolveOld = resolve;
    });
    vi.mocked(addReviewQueueEvent).mockReturnValueOnce(pendingOld);
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const view = (queueId: string, itemId: string) => (
      <QueryClientProvider client={client}>
        <ReviewQueueCoordinationPanel
          queueId={queueId}
          itemId={itemId}
          onClose={vi.fn()}
        />
      </QueryClientProvider>
    );
    const { rerender } = render(view("queue-a", "item-a"));
    await screen.findByText("Assigned reviewer: Unassigned");
    fireEvent.change(screen.getByLabelText("Your local reviewer label"), {
      target: { value: "reviewer-a" },
    });
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Observation for A" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
    await waitFor(() => expect(addReviewQueueEvent).toHaveBeenCalledTimes(1));

    rerender(view("queue-b", "item-b"));
    fireEvent.change(screen.getByLabelText("Your local reviewer label"), {
      target: { value: "reviewer-b" },
    });
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Observation for B" },
    });
    await act(async () => {
      resolveOld({} as Awaited<ReturnType<typeof addReviewQueueEvent>>);
      await pendingOld;
    });
    expect(addReviewQueueEvent).toHaveBeenCalledWith(
      "queue-a",
      "item-a",
      expect.objectContaining({
        actor: "reviewer-a",
        comment: "Observation for A",
      }),
    );
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["review_queue_events", "queue-a", "item-a"],
    });
    expect(invalidate).not.toHaveBeenCalledWith({
      queryKey: ["review_queue_events", "queue-b", "item-b"],
    });
    expect(screen.getByLabelText("Review comment")).toHaveProperty(
      "value",
      "Observation for B",
    );
    fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
    await waitFor(() => expect(addReviewQueueEvent).toHaveBeenCalledTimes(2));
    expect(addReviewQueueEvent).toHaveBeenLastCalledWith(
      "queue-b",
      "item-b",
      expect.objectContaining({
        actor: "reviewer-b",
        comment: "Observation for B",
      }),
    );
  });

  it("does not clear a draft when an old response returns after A-B-A navigation", async () => {
    let resolveOld!: (
      value: Awaited<ReturnType<typeof addReviewQueueEvent>>,
    ) => void;
    const pendingOld = new Promise<
      Awaited<ReturnType<typeof addReviewQueueEvent>>
    >((resolve) => {
      resolveOld = resolve;
    });
    vi.mocked(addReviewQueueEvent).mockReturnValueOnce(pendingOld);
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const view = (queueId: string, itemId: string) => (
      <QueryClientProvider client={client}>
        <ReviewQueueCoordinationPanel
          queueId={queueId}
          itemId={itemId}
          onClose={vi.fn()}
        />
      </QueryClientProvider>
    );
    const { rerender } = render(view("queue-a", "item-a"));
    await screen.findByText("Assigned reviewer: Unassigned");
    fireEvent.change(screen.getByLabelText("Your local reviewer label"), {
      target: { value: "reviewer-a" },
    });
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Keep this draft" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
    await waitFor(() => expect(addReviewQueueEvent).toHaveBeenCalledTimes(1));
    rerender(view("queue-b", "item-b"));
    rerender(view("queue-a", "item-a"));
    await act(async () => {
      resolveOld({} as Awaited<ReturnType<typeof addReviewQueueEvent>>);
      await pendingOld;
    });
    expect(screen.getByLabelText("Review comment")).toHaveProperty(
      "value",
      "Keep this draft",
    );
  });

  it("keeps unsent reviewer notes and attribution scoped to their review item", async () => {
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const view = (queueId: string, itemId: string) => (
      <QueryClientProvider client={client}>
        <ReviewQueueCoordinationPanel
          queueId={queueId}
          itemId={itemId}
          onClose={vi.fn()}
        />
      </QueryClientProvider>
    );
    const { rerender } = render(view("queue-a", "item-a"));
    await screen.findByText("Assigned reviewer: Unassigned");
    fireEvent.change(screen.getByLabelText("Your local reviewer label"), {
      target: { value: "researcher-a" },
    });
    fireEvent.change(screen.getByLabelText("Reviewer to assign"), {
      target: { value: "assignee-a" },
    });
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Unsent biological note for A" },
    });

    rerender(view("queue-b", "item-b"));
    expect(screen.getByLabelText("Your local reviewer label")).toHaveProperty(
      "value",
      "",
    );
    expect(screen.getByLabelText("Reviewer to assign")).toHaveProperty(
      "value",
      "",
    );
    expect(screen.getByLabelText("Review comment")).toHaveProperty("value", "");
    expect(screen.getByRole("button", { name: "Add comment" })).toHaveProperty(
      "disabled",
      true,
    );
    fireEvent.change(screen.getByLabelText("Your local reviewer label"), {
      target: { value: "researcher-b" },
    });
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Note for B" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
    await waitFor(() => expect(addReviewQueueEvent).toHaveBeenCalledTimes(1));
    expect(addReviewQueueEvent).toHaveBeenCalledWith(
      "queue-b",
      "item-b",
      expect.objectContaining({
        actor: "researcher-b",
        comment: "Note for B",
      }),
    );

    rerender(view("queue-a", "item-a"));
    expect(screen.getByLabelText("Your local reviewer label")).toHaveProperty(
      "value",
      "researcher-a",
    );
    expect(screen.getByLabelText("Reviewer to assign")).toHaveProperty(
      "value",
      "assignee-a",
    );
    expect(screen.getByLabelText("Review comment")).toHaveProperty(
      "value",
      "Unsent biological note for A",
    );
    expect(addReviewQueueEvent).toHaveBeenCalledTimes(1);
  });

  it("resets history pagination for a new item and restores it on return", async () => {
    vi.mocked(getReviewQueueEvents).mockImplementation(
      async (_queueId, _itemId, page) => ({
        items: [],
        total: 101,
        page: page ?? 1,
        page_size: 50,
        current_assignee: null,
        requires_researcher_review: true,
      }),
    );
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const view = (queueId: string, itemId: string) => (
      <QueryClientProvider client={client}>
        <ReviewQueueCoordinationPanel
          queueId={queueId}
          itemId={itemId}
          onClose={vi.fn()}
        />
      </QueryClientProvider>
    );
    const { rerender } = render(view("queue-a", "item-a"));
    await screen.findByText("Page 1");
    fireEvent.click(screen.getByRole("button", { name: "Next events" }));
    await screen.findByText("Page 2");
    expect(getReviewQueueEvents).toHaveBeenCalledWith(
      "queue-a",
      "item-a",
      2,
      expect.anything(),
    );

    rerender(view("queue-b", "item-b"));
    await screen.findByText("Page 1");
    expect(getReviewQueueEvents).toHaveBeenCalledWith(
      "queue-b",
      "item-b",
      1,
      expect.anything(),
    );
    rerender(view("queue-a", "item-a"));
    await screen.findByText("Page 2");
  });

  it("restores an uncertain event retry after delayed failure across item navigation", async () => {
    let rejectOriginal!: (reason: Error) => void;
    const pendingOriginal = new Promise<
      Awaited<ReturnType<typeof addReviewQueueEvent>>
    >((_, reject) => {
      rejectOriginal = reject;
    });
    vi.mocked(addReviewQueueEvent)
      .mockReturnValueOnce(pendingOriginal)
      .mockResolvedValueOnce(
        {} as Awaited<ReturnType<typeof addReviewQueueEvent>>,
      );
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const view = (queueId: string, itemId: string) => (
      <QueryClientProvider client={client}>
        <ReviewQueueCoordinationPanel
          queueId={queueId}
          itemId={itemId}
          onClose={vi.fn()}
        />
      </QueryClientProvider>
    );
    const { rerender } = render(view("queue-a", "item-a"));
    await screen.findByText("Assigned reviewer: Unassigned");
    fireEvent.change(screen.getByLabelText("Your local reviewer label"), {
      target: { value: "researcher-a" },
    });
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Original observation for A" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
    await waitFor(() => expect(addReviewQueueEvent).toHaveBeenCalledTimes(1));

    rerender(view("queue-b", "item-b"));
    await act(async () => {
      rejectOriginal(new Error("Uncertain delivery for A"));
      await pendingOriginal.catch(() => undefined);
    });
    expect(screen.queryByRole("button", { name: "Retry event" })).toBeNull();
    expect(screen.queryByText("Uncertain delivery for A")).toBeNull();

    rerender(view("queue-a", "item-a"));
    expect(await screen.findByText("Uncertain delivery for A")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry event" }));
    await waitFor(() => expect(addReviewQueueEvent).toHaveBeenCalledTimes(2));
    const calls = vi.mocked(addReviewQueueEvent).mock.calls;
    expect(calls[1]).toEqual(calls[0]);
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Retry event" })).toBeNull(),
    );
  });

  it("keeps separate uncertain retries and reviewer identities for two items", async () => {
    vi.mocked(addReviewQueueEvent)
      .mockRejectedValueOnce(new Error("Uncertain A"))
      .mockRejectedValueOnce(new Error("Uncertain B"))
      .mockResolvedValue({} as Awaited<ReturnType<typeof addReviewQueueEvent>>);
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const view = (queueId: string, itemId: string) => (
      <QueryClientProvider client={client}>
        <ReviewQueueCoordinationPanel
          queueId={queueId}
          itemId={itemId}
          onClose={vi.fn()}
        />
      </QueryClientProvider>
    );
    const { rerender } = render(view("queue-a", "item-a"));
    await screen.findByText("Assigned reviewer: Unassigned");
    fireEvent.change(screen.getByLabelText("Your local reviewer label"), {
      target: { value: "reviewer-a" },
    });
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Note A" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
    await screen.findByText("Uncertain A");

    rerender(view("queue-b", "item-b"));
    expect(screen.queryByText("Uncertain A")).toBeNull();
    fireEvent.change(screen.getByLabelText("Your local reviewer label"), {
      target: { value: "reviewer-b" },
    });
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Note B" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
    await screen.findByText("Uncertain B");

    rerender(view("queue-a", "item-a"));
    expect(screen.getByText("Uncertain A")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry event" }));
    await waitFor(() => expect(addReviewQueueEvent).toHaveBeenCalledTimes(3));
    expect(vi.mocked(addReviewQueueEvent).mock.calls[2]).toEqual(
      vi.mocked(addReviewQueueEvent).mock.calls[0],
    );
    await waitFor(() => expect(screen.queryByText("Uncertain A")).toBeNull());

    rerender(view("queue-b", "item-b"));
    expect(screen.getByText("Uncertain B")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry event" }));
    await waitFor(() => expect(addReviewQueueEvent).toHaveBeenCalledTimes(4));
    expect(vi.mocked(addReviewQueueEvent).mock.calls[3]).toEqual(
      vi.mocked(addReviewQueueEvent).mock.calls[1],
    );
    expect(vi.mocked(addReviewQueueEvent).mock.calls[0][2].actor).toBe(
      "reviewer-a",
    );
    expect(vi.mocked(addReviewQueueEvent).mock.calls[1][2].actor).toBe(
      "reviewer-b",
    );
  });
});
