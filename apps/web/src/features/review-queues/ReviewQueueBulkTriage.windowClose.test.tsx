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

import {
  bulkTriageReviewQueueItems,
  type ReviewQueueItem,
} from "../../api/client";
import { ReviewQueueBulkTriage } from "./ReviewQueueBulkTriage";

vi.mock("@tauri-apps/api/core", () => ({ isTauri: vi.fn() }));
vi.mock("@tauri-apps/api/window", () => ({ getCurrentWindow: vi.fn() }));
vi.mock("../../api/client", () => ({ bulkTriageReviewQueueItems: vi.fn() }));

const items = [
  {
    id: "coral-1",
    image_id: "frame-1",
    rank_position: 1,
    review_state: "pending",
  },
] as ReviewQueueItem[];

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ReviewQueueBulkTriage queueId="queue-1" items={items} />
    </QueryClientProvider>,
  );
}

function submitBulkReview() {
  fireEvent.change(screen.getByLabelText("Bulk triage reviewer label"), {
    target: { value: "coral researcher" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: /Select eligible on page/ }),
  );
  fireEvent.click(screen.getByLabelText("Confirm manual triage"));
  fireEvent.click(
    screen.getByRole("button", { name: "Apply start to 1 items" }),
  );
}

function validResult() {
  return {
    queue_id: "queue-1",
    action: "start" as const,
    changed_count: 1,
    items: [
      {
        ...items[0],
        review_queue_id: "queue-1",
        review_state: "in_progress" as const,
      },
    ] as ReviewQueueItem[],
    requires_researcher_review: true,
  };
}

describe("bulk QC browser and native window-close integrity", () => {
  let closeHandler:
    | ((event: { preventDefault: () => void }) => void)
    | undefined;
  let unlisten: ReturnType<typeof vi.fn>;
  let onCloseRequested: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    closeHandler = undefined;
    unlisten = vi.fn();
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
  });

  it("does not block idle desktop closure or register a listener", () => {
    mount();
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
    expect(onCloseRequested).not.toHaveBeenCalled();
  });

  it("blocks native close through an uncertain response and preserves the exact retry UUID", async () => {
    let rejectRequest!: (error: Error) => void;
    const pending = new Promise<
      Awaited<ReturnType<typeof bulkTriageReviewQueueItems>>
    >(
      (_resolve, reject) => {
        rejectRequest = reject;
      },
    );
    vi.mocked(bulkTriageReviewQueueItems)
      .mockReturnValueOnce(pending)
      .mockResolvedValueOnce(validResult());
    mount();
    submitBulkReview();
    await waitFor(() => expect(onCloseRequested).toHaveBeenCalledTimes(1));
    const original = vi.mocked(bulkTriageReviewQueueItems).mock.calls[0];
    const before = vi.fn();
    act(() => closeHandler?.({ preventDefault: before }));
    expect(before).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Desktop window close was blocked/)).toBeTruthy();

    await act(async () => {
      rejectRequest(new Error("Response lost after server commit"));
      try {
        await pending;
      } catch {
        // The uncertain result must remain available for exact retry.
      }
    });
    await screen.findByRole("button", { name: "Retry identical bulk action" });
    const uncertainClose = vi.fn();
    act(() => closeHandler?.({ preventDefault: uncertainClose }));
    expect(uncertainClose).toHaveBeenCalledTimes(1);
    fireEvent.click(
      screen.getByRole("button", { name: "Retry identical bulk action" }),
    );
    await waitFor(() =>
      expect(bulkTriageReviewQueueItems).toHaveBeenCalledTimes(2),
    );
    expect(vi.mocked(bulkTriageReviewQueueItems).mock.calls[1]).toEqual(
      original,
    );
    await waitFor(() => expect(unlisten).toHaveBeenCalledTimes(1));
    const after = vi.fn();
    act(() => closeHandler?.({ preventDefault: after }));
    expect(after).not.toHaveBeenCalled();
  });

  it("blocks browser reload for an uncertain request until explicit discard", async () => {
    vi.mocked(isTauri).mockReturnValue(false);
    vi.mocked(bulkTriageReviewQueueItems).mockRejectedValueOnce(
      new Error("Bulk response lost"),
    );
    mount();
    submitBulkReview();
    await screen.findByRole("button", { name: "Retry identical bulk action" });
    const guarded = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(guarded);
    expect(guarded.defaultPrevented).toBe(true);
    expect(getCurrentWindow).not.toHaveBeenCalled();

    fireEvent.click(
      screen.getByRole("button", { name: "Review discard risk" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Discard and refresh" }),
    );
    await waitFor(() => {
      const after = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(after);
      expect(after.defaultPrevented).toBe(false);
    });
    expect(bulkTriageReviewQueueItems).toHaveBeenCalledTimes(1);
  });

  it("offers a retry if native close interception fails without changing the bulk request", async () => {
    onCloseRequested.mockRejectedValueOnce(new Error("Listener unavailable"));
    vi.mocked(bulkTriageReviewQueueItems).mockRejectedValueOnce(
      new Error("Uncertain server outcome"),
    );
    mount();
    submitBulkReview();
    const retry = await screen.findByRole("button", {
      name: "Retry bulk desktop close protection",
    });
    const original = vi.mocked(bulkTriageReviewQueueItems).mock.calls[0];
    fireEvent.click(retry);
    await waitFor(() => expect(onCloseRequested).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(
        screen.queryByRole("button", {
          name: "Retry bulk desktop close protection",
        }),
      ).toBeNull(),
    );
    const prevented = vi.fn();
    act(() => closeHandler?.({ preventDefault: prevented }));
    expect(prevented).toHaveBeenCalledTimes(1);
    expect(vi.mocked(bulkTriageReviewQueueItems).mock.calls[0]).toEqual(
      original,
    );
    expect(bulkTriageReviewQueueItems).toHaveBeenCalledTimes(1);
  });

  it.each(["window accessor", "listener registration"] as const)(
    "keeps the original bulk request recoverable when %s throws synchronously",
    async (failure) => {
      if (failure === "window accessor") {
        vi.mocked(getCurrentWindow).mockImplementationOnce(() => {
          throw new Error("Desktop window unavailable");
        });
      } else {
        onCloseRequested.mockImplementationOnce(() => {
          throw new Error("Native listener unavailable");
        });
      }
      vi.mocked(bulkTriageReviewQueueItems)
        .mockRejectedValueOnce(new Error("Bulk response lost"))
        .mockResolvedValueOnce(validResult());
      mount();
      submitBulkReview();
      const retryGuard = await screen.findByRole("button", {
        name: "Retry bulk desktop close protection",
      });
      const original = vi.mocked(bulkTriageReviewQueueItems).mock.calls[0];
      const browserClose = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(browserClose);
      expect(browserClose.defaultPrevented).toBe(true);

      fireEvent.click(retryGuard);
      await waitFor(() => expect(getCurrentWindow).toHaveBeenCalledTimes(2));
      await waitFor(() =>
        expect(
          screen.queryByRole("button", {
            name: "Retry bulk desktop close protection",
          }),
        ).toBeNull(),
      );
      const prevented = vi.fn();
      act(() => closeHandler?.({ preventDefault: prevented }));
      expect(prevented).toHaveBeenCalledTimes(1);
      expect(bulkTriageReviewQueueItems).toHaveBeenCalledTimes(1);

      fireEvent.click(
        screen.getByRole("button", { name: "Retry identical bulk action" }),
      );
      await waitFor(() =>
        expect(bulkTriageReviewQueueItems).toHaveBeenCalledTimes(2),
      );
      expect(vi.mocked(bulkTriageReviewQueueItems).mock.calls[1]).toEqual(
        original,
      );
    },
  );

  it("cleans up a native listener that resolves after the request completes", async () => {
    let resolveListener!: (stop: () => void) => void;
    const subscription = new Promise<() => void>((resolve) => {
      resolveListener = resolve;
    });
    onCloseRequested.mockImplementationOnce(
      async (callback: (event: { preventDefault: () => void }) => void) => {
        closeHandler = callback;
        return subscription;
      },
    );
    let resolveRequest!: (
      value: Awaited<ReturnType<typeof bulkTriageReviewQueueItems>>,
    ) => void;
    const pending = new Promise<
      Awaited<ReturnType<typeof bulkTriageReviewQueueItems>>
    >(
      (resolve) => {
        resolveRequest = resolve;
      },
    );
    vi.mocked(bulkTriageReviewQueueItems).mockReturnValueOnce(pending);
    mount();
    submitBulkReview();
    await waitFor(() => expect(onCloseRequested).toHaveBeenCalledTimes(1));
    await act(async () => {
      resolveRequest(validResult());
      await pending;
    });
    await screen.findByText(/scientific review remains required/);
    await act(async () => {
      resolveListener(unlisten);
      await subscription;
    });
    await waitFor(() => expect(unlisten).toHaveBeenCalledTimes(1));
    const after = vi.fn();
    act(() => closeHandler?.({ preventDefault: after }));
    expect(after).not.toHaveBeenCalled();
  });
});
