import { isTauri } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
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

vi.mock("@tauri-apps/api/core", () => ({ isTauri: vi.fn() }));
vi.mock("@tauri-apps/api/window", () => ({ getCurrentWindow: vi.fn() }));
vi.mock("../../api/client", () => ({
  addReviewQueueEvent: vi.fn(),
  getReviewQueueEvents: vi.fn(),
}));

function mount() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={client}>
      <ReviewQueueCoordinationPanel
        queueId="queue-a"
        itemId="coral-a"
        onClose={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

describe("native QC window close protection", () => {
  let closeHandler:
    ((event: { preventDefault: () => void }) => void) | undefined;
  let unlisten: () => void;
  let onCloseRequested: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    closeHandler = undefined;
    unlisten = vi.fn(() => undefined);
    onCloseRequested = vi.fn(
      async (callback: (event: { preventDefault: () => void }) => void) => {
        closeHandler = callback;
        return unlisten;
      },
    );
    vi.mocked(isTauri).mockReturnValue(true);
    vi.mocked(getCurrentWindow).mockReturnValue({
      onCloseRequested,
    } as unknown as ReturnType<typeof getCurrentWindow>);
    vi.mocked(getReviewQueueEvents).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 50,
      current_assignee: null,
      requires_researcher_review: true,
    });
  });

  it("prevents native close for an unsent coral note and unregisters after clearing", async () => {
    mount();
    await screen.findByText("Assigned reviewer: Unassigned");
    expect(onCloseRequested).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Unsent polyp health observation" },
    });
    await waitFor(() => expect(onCloseRequested).toHaveBeenCalledTimes(1));
    const preventDefault = vi.fn();
    act(() => closeHandler?.({ preventDefault }));
    expect(preventDefault).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Desktop window close was blocked/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "" },
    });
    await waitFor(() => expect(unlisten).toHaveBeenCalledTimes(1));
    const afterCleanup = vi.fn();
    act(() => closeHandler?.({ preventDefault: afterCleanup }));
    expect(afterCleanup).not.toHaveBeenCalled();
    expect(addReviewQueueEvent).not.toHaveBeenCalled();
  });

  it("protects an in-flight unassignment even with no unsent note", async () => {
    vi.mocked(getReviewQueueEvents).mockResolvedValueOnce({
      items: [],
      total: 0,
      page: 1,
      page_size: 50,
      current_assignee: "scientist-a",
      requires_researcher_review: true,
    });
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
    await screen.findByText("Assigned reviewer: scientist-a");
    fireEvent.change(screen.getByLabelText("Your local reviewer label"), {
      target: { value: "researcher" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Unassign reviewer" }));
    await waitFor(() => expect(onCloseRequested).toHaveBeenCalledTimes(1));
    const preventDefault = vi.fn();
    act(() => closeHandler?.({ preventDefault }));
    expect(preventDefault).toHaveBeenCalledTimes(1);
    const [queueId, itemId, payload] =
      vi.mocked(addReviewQueueEvent).mock.calls[0]!;
    await act(async () => {
      resolveEvent({
        id: "event-1",
        project_id: "project-a",
        review_queue_id: queueId,
        review_queue_item_id: itemId,
        client_request_id: payload.client_request_id,
        event_type: payload.event_type,
        actor: payload.actor,
        comment: null,
        assignee: null,
        created_at: "2026-10-31T12:00:00Z",
      });
      await pending;
    });
    await waitFor(() => expect(unlisten).toHaveBeenCalledTimes(1));
  });

  it("never subscribes to native close in a browser", async () => {
    vi.mocked(isTauri).mockReturnValue(false);
    mount();
    await screen.findByText("Assigned reviewer: Unassigned");
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Unsent note" },
    });
    expect(getCurrentWindow).not.toHaveBeenCalled();
  });

  it("removes a late asynchronous listener after the note is cleared", async () => {
    let resolveSubscription!: (stop: () => void) => void;
    const subscription = new Promise<() => void>((resolve) => {
      resolveSubscription = resolve;
    });
    onCloseRequested.mockImplementationOnce(
      async (callback: (event: { preventDefault: () => void }) => void) => {
        closeHandler = callback;
        return subscription;
      },
    );
    mount();
    await screen.findByText("Assigned reviewer: Unassigned");
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Short-lived unsent note" },
    });
    await waitFor(() => expect(onCloseRequested).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "" },
    });
    await act(async () => {
      resolveSubscription(unlisten);
      await subscription;
    });
    await waitFor(() => expect(unlisten).toHaveBeenCalledTimes(1));
    const preventDefault = vi.fn();
    act(() => closeHandler?.({ preventDefault }));
    expect(preventDefault).not.toHaveBeenCalled();
  });

  it("warns when native close interception cannot be registered", async () => {
    onCloseRequested.mockRejectedValueOnce(new Error("Native listener failed"));
    mount();
    await screen.findByText("Assigned reviewer: Unassigned");
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Unsent biological record" },
    });
    expect(
      await screen.findByText(
        /Desktop close protection could not be registered/,
      ),
    ).toBeTruthy();
  });

  it("retries failed native close interception without discarding a biological draft", async () => {
    onCloseRequested.mockRejectedValueOnce(new Error("Native listener failed"));
    mount();
    await screen.findByText("Assigned reviewer: Unassigned");
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Unsent coral tissue condition" },
    });
    const retry = await screen.findByRole("button", {
      name: "Retry desktop close protection",
    });
    expect(onCloseRequested).toHaveBeenCalledTimes(1);
    fireEvent.click(retry);
    await waitFor(() => expect(onCloseRequested).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(
        screen.queryByRole("button", {
          name: "Retry desktop close protection",
        }),
      ).toBeNull(),
    );
    const preventDefault = vi.fn();
    act(() => closeHandler?.({ preventDefault }));
    expect(preventDefault).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Review comment")).toHaveProperty(
      "value",
      "Unsent coral tissue condition",
    );
    expect(addReviewQueueEvent).not.toHaveBeenCalled();
  });

  it("continues blocking native close for a hidden draft after A to B navigation", async () => {
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const view = (itemId: string) => (
      <QueryClientProvider client={client}>
        <ReviewQueueCoordinationPanel
          queueId="queue-a"
          itemId={itemId}
          onClose={vi.fn()}
        />
      </QueryClientProvider>
    );
    const { rerender } = render(view("coral-a"));
    await screen.findByText("Assigned reviewer: Unassigned");
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Hidden polyp activity note for coral A" },
    });
    await waitFor(() => expect(onCloseRequested).toHaveBeenCalledTimes(1));

    rerender(view("coral-b"));
    await screen.findByText("Assigned reviewer: Unassigned");
    expect(screen.getByLabelText("Review comment")).toHaveProperty("value", "");
    const preventDefault = vi.fn();
    act(() => closeHandler?.({ preventDefault }));
    expect(preventDefault).toHaveBeenCalledTimes(1);
    expect(unlisten).not.toHaveBeenCalled();

    rerender(view("coral-a"));
    expect(screen.getByLabelText("Review comment")).toHaveProperty(
      "value",
      "Hidden polyp activity note for coral A",
    );
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "" },
    });
    await waitFor(() => expect(unlisten).toHaveBeenCalledTimes(1));
    expect(addReviewQueueEvent).not.toHaveBeenCalled();
  });

  it.each(["window accessor", "listener registration"])(
    "recovers from synchronous native close %s failure without losing a coral note",
    async (failure) => {
      if (failure === "window accessor") {
        vi.mocked(getCurrentWindow).mockImplementationOnce(() => {
          throw new Error("Desktop bridge not ready");
        });
      } else {
        onCloseRequested.mockImplementationOnce(() => {
          throw new Error("Native close listener unavailable");
        });
      }
      mount();
      await screen.findByText("Assigned reviewer: Unassigned");
      fireEvent.change(screen.getByLabelText("Review comment"), {
        target: { value: "Unsent octocoral health observation" },
      });
      const retry = await screen.findByRole("button", {
        name: "Retry desktop close protection",
      });
      const unload = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(unload);
      expect(unload.defaultPrevented).toBe(true);
      expect(addReviewQueueEvent).not.toHaveBeenCalled();

      fireEvent.click(retry);
      await waitFor(() => expect(getCurrentWindow).toHaveBeenCalledTimes(2));
      await waitFor(() =>
        expect(
          screen.queryByRole("button", {
            name: "Retry desktop close protection",
          }),
        ).toBeNull(),
      );
      const preventDefault = vi.fn();
      act(() => closeHandler?.({ preventDefault }));
      expect(preventDefault).toHaveBeenCalledTimes(1);
      expect(screen.getByLabelText("Review comment")).toHaveProperty(
        "value",
        "Unsent octocoral health observation",
      );
      fireEvent.change(screen.getByLabelText("Review comment"), {
        target: { value: "" },
      });
      await waitFor(() => expect(unlisten).toHaveBeenCalledTimes(1));
    },
  );

  it("retains the exact uncertain event UUID when native registration throws synchronously", async () => {
    onCloseRequested.mockImplementationOnce(() => {
      throw new Error("Native listener not initialized");
    });
    vi.mocked(addReviewQueueEvent)
      .mockRejectedValueOnce(new Error("Lost server response"))
      .mockImplementationOnce(async (queueId, itemId, payload) => ({
        id: "event-replayed",
        project_id: "project-a",
        review_queue_id: queueId,
        review_queue_item_id: itemId,
        client_request_id: payload.client_request_id,
        event_type: payload.event_type,
        actor: payload.actor,
        comment: payload.comment ?? null,
        assignee: payload.assignee ?? null,
        created_at: "2026-10-31T12:00:00Z",
      }));
    mount();
    await screen.findByText("Assigned reviewer: Unassigned");
    fireEvent.change(screen.getByLabelText("Your local reviewer label"), {
      target: { value: "researcher" },
    });
    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Uncertain coral observation" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
    await screen.findByRole("button", { name: "Retry event" });
    const retryGuard = await screen.findByRole("button", {
      name: "Retry desktop close protection",
    });
    const original = vi.mocked(addReviewQueueEvent).mock.calls[0];
    expect(original?.[2].client_request_id).toBeTruthy();
    fireEvent.click(retryGuard);
    await waitFor(() => expect(onCloseRequested).toHaveBeenCalledTimes(2));
    const preventDefault = vi.fn();
    act(() => closeHandler?.({ preventDefault }));
    expect(preventDefault).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Retry event" }));
    await waitFor(() => expect(addReviewQueueEvent).toHaveBeenCalledTimes(2));
    expect(vi.mocked(addReviewQueueEvent).mock.calls[1]).toEqual(original);
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Retry event" })).toBeNull(),
    );
    expect(screen.getByLabelText("Review comment")).toHaveProperty("value", "");
    await waitFor(() => expect(unlisten).toHaveBeenCalledTimes(1));
  });
});
