import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  completeReviewQueueItem,
  getDatasetVersionQualityControlRuns,
  getDatasetVersionReviewQueues,
  getDatasetVersions,
  getQualityControlRuns,
  getReviewQueueItems,
  getReviewQueues,
  startReviewQueueItem,
  type Project,
  type ReviewQueueRecord,
} from "../../api/client";
import { ReviewQueueDashboard } from "./ReviewQueueDashboard";

vi.mock("../../api/client", () => ({
  completeReviewQueueItem: vi.fn(),
  startReviewQueueItem: vi.fn(),
  skipReviewQueueItem: vi.fn(),
  returnReviewQueueItem: vi.fn(),
  getDatasetVersionQualityControlRuns: vi.fn(),
  getDatasetVersionReviewQueues: vi.fn(),
  getDatasetVersions: vi.fn(),
  getQualityControlRuns: vi.fn(),
  getReviewQueueItems: vi.fn(),
  getReviewQueues: vi.fn(),
}));
vi.mock("./QuickConfidenceReviewDialog", () => ({
  QuickConfidenceReviewDialog: () => null,
}));
vi.mock("./ReviewQueueBulkTriage", () => ({
  ReviewQueueBulkTriage: () => null,
}));
vi.mock("./ReviewQueueCoordinationPanel", () => ({
  ReviewQueueCoordinationPanel: () => null,
}));

function queue(id: string): ReviewQueueRecord {
  return {
    id,
    created_at: "2026-10-23T12:00:00Z",
    formula_id: "qc",
    formula_version: "1",
    status: "complete",
    item_count: 0,
    configuration_json: {},
  } as unknown as ReviewQueueRecord;
}

function project(id: string): Project {
  return { id, label_classes: [] } as unknown as Project;
}

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onSelectedQueueChange = vi.fn();
  const view = (id: string) => (
    <QueryClientProvider client={client}>
      <ReviewQueueDashboard
        project={project(id)}
        onOpenImage={vi.fn()}
        onSelectedQueueChange={onSelectedQueueChange}
      />
    </QueryClientProvider>
  );
  const result = render(view("project-a"));
  return { ...result, view, onSelectedQueueChange };
}

describe("ReviewQueueDashboard scope isolation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getDatasetVersions).mockResolvedValue([
      { id: "dataset-1", version_number: 1, name: "Frozen set" },
    ] as Awaited<ReturnType<typeof getDatasetVersions>>);
    vi.mocked(getQualityControlRuns).mockResolvedValue([]);
    vi.mocked(getDatasetVersionQualityControlRuns).mockResolvedValue([]);
    vi.mocked(getReviewQueues).mockImplementation(async (id) => [
      queue(id === "project-a" ? "queue-a" : "queue-b"),
    ]);
    vi.mocked(getDatasetVersionReviewQueues).mockResolvedValue([
      queue("dataset-queue"),
    ]);
    vi.mocked(getReviewQueueItems).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 25,
      pages: 1,
    } as Awaited<ReturnType<typeof getReviewQueueItems>>);
  });

  it("does not fetch items from the previous project after navigation", async () => {
    const { rerender, view, onSelectedQueueChange } = mount();
    await waitFor(() => {
      expect(getReviewQueueItems).toHaveBeenCalledWith(
        "queue-a",
        expect.any(Object),
        expect.anything(),
      );
    });
    vi.mocked(getReviewQueueItems).mockClear();
    rerender(view("project-b"));
    await waitFor(() => {
      expect(getReviewQueueItems).toHaveBeenCalledWith(
        "queue-b",
        expect.any(Object),
        expect.anything(),
      );
    });
    const calls = vi.mocked(getReviewQueueItems).mock.calls;
    const queueIds = calls.map(([id]) => id);
    expect(queueIds.every((id) => id === "queue-b")).toBe(true);
    expect(onSelectedQueueChange).toHaveBeenLastCalledWith("queue-b");
  });

  it("drops a prior project's dataset-version selection before fetching", async () => {
    const { rerender, view } = mount();
    await waitFor(() => expect(getReviewQueueItems).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText("Scope"), {
      target: { value: "dataset_version" },
    });
    fireEvent.change(await screen.findByLabelText("Dataset version"), {
      target: { value: "dataset-1" },
    });
    await waitFor(() =>
      expect(getReviewQueueItems).toHaveBeenCalledWith(
        "dataset-queue",
        expect.any(Object),
        expect.anything(),
      ),
    );
    vi.mocked(getDatasetVersionReviewQueues).mockClear();
    vi.mocked(getReviewQueueItems).mockClear();
    rerender(view("project-b"));
    await waitFor(() =>
      expect(getReviewQueueItems).toHaveBeenCalledWith(
        "queue-b",
        expect.any(Object),
        expect.anything(),
      ),
    );
    expect(getDatasetVersionReviewQueues).not.toHaveBeenCalled();
    const calls = vi.mocked(getReviewQueueItems).mock.calls;
    const queueIds = calls.map(([id]) => id);
    expect(queueIds.every((id) => id === "queue-b")).toBe(true);
  });

  it("never falls back to project queues while dataset version is unset", async () => {
    mount();
    await waitFor(() => expect(getReviewQueueItems).toHaveBeenCalled());
    vi.mocked(getReviewQueues).mockClear();
    vi.mocked(getReviewQueueItems).mockClear();
    fireEvent.change(screen.getByLabelText("Scope"), {
      target: { value: "dataset_version" },
    });
    await screen.findByLabelText("Dataset version");
    const sourceRunSelect = screen.getByLabelText("Source QC run");
    const generateButton = screen.getByRole("button", {
      name: "Generate queue",
    });
    expect(sourceRunSelect.hasAttribute("disabled")).toBe(true);
    expect(generateButton.hasAttribute("disabled")).toBe(true);
    expect(getDatasetVersionQualityControlRuns).not.toHaveBeenCalled();
    expect(getReviewQueues).not.toHaveBeenCalled();
    expect(getDatasetVersionReviewQueues).not.toHaveBeenCalled();
    expect(getReviewQueueItems).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Dataset version"), {
      target: { value: "dataset-1" },
    });
    await waitFor(() => {
      expect(getReviewQueueItems).toHaveBeenCalledWith(
        "dataset-queue",
        expect.any(Object),
        expect.anything(),
      );
    });
    const calls = vi.mocked(getReviewQueueItems).mock.calls;
    const queueIds = calls.map(([id]) => id);
    expect(queueIds.every((id) => id === "dataset-queue")).toBe(true);
  });

  it(
    "requires a reviewer label and confirmation before single-item completion",
    async () => {
      vi.mocked(getReviewQueueItems).mockResolvedValue({
        items: [
          {
            id: "item-1",
            image_id: "image-1",
            rank_position: 1,
            score: 0.6,
            score_breakdown_json: [],
            review_state: "pending",
          },
        ],
        total: 1,
        page: 1,
        page_size: 25,
        pages: 1,
      } as Awaited<ReturnType<typeof getReviewQueueItems>>);
      vi.mocked(completeReviewQueueItem).mockResolvedValue(
        {} as Awaited<ReturnType<typeof completeReviewQueueItem>>,
      );
      vi.mocked(startReviewQueueItem).mockResolvedValue(
        {} as Awaited<ReturnType<typeof startReviewQueueItem>>,
      );
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
      try {
        mount();
        const complete = await screen.findByRole("button", {
          name: "Mark complete",
        });
        const start = screen.getByRole("button", { name: "Start review" });
        expect(complete.hasAttribute("disabled")).toBe(true);
        expect(start.hasAttribute("disabled")).toBe(true);
        fireEvent.change(screen.getByLabelText("Single-item reviewer label"), {
          target: { value: "  reef-scientist  " },
        });
        expect(complete.hasAttribute("disabled")).toBe(false);
        fireEvent.click(complete);
        expect(confirm).toHaveBeenCalledTimes(1);
        expect(completeReviewQueueItem).not.toHaveBeenCalled();

        confirm.mockReturnValue(true);
        fireEvent.click(complete);
        await waitFor(() =>
          expect(completeReviewQueueItem).toHaveBeenCalledWith(
            "item-1",
            "reef-scientist",
            true,
          ),
        );
        expect(confirm.mock.calls[0][0]).toMatch(
          /does not verify model predictions/,
        );
        fireEvent.click(start);
        await waitFor(() =>
          expect(startReviewQueueItem).toHaveBeenCalledWith(
            "item-1",
            "reef-scientist",
          ),
        );
      } finally {
        confirm.mockRestore();
      }
    },
  );
});
